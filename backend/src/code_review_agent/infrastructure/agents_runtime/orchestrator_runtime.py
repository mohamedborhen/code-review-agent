"""Orchestrator + Aggregator runtime: Layer 5 implementation of ReviewOrchestratorPort.

Design notes:
- All five specialist subagents are registered on the deep agent (the DoD
  requires all 7 agents constructed via create_deep_agent, and the aggregator
  is the root agent's synthesis phase). The per-request REQUIRED set comes from
  the routing policy and is spelled out in the user message; the orchestrator
  must delegate to each required agent, and may additionally invoke
  fix_suggestion once findings exist.
- ``response_format=SubagentReport`` is set on the root; deepagents propagates
  it to every subagent, so each subagent's ToolMessage content is a
  JSON-serialized SubagentReport — that is what per-agent audit rows are parsed
  from.
- The safety harness profile strips every built-in filesystem/execute tool; the
  agents hold exactly their scoped MCP tools (plus the root's `task` tool).
"""

import asyncio
import logging

from deepagents import (
    ProviderProfile,
    create_deep_agent,
    register_provider_profile,
)
from deepagents.backends.state import StateBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from application.conversation_service.summarize_conversation import summarize_conversation
from domain.entities.agent_finding import AgentInput, ReviewResult
from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.harness_profile import ensure_review_harness_profile
from infrastructure.agents_runtime.memory_tools import build_shared_memory_tools
from infrastructure.agents_runtime.middleware import (
    DiffInjectionMiddleware,
    RootTimingMiddleware,
    TransientRetryMiddleware,
)
from infrastructure.agents_runtime.orchestrator_emit import _emit_events, _extract_per_agent
from infrastructure.agents_runtime.orchestrator_message import _build_user_message
from infrastructure.agents_runtime.orchestrator_parsing import (
    _coerce_report,
    _enforce_evidence_discipline,
    _parse_aggregated,
    _parse_tool_message,
)
from infrastructure.agents_runtime.orchestrator_retry import _run_with_retry
from infrastructure.agents_runtime.report_schema import SubagentReport
from infrastructure.agents_runtime.subagents.compliance_runtime import build_compliance_spec
from infrastructure.agents_runtime.subagents.context_agent_runtime import get_audited_context_tool
from infrastructure.agents_runtime.subagents.fix_suggestion_runtime import build_fix_suggestion_spec
from infrastructure.agents_runtime.subagents.performance_runtime import build_performance_spec
from infrastructure.agents_runtime.subagents.regression_runtime import build_regression_spec
from infrastructure.agents_runtime.subagents.security_runtime import build_security_spec
from infrastructure.agents_runtime.tool_scoping import load_prompt
from infrastructure.config import settings
from infrastructure.db.conversation_ports_adapters import SQLModelConversationAudit
from infrastructure.db.conversation_repository import SQLModelConversationRepository

logger = logging.getLogger(__name__)

_SUBAGENT_BUILDERS = {
    "compliance": build_compliance_spec,
    "security": build_security_spec,
    "performance": build_performance_spec,
    "regression": build_regression_spec,
    "fix_suggestion": build_fix_suggestion_spec,
}

_ALL_SUBAGENTS = list(_SUBAGENT_BUILDERS)


def _ensure_review_provider_profile() -> None:
    """Cap output tokens via a deepagents ProviderProfile.

    Registered under the exact `settings.review_model` key so deepagents'
    resolve_model forwards `max_tokens` to init_chat_model while the model
    stays a STRING — preserving the exact-key HarnessProfile lookup (see
    harness_profile.py). Keeps the OpenRouter free tier from rejecting the
    model's full 16k output window as unaffordable.
    """
    register_provider_profile(
        settings.review_model,
        ProviderProfile(
            init_kwargs={
                "max_tokens": settings.review_max_tokens,
                "timeout": settings.review_timeout,
            }
        ),
    )


class OrchestratorRuntime:
    """Builds and runs the deep agent (orchestrator + aggregator in one)."""

    def __init__(
        self,
        mcp_client,
        review_session_id: int | None = None,
        memory_store=None,
        tool_call_repo=None,
    ) -> None:
        self._mcp_client = mcp_client
        self._review_session_id = review_session_id
        self._memory_store = memory_store
        self._tool_call_repo = tool_call_repo
        self.capture = CaptureStore()

    async def run_review(self, review_input: AgentInput, agent_names: list[str]) -> ReviewResult:
        ensure_review_harness_profile()
        _ensure_review_provider_profile()

        subagent_specs = []
        if agent_names:
            for name in _ALL_SUBAGENTS:
                spec = await _SUBAGENT_BUILDERS[name](
                    self._mcp_client, self.capture, self._review_session_id, self._tool_call_repo
                )
                middleware = list(spec.get("middleware") or [])
                middleware.append(TransientRetryMiddleware())
                spec["middleware"] = middleware
                subagent_specs.append(spec)

        system_prompt = load_prompt("orchestrator") + "\n\n" + load_prompt("aggregator")

        backend = StateBackend()

        root_middleware = [
            RootTimingMiddleware(self.capture),
            DiffInjectionMiddleware(review_input.diff_content),
            SummarizationMiddleware(
                model=settings.review_model,
                backend=backend,
                trigger=("tokens", settings.summarization_trigger_tokens),
                keep=("tokens", settings.summarization_keep_tokens),
                token_counter=count_tokens_approximately,
            ),
            TransientRetryMiddleware(),
        ]

        root_tools = await _build_root_tools(
            review_input, self._mcp_client, self._review_session_id, self.capture, self._tool_call_repo
        )

        context_available = any(t.name == "search_messages" for t in root_tools)
        user_message = _build_user_message(
            review_input, agent_names, context_available=context_available
        )

        agent = create_deep_agent(
            model=settings.review_model,
            system_prompt=system_prompt,
            subagents=subagent_specs or None,
            response_format=SubagentReport,
            middleware=root_middleware,
            tools=root_tools,
            backend=backend,
            store=self._memory_store,
        )

        run_config = {
            "configurable": {
                "user_id": review_input.user_id or "anonymous",
                "repo_id": review_input.repo_id,
            }
        }

        result = await _run_with_retry(agent, user_message, config=run_config)
        messages = result.get("messages", [])

        await _emit_events(messages)

        aggregated = _parse_aggregated(result)
        _enforce_evidence_discipline(aggregated)
        return ReviewResult(
            aggregated=aggregated,
            per_agent=_extract_per_agent(messages, self.capture),
        )

    async def write_durable_conversation_summary(self, review_input: AgentInput) -> None:
        """Persist a durable MemorySummary for a conversation-scoped review run."""
        if review_input.conversation_id is None:
            return
        try:
            await _write_durable_conversation_summary(review_input)
        except Exception as exc:  # noqa: BLE001 - summary must never fail the review
            logger.warning(
                "Durable conversation summary failed for conversation %s: %s",
                review_input.conversation_id,
                exc,
            )


async def _build_root_tools(
    review_input: AgentInput, mcp_client, review_session_id: int | None, store: CaptureStore,
    tool_call_repo=None,
) -> list:
    """Return the root agent's tool list (never None — the root is never tool-less)."""
    tools = build_shared_memory_tools()
    if review_input.conversation_id is None:
        return tools
    if review_input.user_id is None:
        return tools
    audited_context_tool = await get_audited_context_tool(
        mcp_client,
        conversation_id=review_input.conversation_id,
        user_id=review_input.user_id,
        repo_id=review_input.repo_id,
        audit=SQLModelConversationAudit(),
        review_session_id=review_session_id,
        store=store,
        tool_call_repo=tool_call_repo,
    )
    if audited_context_tool is not None:
        tools.append(audited_context_tool)
    return tools


async def _write_durable_conversation_summary(review_input: AgentInput) -> None:
    """Persist a durable MemorySummary for a review run (PHASE_4.md §5.3)."""
    store = SQLModelConversationRepository()
    messages = await asyncio.to_thread(store.list_messages, review_input.conversation_id)
    recent_messages = [m.content for m in messages if m and m.content]
    if not recent_messages:
        return
    await summarize_conversation(
        review_input.conversation_id,
        store=store,
        recent_messages=recent_messages,
        llm_summarizer=_build_llm_summarizer(),
    )


def _build_llm_summarizer():
    """Async ``list[str] -> str`` callable wrapping settings.review_model."""

    async def _summarize(recent_messages: list[str]) -> str:
        model = init_chat_model(
            settings.review_model,
            max_tokens=settings.review_max_tokens,
            timeout=settings.review_timeout,
        )
        prompt = (
            "Summarize this review session concisely. Cover the user's request, "
            "the evidence reviewed, and the conclusions reached.\n\n"
            + "\n".join(f"- {m}" for m in recent_messages)
        )
        response = await model.ainvoke([HumanMessage(content=prompt)])
        content = response.content
        return content if isinstance(content, str) else str(content)

    return _summarize

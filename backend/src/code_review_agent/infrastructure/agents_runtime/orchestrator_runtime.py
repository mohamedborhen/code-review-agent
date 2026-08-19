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
import json
import logging
import re

from deepagents import (
    ProviderProfile,
    create_deep_agent,
    register_provider_profile,
)
from deepagents.backends.state import StateBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

from application.conversation_service.summarize_conversation import summarize_conversation
from domain.entities.agent_finding import AgentFinding, AgentInput, AgentOutput, ReviewResult
from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.harness_profile import ensure_review_harness_profile
from infrastructure.agents_runtime.memory_tools import build_shared_memory_tools
from infrastructure.agents_runtime.middleware import (
    DiffInjectionMiddleware,
    RootTimingMiddleware,
    TransientRetryMiddleware,
    _is_transient_provider_error,
)
from infrastructure.agents_runtime.report_parse import extract_json_text as _extract_json
from infrastructure.agents_runtime.report_schema import FindingItem, SubagentReport
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
from infrastructure.event_bus.log_event_bus import log_event

logger = logging.getLogger(__name__)

_SUBAGENT_BUILDERS = {
    "compliance": build_compliance_spec,
    "security": build_security_spec,
    "performance": build_performance_spec,
    "regression": build_regression_spec,
    "fix_suggestion": build_fix_suggestion_spec,
}

_ALL_SUBAGENTS = list(_SUBAGENT_BUILDERS)

# Typed request types that carry an optional user question: the single-
# specialist questions (compliance/security/performance/impact) forward the
# `question` field so the user can steer the specialist (e.g. a ticket key to
# check). `review` (full pipeline) forwards it too so users can give the
# orchestrator both the diff and a linked Jira ticket key in one prompt.
# `explain_question` (direct answer) stays without one.
_QUESTION_CARRYING_TYPES = frozenset(
    {"review", "compliance_question", "security_question", "performance_question", "impact_question"}
)


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
    ) -> None:
        self._mcp_client = mcp_client
        self._review_session_id = review_session_id
        # The single process-wide AsyncSqliteStore built in main.py's lifespan.
        # Passed to create_deep_agent(store=...) so the LangMem memory tools
        # (constructed without store=) resolve it at runtime (PHASE_4.md §6.1).
        self._memory_store = memory_store
        self.capture = CaptureStore()

    async def run_review(self, review_input: AgentInput, agent_names: list[str]) -> ReviewResult:
        ensure_review_harness_profile()
        _ensure_review_provider_profile()

        subagent_specs = []
        if agent_names:
            for name in _ALL_SUBAGENTS:
                spec = await _SUBAGENT_BUILDERS[name](self._mcp_client, self.capture)
                middleware = list(spec.get("middleware") or [])
                middleware.append(TransientRetryMiddleware())
                spec["middleware"] = middleware
                subagent_specs.append(spec)

        system_prompt = load_prompt("orchestrator") + "\n\n" + load_prompt("aggregator")

        # One StateBackend shared by BOTH the agent graph and the explicit
        # SummarizationMiddleware — deepagents' auto-built summarization reads
        # the same backend for conversation-history offload, so splitting them
        # would silently break that coupling (PHASE_4.md §5.2).
        backend = StateBackend()

        root_middleware = [
            RootTimingMiddleware(self.capture),
            DiffInjectionMiddleware(review_input.diff_content),
            # Explicit in-context summarization budget (PHASE_4.md §5.2): the
            # configured model's `profile` is `{}`, so deepagents' auto-detection
            # falls back to a flat 170k-token trigger. The model's real window is
            # 262,144 tokens, so Phase 4 configures 85% / 10% explicitly. This
            # instance REPLACES deepagents' auto-added one by name
            # ("SummarizationMiddleware"), keeping exactly one summarization
            # node in the compiled graph (verified, PHASE_4.md §9 Q1).
            SummarizationMiddleware(
                model=settings.review_model,
                backend=backend,
                trigger=("tokens", settings.summarization_trigger_tokens),
                keep=("tokens", settings.summarization_keep_tokens),
                token_counter=count_tokens_approximately,
            ),
            TransientRetryMiddleware(),
        ]

        # Root-agent tools: the shared long-term memory tool pair is ALWAYS
        # granted (every agent owns shared memory). When historical
        # conversation context is AVAILABLE (conversation_id supplied), the
        # Context Agent's single read-only search_messages tool is granted too,
        # so the orchestrator can recall evidence BEFORE delegating. Recall is
        # optional — the orchestrator decides — so the tool is only made
        # reachable, never invoked on our behalf. deepagents merges the `tools`
        # argument additively with the built-in suite, so `task` is preserved;
        # the harness profile still strips the filesystem/execute built-ins.
        root_tools = await _build_root_tools(
            review_input, self._mcp_client, self._review_session_id, self.capture
        )

        # The conversation-context prompt block must match what the root agent
        # was actually granted: only declare context AVAILABLE when the context
        # tool was successfully built (server up / registered). On the degraded
        # path (server down) the tool is withheld, so the block is omitted too —
        # otherwise the model is told it has a tool it does not (finding F2).
        # The shared memory tools are always present but need no prompt block.
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

        # Identity flows ONLY via config.configurable (PHASE_4.md §6.2): the
        # LangMem memory tools resolve their {user_id}/{repo_id} namespace
        # placeholders from here at ainvoke time — never an LLM tool argument.
        # Sourced from trusted AgentInput values (caller-supplied tenant keys,
        # PHASE_4.md §2 "Identity source").
        run_config = {
            "configurable": {
                "user_id": review_input.user_id or "anonymous",
                "repo_id": review_input.repo_id,
            }
        }

        result = await _run_with_retry(agent, user_message, config=run_config)
        messages = result.get("messages", [])

        await _emit_events(messages)

        # Durable conversation summary (PHASE_4.md §5.3) is NOT awaited here:
        # the composition root (review route) schedules it as a FastAPI
        # BackgroundTask via write_durable_conversation_summary() so the summary
        # LLM call never extends the API response time. A background failure can
        # only be logged by that guard, never fail the review (review finding
        # F2, deviation D-P4-4).
        return ReviewResult(
            aggregated=_parse_aggregated(result),
            per_agent=_extract_per_agent(messages, self.capture),
        )

    async def write_durable_conversation_summary(self, review_input: AgentInput) -> None:
        """Persist a durable MemorySummary for a conversation-scoped review run.

        Scheduled by the review route as a FastAPI BackgroundTask AFTER the
        response is sent (PHASE_4.md §5.3; placement moved off the request path
        per review finding F2, deviation D-P4-4). The module-level helper may
        raise (test-pinned contract, test_memory_phase4.py:464); this guard
        absorbs DB/message errors so the background task never surfaces an
        unhandled exception and a memory-summary failure NEVER fails the
        review. No-op when the review was not scoped to a conversation.
        """
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
    review_input: AgentInput, mcp_client, review_session_id: int | None, store: CaptureStore
) -> list:
    """Return the root agent's tool list (never None — the root is never tool-less).

    The shared long-term memory tool pair (build_shared_memory_tools) is ALWAYS
    included (PHASE_4.md §6.2): every agent in a conversation owns shared
    memory. A conversation_id additionally makes the Context Agent's
    search_messages tool reachable; it never forces a recall (the orchestrator
    decides). The context tool is withheld (omitted, not returned as None) when
    the conversation/server path is unavailable, so callers detect "context
    withheld" by checking membership rather than None-vs-list semantics.

    Identity (conversation_id/user_id/repo_id) is bound into the context tool at
    construction time (PHASE_3.md §9.5) — the LLM supplies only the query.
    """
    tools = build_shared_memory_tools()
    if review_input.conversation_id is None:
        return tools
    if review_input.user_id is None:
        return tools  # defensive: the route 400s earlier (_validate_conversation_identity)
    audited_context_tool = await get_audited_context_tool(
        mcp_client,
        conversation_id=review_input.conversation_id,
        user_id=review_input.user_id,
        repo_id=review_input.repo_id,
        audit=SQLModelConversationAudit(),
        review_session_id=review_session_id,
        store=store,
    )
    if audited_context_tool is not None:
        tools.append(audited_context_tool)
    return tools


def _build_user_message(
    review_input: AgentInput, agent_names: list[str], context_available: bool = True
) -> str:
    if review_input.request_type == "any_question":
        pool = ", ".join(agent_names) if agent_names else "(none)"
        lines = [
            f"Request type: {review_input.request_type}",
            f"Repo: {review_input.repo_id}",
            f"Graph commit hash: {review_input.graph_commit_hash}",
            f"Repo root (local path): {review_input.repo_root}",
            "",
            "Subagents need BOTH the repo identifier (owner/name from `Repo:`) for "
            "their GitHub tools AND the repo-root path (from `Repo root (local path):`) "
            "for their CRG tools. Include both in every task description, never omit one.",
            "",
            "Question from the user:",
            review_input.question or "(no question provided)",
            "",
            "Available subagents (delegate to the one(s) relevant to this question — "
            "one, several, or none if it is answerable directly):",
            pool,
            "",
            "Investigate, then synthesize the answer into a single SubagentReport JSON.",
        ]
        text = "\n".join(lines)
    else:
        required = ", ".join(agent_names) if agent_names else "(none — answer directly)"
        lines = [
            f"Request type: {review_input.request_type}",
            f"Repo: {review_input.repo_id}",
            f"Graph commit hash: {review_input.graph_commit_hash}",
            f"Repo root (local path): {review_input.repo_root}",
            "",
            "Subagents need BOTH the repo identifier (owner/name from `Repo:`) for "
            "their GitHub tools AND the repo-root path (from `Repo root (local path):`) "
            "for their CRG tools. Include both in every task description, never omit one.",
            "",
            "Required subagents for this request type (you MUST delegate to each):",
            required,
        ]
        if review_input.request_type in _QUESTION_CARRYING_TYPES and review_input.question:
            lines.extend(
                [
                    "",
                    "Question from the user:",
                    review_input.question,
                ]
            )
        diff_instructions = (
            "The complete, unmodified diff for this review is appended automatically to every "
            "task description by the system — you must not reproduce, summarize, abbreviate, "
            "or reference the diff text yourself."
            if review_input.diff_content
            else "There is no separate diff parameter for this review: any diff content the user "
            "supplied lives inside the 'Question from the user:' section above. Forward that "
            "question verbatim into every task description so subagents see the exact diff."
        )
        lines.extend(
            [
                "",
                diff_instructions,
                "",
                "Classify the request, delegate to every required subagent, then synthesize all "
                "reports into a single SubagentReport JSON.",
            ]
        )
        text = "\n".join(lines)

    if review_input.conversation_id is not None and context_available:
        text += "\n\n" + _conversation_context_block(review_input)
    return text


async def _write_durable_conversation_summary(review_input: AgentInput) -> None:
    """Persist a durable MemorySummary for a review run (PHASE_4.md §5.3).

    Runs AFTER the orchestrator run resolves successfully, when the review was
    scoped to a conversation. Uses Phase 3's `ConversationStorePort`
    implementation (SQLModelConversationRepository) and the upgraded
    `summarize_conversation` use-case with an injected LLM summarizer built
    around `settings.review_model`. The use-case falls back to its
    deterministic tail summary on any LLM failure; the CALLER (run_review)
    wraps this whole helper in try/except so DB/message errors also never fail
    the review.

    The message list is pre-fetched through asyncio.to_thread (sync SQLite, per
    the async/sync boundary rule); the only in-loop sync SQLite left is the
    use-case's own brief latest-message-id lookup + single MemorySummary INSERT.
    """
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
    """Async ``list[str] -> str`` callable wrapping settings.review_model.

    Constructs the model lazily (inside the callable) and summarizes the
    plain-text message run with a short user prompt — no system-prompt
    override needed. Any exception propagates to the use-case's fallback
    (PHASE_4.md §5.3).

    The ProviderProfile registered by ``_ensure_review_provider_profile`` only
    applies to models resolved THROUGH deepagents (create_deep_agent) — this
    call bypasses that path, so the same ``max_tokens``/``timeout`` init kwargs
    are applied explicitly (review finding F1): without ``max_tokens`` the
    OpenRouter free tier rejects the full output window and the summary
    silently degrades to the deterministic fallback; without ``timeout`` a hung
    provider could hold the request open past ``review_timeout``.
    """

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


def _conversation_context_block(review_input: AgentInput) -> str:
    """Prompt block declaring historical context AVAILABLE (never mandatory).

    The orchestrator owns the recall decision (PHASE_3.md §6): conversation_id
    only makes search_messages reachable. Identity is closure-bound into the
    tool at construction time (§9.5), so the LLM no longer supplies — or sees —
    conversation_id/user_id/repo_id; it only provides the search query. When
    recall is warranted it must run BEFORE specialist delegation; results are
    evidence with message_id provenance — never a ready-made answer — and the
    most recent message wins on contradiction (§9.7).
    """
    return (
        "Historical conversation context is AVAILABLE (optional, not mandatory). "
        "The search_messages tool is pre-scoped to this conversation's identity — "
        "do not pass conversation_id/user_id/repo_id; they are supplied for you. "
        "You may call it ONLY if historical context is needed to answer this review; "
        "it is never required and must never be called on every request. If you call "
        "it, do so BEFORE delegating to subagents, treat the results as evidence "
        "(never answer from a single snippet — reason over all of them), retain the "
        "message_id of every hit you rely on, and when two recalled messages "
        "contradict, prefer the most recent one."
    )


def _index_task_calls(messages) -> dict[str, str]:
    """Map tool_call_id -> subagent_type for the root's `task` tool calls."""
    calls: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for tc in msg.tool_calls or []:
            if tc.get("name") == "task":
                subagent_type = (tc.get("args") or {}).get("subagent_type")
                if subagent_type:
                    calls[tc.get("id")] = subagent_type
    return calls


def _to_agent_output(report: SubagentReport) -> AgentOutput:
    findings = [
        AgentFinding(
            severity=item.severity,
            confidence=item.confidence,
            title=item.title,
            description=item.description,
            evidence=list(item.evidence),
            recommendation=item.recommendation,
        )
        for item in report.findings
    ]
    return AgentOutput(agent_name=report.agent_name, findings=findings)


def _parse_aggregated(result: dict) -> AgentOutput:
    structured = result.get("structured_response")
    if isinstance(structured, SubagentReport):
        return AgentOutput(agent_name="aggregator", findings=_to_agent_output(structured).findings)
    from_dict: AgentOutput | None = None
    if isinstance(structured, dict):
        try:
            report = SubagentReport.model_validate(structured)
            return AgentOutput(agent_name="aggregator", findings=_to_agent_output(report).findings)
        except Exception:
            pass
        try:
            report = _coerce_report(json.dumps(structured), "aggregator")
            report.agent_name = "aggregator"
            from_dict = AgentOutput(agent_name="aggregator", findings=_to_agent_output(report).findings)
        except Exception:
            logger.warning("Aggregator structured response did not match SubagentReport schema")
    # Weak-model fallback: deepagents occasionally returns the aggregator report
    # as plain final-message content instead of a native structured response
    # (session 50 — full findings in the `final` event but findings:[] in the
    # API). Parse the last AIMessage content through the same lenient path used
    # for subagent tool messages, and prefer it whenever it carries findings —
    # otherwise an empty dict structured response (`{}`) would short-circuit
    # with zero findings and throw the real report away.
    from_messages = _parse_aggregated_from_messages(result)
    if from_messages is not None and from_messages.findings:
        return from_messages
    if from_dict is not None:
        return from_dict
    if from_messages is not None:
        return from_messages
    logger.warning("No structured_response in orchestrator result; returning empty aggregated output")
    return AgentOutput(agent_name="aggregator")


def _parse_aggregated_from_messages(result: dict) -> AgentOutput | None:
    """Parse the aggregator report from the last AIMessage content, if any.

    Mirror of `_parse_tool_message`: strip fences/XML, coerce leniently, and
    return None only when no message parses (caller then falls back to empty).
    """
    for msg in reversed(result.get("messages", [])):
        if not isinstance(msg, AIMessage) or not msg.content:
            continue
        try:
            report = _coerce_report(_extract_json(str(msg.content)), "aggregator")
            report.agent_name = "aggregator"
            return AgentOutput(agent_name="aggregator", findings=_to_agent_output(report).findings)
        except Exception:
            continue
    return None


def _parse_tool_message(agent_name: str, content) -> AgentOutput:
    if not content:
        return AgentOutput(agent_name=agent_name)
    text = content.content if hasattr(content, "content") else str(content)
    text = _extract_json(text)
    try:
        raw = json.loads(text)
    except Exception:
        raw = None
    if isinstance(raw, dict) and "findings" not in raw and raw.get("violations"):
        # compliance-style report: pydantic's default ignores unknown top-level
        # keys, so strict validation would "succeed" with empty findings and
        # silently drop the violations — route straight to the tolerant path.
        return _to_agent_output(_coerce_report(text, agent_name))
    try:
        report = SubagentReport.model_validate_json(text)
        return _to_agent_output(report)
    except Exception:
        pass
    try:
        report = _coerce_report(text, agent_name)
        return _to_agent_output(report)
    except Exception:
        logger.warning("Could not parse structured subagent output for %s", agent_name)
        return AgentOutput(agent_name=agent_name)


_STRING_CONFIDENCE: dict[str, float] = {
    "low": 0.3,
    "medium": 0.6,
    "high": 0.9,
    "critical": 1.0,
}

_STRUCTURED_OUTPUT_FAILURE = re.compile(r"structured output|json|parse", re.IGNORECASE)


async def _run_with_retry(agent, user_message: str, config: dict | None = None, attempts: int = 3) -> dict:
    """Run the deep agent, retrying transient + structured-output failures.

    ``config`` is the run config carrying ``config.configurable`` identity
    (user_id/repo_id) that the LangMem memory tools resolve their namespace
    placeholders from (PHASE_4.md §6.2).

    Two failure classes are retried, each with a cadence matching its nature:

    - Provider-transient errors (429 / 5xx / rate limit / quota / socket
      timeout) — exponential backoff. These are mostly absorbed earlier by
      ``TransientRetryMiddleware`` at the individual model-call level; this
      whole-run retry is the outer safety net.
    - Structured-output parse failures (a weak-model failure mode observed
      during E2E, where the configured model returns an empty/invalid native
      structured output that deepagents surfaces as a parse error) — short
      delay, since they are not quota-bound.

    Everything else propagates immediately.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_message}]},
                config=config,
            )
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch for retry classification
            last = exc
            transient = _is_transient_provider_error(exc)
            structured = bool(_STRUCTURED_OUTPUT_FAILURE.search(str(exc)))
            if not (transient or structured):
                raise
            if attempt < attempts:
                delay = (2.0 * (2 ** (attempt - 1)) + 0.5) if transient else 0.5
                logger.warning(
                    "Retrying review run (attempt %s/%s) after %s: %s",
                    attempt,
                    attempts,
                    "transient provider error" if transient else "structured-output failure",
                    exc,
                )
                await asyncio.sleep(delay)
    raise last  # type: ignore[misc]


def _coerce_finding(item: dict) -> FindingItem:
    """Leniently coerce a raw finding dict into the strict FindingItem schema.

    Subagents regularly deviate from the exact schema — string confidences
    (``"high"``), evidence as dicts instead of list[str], a ``violations`` key
    instead of ``findings``. Without coercion those findings silently vanish
    from the AgentExecution audit rows. This is the single source of truth for
    the tolerant path; strict pydantic parsing is always attempted first.
    """
    confidence = item.get("confidence", 0.5)
    if isinstance(confidence, str):
        key = confidence.strip().lower()
        confidence = _STRING_CONFIDENCE.get(key, 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))

    evidence_raw = item.get("evidence")
    if not evidence_raw:
        evidence_raw = item.get("location")
    evidence: list[str] = []
    if isinstance(evidence_raw, str):
        evidence = [evidence_raw]
    else:
        for e in evidence_raw or []:
            if isinstance(e, str):
                evidence.append(e)
            else:
                evidence.append(json.dumps(e, ensure_ascii=False, default=str))

    if confidence == 0.5 and item.get("risk_score") is not None:
        try:
            confidence = min(1.0, max(0.0, float(item["risk_score"]) / 10.0))
        except (TypeError, ValueError):
            pass

    recommendation = item.get("recommendation")
    if not recommendation:
        recommendations = item.get("recommendations")
        if isinstance(recommendations, list):
            recommendation = "\n".join(str(r) for r in recommendations)
        elif recommendations:
            recommendation = str(recommendations)

    return FindingItem(
        severity=str(item.get("severity", "info")).lower(),
        confidence=confidence,
        title=str(item.get("title") or item.get("id") or ""),
        description=str(item.get("description", "")),
        evidence=evidence,
        recommendation=str(recommendation or ""),
    )


def _findings_list(raw: dict) -> list | None:
    """Locate the findings array under any of the shapes subagents emit.

    Subagents nest reports under domain keys (``security_review``,
    ``compliance_report``, ...) and vary the array name (``findings``,
    ``violations``, ``security_findings``, ...). Recurse one level into nested
    dicts so a report like ``{"security_review": {"findings": [...]}}`` parses.
    """
    for key in ("findings", "violations"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    for key, value in raw.items():
        if key.endswith("findings") and isinstance(value, list):
            return value
    for value in raw.values():
        if isinstance(value, dict):
            nested = _findings_list(value)
            if nested is not None:
                return nested
    return None


def _coerce_report(text: str, agent_name: str) -> SubagentReport:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        return SubagentReport(agent_name=agent_name)
    findings_raw = _findings_list(raw) or []
    findings = [
        _coerce_finding(item)
        for item in findings_raw
        if isinstance(item, dict)
    ]
    return SubagentReport(
        agent_name=str(raw.get("agent_name") or agent_name),
        findings=findings,
    )


def _looks_like_json_obj(content) -> bool:
    """True when the final ToolMessage content is at least a JSON object.

    A valid JSON object — even ``{"agent_name": ..., "findings": []}`` — is a
    genuine subagent verdict and must NOT be overwritten by the stashed-report
    recovery. Only prose/empty/garbage content (json.loads fails) qualifies for
    recovery.
    """
    if not content:
        return False
    text = content.content if hasattr(content, "content") else str(content)
    try:
        return isinstance(json.loads(_extract_json(text)), dict)
    except (TypeError, ValueError):
        return False


def _extract_per_agent(messages, capture: CaptureStore) -> list[AgentOutput]:
    task_calls = _index_task_calls(messages)
    outputs: list[AgentOutput] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        agent_name = task_calls.get(msg.tool_call_id)
        if agent_name is None:
            continue
        output = _parse_tool_message(agent_name, msg.content)
        if output.findings:
            outputs.append(output)
            continue
        if _looks_like_json_obj(msg.content):
            outputs.append(output)
            continue
        # Final message was prose/empty — the model likely emitted its real
        # report in an earlier message that the middleware stashed. Recover it.
        stashed = capture.consume_report(agent_name)
        if stashed is not None:
            try:
                report = _coerce_report(json.dumps(stashed), agent_name)
                outputs.append(_to_agent_output(report))
                continue
            except Exception:
                logger.warning("Could not coerce stashed report for %s", agent_name)
        outputs.append(output)
    return outputs


def _truncate(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


async def _emit_events(messages) -> None:
    task_calls = _index_task_calls(messages)
    for msg in messages:
        if isinstance(msg, AIMessage):
            if msg.content:
                await log_event("thinking", agent="orchestrator", content=_truncate(str(msg.content)))
            for tc in msg.tool_calls or []:
                await log_event(
                    "tool_call",
                    agent="orchestrator",
                    tool=tc.get("name"),
                    input_=tc.get("args"),
                )
        elif isinstance(msg, ToolMessage):
            agent = task_calls.get(msg.tool_call_id, "orchestrator")
            await log_event(
                "tool_result",
                agent=agent,
                tool=msg.name or "task",
                output=_truncate(str(msg.content)),
            )
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            await log_event("final", content=_truncate(str(msg.content)))
            break

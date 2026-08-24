"""Event emission and per-agent extraction (Task 3).

Functions that walk the message list to emit structured events and build
per-agent output lists from ToolMessages.
"""

import json
import logging

from langchain_core.messages import AIMessage, ToolMessage

from domain.entities.agent_finding import AgentOutput
from infrastructure.agents_runtime.capture import CaptureStore
from infrastructure.agents_runtime.orchestrator_parsing import (
    _coerce_report,
    _index_task_calls,
    _looks_like_json_obj,
    _parse_tool_message,
    _to_agent_output,
)
from infrastructure.agents_runtime.utils import truncate as _truncate
from infrastructure.event_bus.log_event_bus import log_event

logger = logging.getLogger(__name__)


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

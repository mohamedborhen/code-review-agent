"""Event bus: logs the Phase 2 event schema to stdout/file.

Schema (log-only this phase, no UI consumer yet)::

    { "type": "thinking",   "agent": "compliance",  "content": "..." }
    { "type": "tool_call",  "agent": "compliance",  "tool": "query_graph_tool", "input": {...} }
    { "type": "tool_result", "agent": "compliance", "tool": "query_graph_tool", "output": {...} }
    { "type": "final",      "content": "..." }

Every entry is one JSON line, written to stdout (via logging) and appended to
``logs/review_events.log``. File writes are offloaded with asyncio.to_thread so
the event loop is never blocked (Phase 2 is async throughout).
"""

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_LOG_PATH = Path("logs/review_events.log")


async def log_event(
    type_: str,
    *,
    agent: str | None = None,
    content: str | None = None,
    tool: str | None = None,
    input_: dict | None = None,
    output: object = None,
) -> None:
    entry: dict = {"type": type_}
    if agent is not None:
        entry["agent"] = agent
    if content is not None:
        entry["content"] = content
    if tool is not None:
        entry["tool"] = tool
    if input_ is not None:
        entry["input"] = input_
    if output is not None:
        entry["output"] = output

    line = json.dumps(entry, default=str)
    logger.info("EVENT %s", line)
    await asyncio.to_thread(_append_to_file, line)


def _append_to_file(line: str, path: Path = _DEFAULT_LOG_PATH) -> None:
    try:
        os.makedirs(path.parent, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:  # pragma: no cover - logging must never break a review
        logger.warning("Could not write review event log at %s: %s", path, exc)

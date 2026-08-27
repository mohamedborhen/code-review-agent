"""Shared utility functions for the agents_runtime package.

Consolidates _truncate, _findings_list, and _extract_text which were
previously duplicated across orchestrator_runtime.py, tool_scoping.py,
capture.py, report_parse.py, branch_resolution.py, and context_agent_runtime.py.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Patterns that look like secrets/tokens — redact before persisting.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ghp_[A-Za-z0-9]{36}"),          # GitHub PAT
    re.compile(r"github_pat_[A-Za-z0-9_]{82}"),   # GitHub fine-grained PAT
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"Basic\s+[A-Za-z0-9+/]+=*", re.IGNORECASE),
    re.compile(r"xoxb-[A-Za-z0-9\-]+"),           # Slack bot token
    re.compile(r"AKIA[0-9A-Z]{16}"),              # AWS access key
]

_REDACTED = "[REDACTED]"


def truncate(text: str, limit: int = 2000) -> str:
    """Truncate text to limit, appending '...(truncated)' if needed."""
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def sanitize_for_storage(text: str, limit: int = 2000) -> str:
    """Redact known secret patterns then truncate for safe DB storage."""
    redacted = text
    for pat in _SECRET_PATTERNS:
        redacted = pat.sub(_REDACTED, redacted)
    return truncate(redacted, limit)


def findings_list(raw: dict) -> list | None:
    """Locate the findings array under any of the shapes subagents emit.

    Subagents nest reports under domain keys (`security_review`,
    `compliance_report`, ...) and vary the array name (`findings`,
    `violations`, `security_findings`, ...). Recurse one level into nested
    dicts so a report like `{"security_review": {"findings": [...]}}` parses.
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
            nested = findings_list(value)
            if nested is not None:
                return nested
    return None


def extract_text(result: Any) -> str:
    """Pull the text payload out of a langchain tool result.

    The GitHub MCP tool returns `list[dict]` content items with a `text`
    key (and possibly `structuredContent`); `str` or plain objects are
    returned as-is.
    """
    if isinstance(result, str):
        return result
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                parts.append(item["text"])
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else json.dumps(content)
    return str(content or "")

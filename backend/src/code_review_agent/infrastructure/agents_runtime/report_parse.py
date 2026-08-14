"""Report-JSON detection helpers shared by the capture layer and the parser.

Why this module exists: ``capture.py`` (the middleware that sees every subagent
AIMessage) and ``orchestrator_runtime.py`` (the parser that persists per-agent
rows) both need to recognize a SubagentReport-shaped JSON blob, but importing
``orchestrator_runtime`` from ``capture`` would be circular. These helpers are
the shared, import-light answer — they depend on nothing but the stdlib.

The recovery flow they enable (see ``capture.py`` / ``_extract_per_agent``):
a weak model occasionally emits its real SubagentReport JSON in an earlier
message and then closes the subagent run with prose or an empty message, so the
final ``task`` ToolMessage (the only thing the parser sees) is not parseable.
``report_dict_from_text`` is the "is this a real report" sniff the middleware
uses to stash the last report per agent, so the parser can fall back to it.
"""

import json
import re

__all__ = ["extract_json_text", "report_dict_from_text"]

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_XML_RE = re.compile(
    r"<(?:subagent_report|report|result)\b[^>]*>(.*?)"
    r"</(?:subagent_report|report|result)>",
    re.DOTALL | re.IGNORECASE,
)


def extract_json_text(text: str) -> str:
    """Pull a JSON block out of a fenced/prose subagent reply.

    Subagents regularly wrap their JSON report in a markdown code fence
    (``**SubagentReport**\n\n```json ... `````) or an XML-style tag
    (``<subagent_report> ... </subagent_report>``), which makes ``json.loads``
    fail and silently empties their AgentExecution row. Strip the wrapper before
    parsing so the strict path still gets first crack at the real JSON.
    """
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    match = _XML_RE.search(text)
    return match.group(1).strip() if match else text


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


def report_dict_from_text(text: str) -> dict | None:
    """Return a report-shaped dict from raw text, or None.

    The dict is returned only when it actually carries a findings array, so an
    empty ``{}`` or prose text does not qualify — we only want to stash (and
    later recover) reports that contain real findings, never noise.
    """
    try:
        raw = json.loads(extract_json_text(text))
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    findings = _findings_list(raw)
    if not findings:
        return None
    return raw

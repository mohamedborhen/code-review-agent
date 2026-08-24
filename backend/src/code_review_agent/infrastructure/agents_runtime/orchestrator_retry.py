"""Retry logic extracted from orchestrator_runtime (Task 3).

Handles MCP transport failures, transient provider errors, and structured-
output parse failures with appropriate backoff strategies.
"""

import asyncio
import logging
import re

from infrastructure.agents_runtime.middleware import _is_transient_provider_error

logger = logging.getLogger(__name__)

_MCP_ERROR = re.compile(r"ExceptionGroup|MCP|mcp|streamable|connection|transport", re.IGNORECASE)
_STRUCTURED_OUTPUT_FAILURE = re.compile(r"structured output|json|parse", re.IGNORECASE)


def _is_mcp_error(exc: BaseException) -> bool:
    """Detect MCP transport/connection failures (D-12)."""
    return bool(_MCP_ERROR.search(str(exc)))


async def _run_with_retry(agent, user_message: str, config: dict | None = None, attempts: int = 3) -> dict:
    """Run the deep agent, retrying transient + structured-output + MCP failures."""
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
            mcp = _is_mcp_error(exc)
            if not (transient or structured or mcp):
                raise
            if attempt < attempts:
                if transient:
                    delay = 2.0 * (2 ** (attempt - 1)) + 0.5
                elif mcp:
                    delay = 1.0
                else:
                    delay = 0.5
                logger.warning(
                    "Retrying review run (attempt %s/%s) after %s: %s",
                    attempt,
                    attempts,
                    "transient provider error" if transient else "MCP transport error" if mcp else "structured-output failure",
                    exc,
                )
                await asyncio.sleep(delay)
    raise last  # type: ignore[misc]

"""Conversation FastMCP server (Phase 3) — exactly one tool: ``search_messages``.

Layer 5, run as its own process bound to ``127.0.0.1`` (PHASE_3.md §9.4;
default port from ``settings.conversation_mcp_url``). Registered as the 5th
streamable-HTTP server in the shared ``MultiServerMCPClient`` at FastAPI
startup — never a per-request client.

Safety contract (non-negotiable, PHASE_3.md §5 / §8):
- ``search_messages`` is the ONLY tool exposed. No ``execute_sql``-style tool.
- Read-only: it can only SELECT; no write-capable tool ever exists here.
- Authorization: identity (conversation_id/user_id/repo_id) is checked inside
  the tool; "not found" and "not yours" return the same response.
- FTS5 phrase-quoting protects hyphenated identifiers like ``CLIP-4`` from
  raising ``OperationalError``.
- ``score`` is ``-bm25()`` so higher = better match.
- SQLite is accessed via threadpool offloading (never blocks the event loop).

Run: ``python -m infrastructure.mcp_clients.servers.conversation_server``
"""

import json
import os
import sqlite3
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from mcp.server.fastmcp import FastMCP

from infrastructure.config import settings

MAX_SEARCH_RESULTS = 25
MAX_QUERY_LENGTH = 200

_DB_PATH = Path(settings.metadata_db_path)


def _port_from_url(url: str) -> int:
    from urllib.parse import urlparse

    return urlparse(url).port or 9001


# Bind host: 127.0.0.1 for local dev (PHASE_3.md §9.4); docker-compose sets
# CONVERSATION_SERVER_HOST=0.0.0.0 so the code-review-agent container can reach
# it over the compose network (mirrors mcp-atlassian's HOST env).
_BIND_HOST = os.environ.get("CONVERSATION_SERVER_HOST", "127.0.0.1")

mcp = FastMCP(
    "Conversation",
    host=_BIND_HOST,
    port=_port_from_url(settings.conversation_mcp_url),
    streamable_http_path="/mcp",
)


def _connect() -> sqlite3.Connection:
    """Fresh connection with Phase 1 concurrency pragmas (WAL + busy_timeout)."""
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _authorized(conversation_id: int, user_id: str, repo_id: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM Conversation WHERE id = ? AND user_id = ? AND repo_id = ?",
            (conversation_id, user_id, repo_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _search(
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    limit: int,
    exclude_message_id: int | None = None,
) -> dict:
    """Synchronous core: authorization + FTS5 query. Runs in a threadpool."""
    if not _authorized(conversation_id, user_id, repo_id):
        return {"conversation_id": conversation_id, "results": [], "error": "not_found"}

    clean_query = query.strip().replace('"', '""')
    fts_query = f'"{clean_query}"'
    clamped_limit = max(1, min(limit, MAX_SEARCH_RESULTS))

    conn = _connect()
    try:
        sql = """
            SELECT m.id, m.role, snippet(message_fts, 0, '[', ']', '...', 32) AS snippet,
                   m.created_at, -bm25(message_fts) AS score
            FROM message_fts f
            JOIN Message m ON f.rowid = m.id
            WHERE message_fts MATCH ? AND m.conversation_id = ?
        """
        params: list = [fts_query, conversation_id]
        if exclude_message_id is not None:
            sql += " AND m.id != ?"
            params.append(exclude_message_id)
        sql += " ORDER BY score DESC LIMIT ?"
        params.append(clamped_limit)
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return {"conversation_id": conversation_id, "results": [], "error": "invalid_query"}
    finally:
        conn.close()

    results = [
        {
            "message_id": row["id"],
            "role": row["role"],
            "snippet": row["snippet"],
            "created_at": row["created_at"],
            "score": row["score"],
        }
        for row in rows
    ]
    return {"conversation_id": conversation_id, "results": results}


@mcp.tool()
async def search_messages(
    conversation_id: int,
    user_id: str,
    repo_id: str,
    query: str,
    limit: int = 10,
    exclude_message_id: int | None = None,
) -> str:
    """Search the conversation's message history (read-only).

    Returns a JSON string:
    {
      "conversation_id": int,
      "results": [
        {"message_id": int, "role": str, "snippet": str, "created_at": str, "score": float}
      ]
    }
    `results` is sorted best-match-first. `score` is normalized so that
    HIGHER means a better match (negate SQLite's raw bm25(): `-bm25(message_fts) AS score`).
    `exclude_message_id` optionally excludes one message id from the results
    (used by the turn flow so a just-persisted user message never matches itself);
    None means no exclusion.

    Error responses:
    {"conversation_id": int, "results": [], "error": "not_found"}
      — conversation does not exist or user_id/repo_id authorization check fails.
    {"conversation_id": int, "results": [], "error": "invalid_query"}
      — query exceeds MAX_QUERY_LENGTH or causes an FTS5 syntax operational error.
    """
    if len(query.strip()) > MAX_QUERY_LENGTH:
        return json.dumps(
            {"conversation_id": conversation_id, "results": [], "error": "invalid_query"}
        )
    payload = await run_in_threadpool(
        _search, conversation_id, user_id, repo_id, query, limit, exclude_message_id
    )
    return json.dumps(payload)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

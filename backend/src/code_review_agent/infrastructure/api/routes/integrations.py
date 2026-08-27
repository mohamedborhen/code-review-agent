"""Per-user Jira credential vault — write-only, encrypted server-side.

Decision 4 final: no OAuth, per-user (jira_url, jira_email, jira_api_token)
stored encrypted, used as `Authorization: Basic base64(email:token)` per-request
to mcp-atlassian UserTokenMiddleware (servers/main.py:699-728 basic branch).
Global JIRA_* env remains only as dummy placeholder for _get_global_config guard.
ALLOW_GLOBAL_CRED_FALLBACK=false.
"""

import base64
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from infrastructure.db.credential_repository import CredentialRepository

logger = logging.getLogger(__name__)

router = APIRouter()


class JiraCredentialRequest(BaseModel):
    user_id: str
    repo_id: str  # which repo this Jira credential is for (or "*" for all)
    jira_url: str
    jira_email: str
    jira_api_token: str


class JiraValidateRequest(BaseModel):
    user_id: str
    jira_url: str
    jira_email: str
    jira_api_token: str


@router.post("/integrations/jira")
async def store_jira_credentials(body: JiraCredentialRequest) -> dict:
    if not body.user_id or not body.jira_url or not body.jira_email or not body.jira_api_token:
        raise HTTPException(status_code=400, detail="user_id, jira_url, jira_email, jira_api_token are required")
    if not body.jira_url.startswith("https://"):
        raise HTTPException(status_code=400, detail="jira_url must be https://*.atlassian.net")
    try:
        repo = CredentialRepository()
        repo.store(
            repo_id=body.repo_id,
            user_id=body.user_id,
            jira_url=body.jira_url,
            jira_email=body.jira_email,
            jira_api_token=body.jira_api_token,
        )
    except Exception as e:
        logger.error(f"Jira credential store failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to store credentials")
    # Never echo token
    return {"stored": True, "repo_id": body.repo_id}


@router.post("/integrations/jira/validate")
async def validate_jira_credentials(body: JiraValidateRequest) -> dict:
    """Probe Jira with supplied Basic credentials — does NOT store.

    Calls `GET {jira_url}/rest/api/2/myself` with Basic auth.
    Returns {ok: bool, account_id?: str, error?: str}. Never logs token.
    """
    import httpx

    if not all([body.jira_url, body.jira_email, body.jira_api_token]):
        raise HTTPException(status_code=400, detail="All fields required")

    token = base64.b64encode(f"{body.jira_email}:{body.jira_api_token}".encode()).decode()
    headers = {"Authorization": f"Basic {token}"}
    url = body.jira_url.rstrip("/") + "/rest/api/2/myself"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "account_id": data.get("accountId")}
            return {"ok": False, "error": f"Jira responded {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def build_jira_headers_for_user(user_id: str, repo_id: str) -> dict | None:
    """Build per-request headers for mcp-atlassian from vault.

    Called at review time to inject per-user Jira Basic auth and URL.
    Returns None if no Jira credentials stored for this repo/user.

    Returns dict with:
      - Authorization: Basic base64(email:token)
      - X-Atlassian-Jira-Url: user's Jira instance URL (if stored)

    The X-Atlassian-Jira-Url header is consumed by mcp-atlassian's
    UserTokenMiddleware and forwarded to _get_fetcher, which passes it
    to _create_user_config_for_fetcher via credentials["url"]. Our
    monkey-patch (mcp_jira_patch.py) ensures this URL overrides
    base_config.url.
    """
    try:
        creds = CredentialRepository().get_jira_credentials(repo_id)
        if not creds or not creds.get("jira_email") or not creds.get("jira_api_token"):
            return None
        token = base64.b64encode(
            f"{creds['jira_email']}:{creds['jira_api_token']}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {token}"}
        if creds.get("jira_url"):
            headers["X-Atlassian-Jira-Url"] = creds["jira_url"]
        return headers
    except Exception:
        return None

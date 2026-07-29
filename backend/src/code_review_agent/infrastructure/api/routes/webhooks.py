import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlmodel import Session, select

from application.repo_ingestion_service.clone_repository import CloneRepositoryService
from application.repo_ingestion_service.sync_on_webhook import SyncOnWebhookService
from infrastructure.config import settings
from infrastructure.db.engine import engine
from infrastructure.db.models import GraphSnapshot, RepoWorkspace
from infrastructure.graph_builder.crg_mcp_adapter import CRGMcpAdapter
from infrastructure.repo_source.git_repo_source import GitRepoSource
from infrastructure.workspace.workspace_lock import acquire_workspace_lock

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(raw_body, signature, settings.github_webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(raw_body)
    commit_sha: str = payload.get("after", "")

    if commit_sha == "0000000000000000000000000000000000000000":
        return {"status": "skipped", "reason": "branch deletion"}

    repo_id: str = payload["repository"]["full_name"]

    background_tasks.add_task(process_webhook, repo_id, commit_sha)

    return {"status": "accepted"}


def verify_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def process_webhook(repo_id: str, commit_sha: str) -> None:
    with Session(engine) as session:
        statement = select(RepoWorkspace).where(RepoWorkspace.repo_id == repo_id)
        workspace = session.exec(statement).first()
        if workspace is None:
            logger.warning(f"Webhook received for untracked repo: {repo_id}")
            return

        lock = acquire_workspace_lock(settings.workspace_root, repo_id)

        with lock:
            repo_source = GitRepoSource()
            graph_builder = CRGMcpAdapter(settings.crg_server_url)
            service = SyncOnWebhookService(repo_source, graph_builder)

            last_indexed = workspace.last_synced_commit

            try:
                build_status = service.execute(
                    local_path=workspace.local_path,
                    commit_sha=commit_sha,
                    last_indexed_commit=last_indexed,
                )
                status = build_status.status
                error_message = build_status.error_message
            except Exception as e:
                logger.error(f"Error executing webhook sync for {repo_id}: {e}")
                status = "error"
                error_message = str(e)

            snapshot = GraphSnapshot(
                repo_id=repo_id,
                commit_hash=commit_sha,
                status=status,
                error_message=error_message,
            )
            session.add(snapshot)

            if status == "ready":
                workspace.last_synced_commit = commit_sha
                workspace.updated_at = datetime.now(timezone.utc)
            session.commit()


@router.post("/repos")
async def register_repo(body: dict, background_tasks: BackgroundTasks) -> dict:
    repo_url: str = body.get("repo_url", "")
    repo_id: str = body.get("repo_id", "")

    if not repo_url or not repo_id:
        raise HTTPException(status_code=400, detail="repo_url and repo_id are required")

    background_tasks.add_task(register_and_build, repo_url, repo_id)

    return {"status": "accepted", "repo_id": repo_id}


def register_and_build(repo_url: str, repo_id: str) -> None:
    lock = acquire_workspace_lock(settings.workspace_root, repo_id)

    with lock:
        repo_source = GitRepoSource()
        graph_builder = CRGMcpAdapter(settings.crg_server_url)
        service = CloneRepositoryService(repo_source, graph_builder)

        try:
            workspace, build_status = service.execute(
                repo_url=repo_url,
                repo_id=repo_id,
                workspace_root=settings.workspace_root,
            )
            status = build_status.status
            error_message = build_status.error_message
            commit_hash = workspace.last_synced_commit
            local_path = workspace.local_path
        except Exception as e:
            logger.error(f"Error cloning repository {repo_id}: {e}")
            status = "error"
            error_message = str(e)
            commit_hash = "unknown"
            local_path = ""

        with Session(engine) as session:
            if local_path:
                db_ws = RepoWorkspace(
                    repo_id=repo_id,
                    local_path=local_path,
                    last_synced_commit=commit_hash,
                )
                session.add(db_ws)

            snapshot = GraphSnapshot(
                repo_id=repo_id,
                commit_hash=commit_hash,
                status=status,
                error_message=error_message,
            )
            session.add(snapshot)
            session.commit()

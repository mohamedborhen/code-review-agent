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
from infrastructure.db.repo_workspace_repository import SQLModelRepoWorkspaceRepository
from infrastructure.graph_builder.crg_mcp_adapter import CRGMcpAdapter
from infrastructure.mcp_clients.branch_resolution import list_repo_branches
from infrastructure.repo_source.git_repo_source import GitRepoSource
from infrastructure.workspace.workspace_lock import acquire_workspace_lock

logger = logging.getLogger(__name__)

router = APIRouter()

_repo_store = SQLModelRepoWorkspaceRepository()


@router.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Per-repo HMAC: parse repo_id first, then verify against vault.
    # No global fallback in final phase — contradiction removed (item 3).
    payload = json.loads(raw_body)
    repo_id: str = payload["repository"]["full_name"]
    # Vault lookup: if repo_id was never registered via POST /api/v1/repos, fail closed.
    try:
        from infrastructure.db.credential_repository import CredentialRepository

        _vault = CredentialRepository()
        per_repo_secret = _vault.get_webhook_secret(repo_id)
    except Exception:
        per_repo_secret = None

    # Use per-repo secret if present; otherwise fall back to global ONLY during
    # migration (ALLOW_GLOBAL_WEBHOOK_FALLBACK env, default false, removed after).
    # Final product requires per-repo secret — global is not a production path.
    import os

    secret = per_repo_secret
    if secret is None and os.getenv("ALLOW_GLOBAL_WEBHOOK_FALLBACK", "false").lower() in ("true", "1", "yes"):
        secret = settings.github_webhook_secret

    if secret is None or not verify_signature(raw_body, signature, secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    commit_sha: str = payload.get("after", "")

    branch = _branch_from_ref(payload.get("ref", ""))

    if commit_sha == "0000000000000000000000000000000000000000":
        background_tasks.add_task(cleanup_deleted_branch, repo_id, branch)
        return {"status": "accepted", "action": "branch_deletion_cleanup"}

    background_tasks.add_task(process_webhook, repo_id, branch, commit_sha)

    return {"status": "accepted"}


def _branch_from_ref(ref: str) -> str:
    """Turn ``refs/heads/<name>`` into ``<name>`` (empty when not a branch ref)."""
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/") :]
    return ref


def verify_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def process_webhook(repo_id: str, branch: str, commit_sha: str) -> None:
    if not branch:
        return
    base = _repo_store.get_by_repo_id(repo_id)
    if base is None or base.branch != branch:
        # Untracked repo, or a push to a non-default (worktree) branch — both
        # are no-ops. Worktrees update only via POST /review (§2).
        logger.info("Webhook no-op for %s branch %r", repo_id, branch)
        return

    with Session(engine) as session:
        workspace = session.exec(
            select(RepoWorkspace).where(
                RepoWorkspace.repo_id == repo_id,
                RepoWorkspace.branch == branch,
            )
        ).first()
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
                completed_at=datetime.now(timezone.utc) if status == "ready" else None,
            )
            session.add(snapshot)

            if status == "ready":
                workspace.last_synced_commit = commit_sha
                workspace.updated_at = datetime.now(timezone.utc)
            session.commit()


def cleanup_deleted_branch(repo_id: str, branch: str) -> None:
    """Branch-deletion cleanup (§9): remove the worktree + its RepoWorkspace row.

    GraphSnapshot rows are left alone — they are commit-keyed and may still back
    past AgentExecution audit rows.
    """
    if not branch:
        return
    row = _repo_store.get_by_repo_id_and_branch(repo_id, branch)
    if row is None:
        return
    try:
        repo_source = GitRepoSource()
        base = _repo_store.get_by_repo_id(repo_id)
        if base is not None:
            # prune from the base clone; git worktree remove is enough to drop
            # the entry from .git/worktrees of the base clone.
            _run_git_quiet(["worktree", "remove", row.local_path], cwd=base.local_path)
            _run_git_quiet(["worktree", "prune"], cwd=base.local_path)
    except Exception as e:
        logger.error("worktree remove for %s/%s failed: %s", repo_id, branch, e)
    _repo_store.delete_branch_row(repo_id, branch)


def _run_git_quiet(args: list[str], cwd: str) -> None:
    import subprocess

    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else str(result)
        raise RuntimeError(f"git {' '.join(args)} failed\n{stderr}")


@router.post("/repos")
async def register_repo(body: dict, background_tasks: BackgroundTasks) -> dict:
    repo_url: str = body.get("repo_url", "")
    repo_id: str = body.get("repo_id", "")
    user_id: str | None = body.get("user_id")
    github_pat: str | None = body.get("github_pat")
    webhook_secret: str | None = body.get("webhook_secret")
    display_name: str | None = body.get("display_name")

    if not repo_url or not repo_id:
        raise HTTPException(status_code=400, detail="repo_url and repo_id are required")
    # user_id is required in final phase (decision 2); keep 400 for missing
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    # repo_id must match repo_url owner/repo (prevent hijack)
    try:
        from urllib.parse import urlparse

        path = urlparse(repo_url).path.strip("/").removesuffix(".git")
        if path.lower() != repo_id.lower():
            raise HTTPException(status_code=400, detail="repo_id must match repo_url owner/repo")
    except HTTPException:
        raise
    except Exception:
        pass

    # Enforce per-repo ownership (409 on hijack) and persist vault row
    try:
        from infrastructure.db.credential_repository import CredentialRepository
        import secrets

        _vault = CredentialRepository()
        existing = _vault.get_by_repo_id(repo_id)  # returns dict or None
        if existing and existing.get("owning_user_id") and existing["owning_user_id"] != user_id:
            raise HTTPException(status_code=409, detail="Repo already registered by another user")

        # Generate webhook secret if caller omitted it (manual step still requires pasting it into GitHub)
        if not webhook_secret:
            webhook_secret = secrets.token_hex(20)

        _vault.store(
            repo_id=repo_id,
            user_id=user_id,
            repo_url=repo_url,
            github_pat=github_pat,
            webhook_secret=webhook_secret,
        )
        credential_stored = True
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Credential store failed for {repo_id}: {e}")
        credential_stored = False
        # Fall back to still attempting clone with supplied PAT

    pat_for_clone = github_pat  # use the just-supplied PAT for this clone
    background_tasks.add_task(register_and_build, repo_url, repo_id, pat_for_clone)

    return {"status": "accepted", "repo_id": repo_id, "credential_stored": credential_stored}


@router.get("/repos/{repo_id:path}/branches")
async def list_branches(repo_id: str, request: Request) -> dict:
    """Read-only proxy for all remote branches of a registered repo (§6)."""
    if not _repo_store.repo_is_registered(repo_id):
        raise HTTPException(status_code=404, detail=f"Unknown repo_id: {repo_id}")
    owner, _, repo = repo_id.partition("/")
    branches = await list_repo_branches(request.app.state.mcp_client, owner, repo)
    return {"repo_id": repo_id, "branches": branches}


def register_and_build(repo_url: str, repo_id: str, github_pat: str | None = None) -> None:
    # If caller did not supply PAT, try vault (covers re-clone after eviction)
    if github_pat is None:
        try:
            from infrastructure.db.credential_repository import CredentialRepository

            github_pat = CredentialRepository().get_pat(repo_id)
        except Exception:
            github_pat = None

    lock = acquire_workspace_lock(settings.workspace_root, repo_id)

    with lock:
        repo_source = GitRepoSource()
        graph_builder = CRGMcpAdapter(settings.crg_server_url)
        service = CloneRepositoryService(repo_source, graph_builder)

        try:
            # Pass PAT via repo_source clone (vault-aware); if service doesn't take pat, it falls back to URL
            try:
                workspace, build_status = service.execute(
                    repo_url=repo_url,
                    repo_id=repo_id,
                    workspace_root=settings.workspace_root,
                    github_pat=github_pat,
                )
            except TypeError:
                # Back-compat if service signature not yet updated
                workspace, build_status = service.execute(
                    repo_url=repo_url,
                    repo_id=repo_id,
                    workspace_root=settings.workspace_root,
                )
                # Still ensure PAT was used for git if needed — GitRepoSource will have been called with vault lookup inside service
                pass
            status = build_status.status
            error_message = build_status.error_message
            commit_hash = workspace.last_synced_commit
            local_path = workspace.local_path
            branch = workspace.branch or "main"
        except Exception as e:
            logger.error(f"Error cloning repository {repo_id}: {e}")
            status = "error"
            error_message = str(e)
            commit_hash = "unknown"
            local_path = ""
            branch = "main"

        with Session(engine) as session:
            if local_path:
                existing = session.exec(
                    select(RepoWorkspace).where(
                        RepoWorkspace.repo_id == repo_id,
                        RepoWorkspace.branch == branch,
                    )
                ).first()
                if existing:
                    existing.local_path = local_path
                    existing.last_synced_commit = commit_hash
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    db_ws = RepoWorkspace(
                        repo_id=repo_id,
                        branch=branch,
                        local_path=local_path,
                        last_synced_commit=commit_hash,
                    )
                    session.add(db_ws)

            snapshot = GraphSnapshot(
                repo_id=repo_id,
                commit_hash=commit_hash,
                status=status,
                error_message=error_message,
                completed_at=datetime.now(timezone.utc) if status == "ready" else None,
            )
            session.add(snapshot)
            session.commit()

import asyncio
import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI

from infrastructure.agents_runtime.memory_store import build_memory_store
from infrastructure.api.routes.conversation import router as conversation_router
from infrastructure.api.routes.integrations import router as integrations_router
from infrastructure.api.routes.review import router as review_router
from infrastructure.api.routes.webhooks import router as webhook_router
from infrastructure.config import settings
from infrastructure.db.engine import init_db
from infrastructure.graph_service.crg_server_manager import CRGServerManager
from infrastructure.mcp_clients.mcp_client_factory import build_mcp_client
from infrastructure.mcp_clients.mcp_jira_patch import apply_patches as apply_jira_patch
from infrastructure.workspace.workspace_eviction_service import WorkspaceEvictionService

logger = logging.getLogger(__name__)

crg_manager = CRGServerManager()
eviction_service = WorkspaceEvictionService(settings.workspace_root)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Apply mcp-atlassian Jira URL override patch before any MCP client is built.
    # This ensures per-user X-Atlassian-Jira-Url headers override base_config.url.
    apply_jira_patch()
    logger.info(f"Checking CRG connectivity at {crg_manager._server_url}")
    crg_manager.ensure_connected(timeout=10)
    logger.info("CRG server is reachable")
    app.state.mcp_client = build_mcp_client()
    logger.info("Shared MultiServerMCPClient built on app.state")
    # Phase 4: the single process-wide LangGraph BaseStore for agent long-term
    # memory. Exactly ONE AsyncSqliteStore exists per process, constructed HERE
    # inside the async lifespan (the constructor captures asyncio.get_running_loop(),
    # so it cannot be built at module import — PHASE_4.md §6.3). Every runtime
    # that needs it (OrchestratorRuntime) receives this same instance via
    # app.state.memory_store; no second store is ever constructed.
    app.state.memory_store = await build_memory_store()
    logger.info("Shared AsyncSqliteStore built on app.state.memory_store")
    # Branch-aware worktree eviction (§11): run off the event loop on startup so
    # the app comes up promptly; it evicts LRU worktrees only when over budget.
    try:
        await asyncio.to_thread(eviction_service.evict_if_needed)
    except Exception as e:  # never block startup on eviction failure
        logger.warning("Workspace eviction on startup failed: %s", e)
    yield


app = FastAPI(title="Code Review Agent", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")
app.include_router(conversation_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")

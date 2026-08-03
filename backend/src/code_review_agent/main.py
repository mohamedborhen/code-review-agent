import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI

from infrastructure.api.routes.review import router as review_router
from infrastructure.api.routes.webhooks import router as webhook_router
from infrastructure.db.engine import init_db
from infrastructure.graph_service.crg_server_manager import CRGServerManager
from infrastructure.mcp_clients.mcp_client_factory import build_mcp_client

logger = logging.getLogger(__name__)

crg_manager = CRGServerManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(f"Checking CRG connectivity at {crg_manager._server_url}")
    crg_manager.ensure_connected(timeout=10)
    logger.info("CRG server is reachable")
    app.state.mcp_client = build_mcp_client()
    logger.info("Shared MultiServerMCPClient built on app.state")
    yield


app = FastAPI(title="Code Review Agent", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI

from infrastructure.api.routes.webhooks import router as webhook_router
from infrastructure.db.engine import init_db
from infrastructure.graph_service.crg_server_manager import CRGServerManager

logger = logging.getLogger(__name__)

crg_manager = CRGServerManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(f"Checking CRG connectivity at {crg_manager._server_url}")
    crg_manager.ensure_connected(timeout=10)
    logger.info("CRG server is reachable")
    yield


app = FastAPI(title="Code Review Agent", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router, prefix="/api/v1")

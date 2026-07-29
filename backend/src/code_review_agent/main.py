from contextlib import asynccontextmanager

from fastapi import FastAPI

from infrastructure.api.routes.webhooks import router as webhook_router
from infrastructure.db.engine import init_db
from infrastructure.graph_service.crg_server_manager import CRGServerManager

crg_manager = CRGServerManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    crg_manager.start()
    yield
    crg_manager.stop()


app = FastAPI(title="Code Review Agent", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router, prefix="/api/v1")

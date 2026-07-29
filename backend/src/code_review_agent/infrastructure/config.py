import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

_APP_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    github_webhook_secret: str
    crg_server_url: str = "http://localhost:5555/mcp"
    workspace_root: str = "./data/workspaces"
    metadata_db_path: str = "./data/phase1_metadata.db"

    class Config:
        env_file = ".env"

    @model_validator(mode="after")
    def resolve_relative_paths(self) -> "Settings":
        if not os.path.isabs(self.workspace_root):
            self.workspace_root = str(_APP_ROOT / self.workspace_root)
        if not os.path.isabs(self.metadata_db_path):
            self.metadata_db_path = str(_APP_ROOT / self.metadata_db_path)
        return self


settings = Settings()

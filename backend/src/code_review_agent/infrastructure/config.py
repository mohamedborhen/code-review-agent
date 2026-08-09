import os
from pathlib import Path

from pydantic import ConfigDict, model_validator
from pydantic_settings import BaseSettings

_APP_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        # `.env` also carries keys owned by other processes, not our Settings:
        # LLM provider keys (read by init_chat_model from os.environ) and the
        # mcp-atlassian server vars (READ_ONLY_MODE / ALLOW_GLOBAL_CRED_FALLBACK /
        # TOOLSETS). pydantic-settings defaults extra to "forbid", which would
        # crash Settings() on every boot with those present — ignore them here.
        extra="ignore",
    )

    github_webhook_secret: str
    crg_server_url: str = "http://localhost:5555/mcp"
    workspace_root: str = "./data/workspaces"
    metadata_db_path: str = "./data/phase1_metadata.db"

    # --- Phase 2 additions ---
    # Required, no default — the LLM model spec for the whole multi-agent system,
    # sourced from env var REVIEW_MODEL in `provider:model` form (e.g.
    # "groq:llama-3.3-70b-versatile", "openrouter:anthropic/claude-sonnet-4-5",
    # "google_genai:gemini-2.5-pro", "openai:gpt-5.5", "anthropic:claude-sonnet-4-6").
    # deepagents resolves it via langchain's init_chat_model, which dispatches by
    # provider prefix — the provider's langchain integration package + API key env
    # var must be available. Never hardcode a model string in code; that relocates
    # staleness instead of removing it.
    review_model: str
    # Output-token budget per model call, forwarded to the provider as
    # `max_tokens`. No default cap exists in code; deepagents/openrouter resolve
    # "unset" to the model's full output window (16k for gpt-4o-mini), which the
    # OpenRouter free tier rejects ("...can only afford 15683"). Config-driven so
    # it is not a hardcoded value and can be raised when credits permit.
    review_max_tokens: int = 2000
    # Per-model-call timeout in seconds, forwarded to the provider as `timeout`.
    # Free-tier hosts (e.g. NVIDIA NIM) can exceed the previous hardcoded 240s on
    # a single long-reasoning turn, which surfaced as "Timeout on reading data
    # from socket" mid-review. Config-driven so it is not a hardcoded value.
    review_timeout: int = 600
    # Required, no default — used for the GitHub MCP server's Bearer auth header.
    github_pat: str
    # Optional — GitHub Copilot MCP's Context7 server sends the key as a header
    # only when one is configured.
    context7_api_key: str | None = None
    # mcp-atlassian MCP endpoint. Default is the local dev launch
    # (`uvx mcp-atlassian --transport streamable-http --port 9000`); docker-compose
    # overrides it to http://mcp-atlassian:9000/mcp — never hardcode 127.0.0.1
    # in the client factory for the same reason CRG's URL is a setting.
    atlassian_mcp_url: str = "http://127.0.0.1:9000/mcp"
    # mcp-atlassian auth (Cloud API tokens). These are handed to the mcp-atlassian
    # process as its own env vars (see run_atlassian_server.sh / docker-compose),
    # not sent as MultiServerMCPClient headers.
    jira_url: str | None = None
    jira_username: str | None = None
    jira_api_token: str | None = None
    confluence_url: str | None = None
    confluence_username: str | None = None
    confluence_api_token: str | None = None

    @model_validator(mode="after")
    def resolve_relative_paths(self) -> "Settings":
        if not os.path.isabs(self.workspace_root):
            self.workspace_root = str(_APP_ROOT / self.workspace_root)
        if not os.path.isabs(self.metadata_db_path):
            self.metadata_db_path = str(_APP_ROOT / self.metadata_db_path)
        return self


settings = Settings()

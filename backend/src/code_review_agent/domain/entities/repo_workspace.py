from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RepoWorkspace:
    repo_id: str
    branch: str
    local_path: str
    last_synced_commit: str | None = None
    last_requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

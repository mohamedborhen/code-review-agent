from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class GraphBuildStatus:
    commit_hash: str
    status: str
    error_message: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

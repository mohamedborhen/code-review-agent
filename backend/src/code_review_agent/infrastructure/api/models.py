"""Layer 2 API request/response shapes.

ReviewRequest lives here (not in domain/) because it is the HTTP boundary
contract — putting Pydantic models in domain/ would violate the zero-framework
rule the same way an `import fastapi` would.
"""

from pydantic import BaseModel


class ReviewRequest(BaseModel):
    repo_id: str
    graph_commit_hash: str | None = None  # optional — either this OR branch is required
    branch: str | None = None  # NEW — per-branch review; requires exactly one of branch/graph_commit_hash
    request_type: str  # must match a key in the Routing Policy
    diff_content: str | None = None  # optional — explain_question may not need one
    question: str | None = None  # optional — free-form question; steers any_question AND the single-specialist question types
    conversation_id: int | None = None  # optional — historical context AVAILABLE, never mandatory recall
    user_id: str | None = None  # required when conversation_id is set; authorized inside search_messages

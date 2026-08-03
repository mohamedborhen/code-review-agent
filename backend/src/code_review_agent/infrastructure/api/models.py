"""Layer 2 API request/response shapes.

ReviewRequest lives here (not in domain/) because it is the HTTP boundary
contract — putting Pydantic models in domain/ would violate the zero-framework
rule the same way an `import fastapi` would.
"""

from pydantic import BaseModel


class ReviewRequest(BaseModel):
    repo_id: str
    graph_commit_hash: str
    request_type: str  # must match a key in the Routing Policy
    diff_content: str | None = None  # optional — explain_question may not need one

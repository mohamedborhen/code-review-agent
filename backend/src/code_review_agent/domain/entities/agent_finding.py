from dataclasses import dataclass, field


@dataclass
class AgentInput:
    repo_id: str
    graph_commit_hash: str
    request_type: str
    diff_content: str | None = None
    repo_root: str = ""
    question: str | None = None
    conversation_id: int | None = None  # historical context AVAILABLE (never mandatory recall)
    user_id: str | None = None  # caller-supplied identity for search_messages authorization


@dataclass
class AgentFinding:
    severity: str
    confidence: float
    title: str
    description: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class AgentOutput:
    agent_name: str
    findings: list[AgentFinding] = field(default_factory=list)
    parse_status: str = "ok"  # "ok" | "parse_failed" | "empty_output" | "fallback_from_specialists"


@dataclass
class ReviewResult:
    """Outcome of one review run: the aggregated reply plus one output per
    routed subagent (the audit trail needs both)."""

    aggregated: AgentOutput
    per_agent: list[AgentOutput] = field(default_factory=list)

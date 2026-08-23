"""Pydantic schemas for deepagents structured outputs (Layer 5 only).

These mirror the domain AgentFinding/AgentOutput dataclasses but live in
infrastructure because Pydantic models are the deepagents `response_format`
mechanism, and domain/ must stay framework-free (zero pydantic imports).

The root agent and every subagent share this one schema: the orchestrator sets
``response_format=SubagentReport`` on create_deep_agent, and deepagents
propagates it to each subagent, so every subagent's ToolMessage content is the
JSON serialization of a SubagentReport.
"""

from pydantic import BaseModel, Field, model_validator


class FindingItem(BaseModel):
    severity: str = Field(description='"info" | "warning" | "critical"')
    confidence: float = Field(ge=0.0, le=1.0, description="0.0-1.0")
    title: str
    description: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str = ""

    @model_validator(mode="after")
    def _cap_confidence_on_empty_evidence(self) -> "FindingItem":
        """Downgrade high-confidence findings that have no evidence."""
        if not self.evidence and self.confidence > 0.5:
            self.confidence = min(self.confidence, 0.3)
            if not self.title.startswith("(unverified)"):
                self.title = f"(unverified) {self.title}"
        return self


class SubagentReport(BaseModel):
    agent_name: str
    findings: list[FindingItem] = Field(default_factory=list)

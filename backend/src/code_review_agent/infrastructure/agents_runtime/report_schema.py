"""Pydantic schemas for deepagents structured outputs (Layer 5 only).

These mirror the domain AgentFinding/AgentOutput dataclasses but live in
infrastructure because Pydantic models are the deepagents `response_format`
mechanism, and domain/ must stay framework-free (zero pydantic imports).

The root agent and every subagent share this one schema: the orchestrator sets
``response_format=SubagentReport`` on create_deep_agent, and deepagents
propagates it to each subagent, so every subagent's ToolMessage content is the
JSON serialization of a SubagentReport.
"""

from pydantic import BaseModel, Field


class FindingItem(BaseModel):
    severity: str = Field(description='"info" | "warning" | "critical"')
    confidence: float = Field(ge=0.0, le=1.0, description="0.0-1.0")
    title: str
    description: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str = ""


class SubagentReport(BaseModel):
    agent_name: str
    findings: list[FindingItem] = Field(default_factory=list)

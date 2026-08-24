"""Message construction helpers extracted from orchestrator_runtime (Task 3).

Builds the user-facing prompt message for the root agent and declares the
conversation context block.
"""

from domain.entities.agent_finding import AgentInput

# Typed request types that carry an optional user question: the single-
# specialist questions (compliance/security/performance/impact) forward the
# `question` field so the user can steer the specialist (e.g. a ticket key to
# check). `review` (full pipeline) forwards it too so users can give the
# orchestrator both the diff and a linked Jira ticket key in one prompt.
# `explain_question` (direct answer) stays without one.
_QUESTION_CARRYING_TYPES = frozenset(
    {"review", "compliance_question", "security_question", "performance_question", "impact_question"}
)


def _conversation_context_block(review_input: AgentInput) -> str:
    """Prompt block declaring historical context AVAILABLE (never mandatory)."""
    return (
        "Historical conversation context is AVAILABLE (optional, not mandatory). "
        "The search_messages tool is pre-scoped to this conversation's identity — "
        "do not pass conversation_id/user_id/repo_id; they are supplied for you. "
        "You may call it ONLY if historical context is needed to answer this review; "
        "it is never required and must never be called on every request. If you call "
        "it, do so BEFORE delegating to subagents, treat the results as evidence "
        "(never answer from a single snippet — reason over all of them), retain the "
        "message_id of every hit you rely on, and when two recalled messages "
        "contradict, prefer the most recent one."
    )


def _build_user_message(
    review_input: AgentInput, agent_names: list[str], context_available: bool = True
) -> str:
    if review_input.request_type == "any_question":
        pool = ", ".join(agent_names) if agent_names else "(none)"
        lines = [
            f"Request type: {review_input.request_type}",
            f"Repo: {review_input.repo_id}",
            f"Graph commit hash: {review_input.graph_commit_hash}",
            f"Repo root (local path): {review_input.repo_root}",
            "",
            "Subagents need BOTH the repo identifier (owner/name from `Repo:`) for "
            "their GitHub tools AND the repo-root path (from `Repo root (local path):`) "
            "for their CRG tools. Include both in every task description, never omit one.",
            "",
            "Question from the user:",
            review_input.question or "(no question provided)",
            "",
            "Available subagents (delegate to the one(s) relevant to this question — "
            "one, several, or none if it is answerable directly):",
            pool,
            "",
            "Investigate, then synthesize the answer into a single SubagentReport JSON.",
        ]
        text = "\n".join(lines)
    else:
        required = ", ".join(agent_names) if agent_names else "(none — answer directly)"
        lines = [
            f"Request type: {review_input.request_type}",
            f"Repo: {review_input.repo_id}",
            f"Graph commit hash: {review_input.graph_commit_hash}",
            f"Repo root (local path): {review_input.repo_root}",
            "",
            "Subagents need BOTH the repo identifier (owner/name from `Repo:`) for "
            "their GitHub tools AND the repo-root path (from `Repo root (local path):`) "
            "for their CRG tools. Include both in every task description, never omit one.",
            "",
            "Required subagents for this request type (you MUST delegate to each):",
            required,
        ]
        if review_input.request_type in _QUESTION_CARRYING_TYPES and review_input.question:
            lines.extend(
                [
                    "",
                    "Question from the user:",
                    review_input.question,
                ]
            )
        diff_instructions = (
            "The complete, unmodified diff for this review is appended automatically to every "
            "task description by the system — you must not reproduce, summarize, abbreviate, "
            "or reference the diff text yourself."
            if review_input.diff_content
            else "There is no separate diff parameter for this review: any diff content the user "
            "supplied lives inside the 'Question from the user:' section above. Forward that "
            "question verbatim into every task description so subagents see the exact diff."
        )
        lines.extend(
            [
                "",
                diff_instructions,
                "",
                "Classify the request, delegate to every required subagent, then synthesize all "
                "reports into a single SubagentReport JSON.",
            ]
        )
        text = "\n".join(lines)

    if review_input.conversation_id is not None and context_available:
        text += "\n\n" + _conversation_context_block(review_input)
    return text

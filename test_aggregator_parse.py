"""Regression: aggregator report arriving as plain final-message content.

Session 50: compliance found real issues (camelCase validatePDFPath, print()
debug, ticket-scope mismatch) but POST /review returned findings: [] because
deepagents returned the report as content instead of a native structured
response. _parse_aggregated must recover it via the lenient path.

Run:  $env:PYTHONPATH='backend\src\code_review_agent'; .venv\Scripts\python.exe test_aggregator_parse.py
"""

from langchain_core.messages import AIMessage

from infrastructure.agents_runtime.orchestrator_runtime import _parse_aggregated

SESSION_50_FINAL = r"""{
  "agent_name": "aggregator",
  "findings": [
    {
      "severity": "critical",
      "confidence": 0.95,
      "title": "Diff does not match Jira ticket CLIP-3 requirements",
      "description": "The diff shows no changes (empty diff), but ticket CLIP-3 requires adding a validate_pdf_path function in vector.py with snake_case naming, no print statements, and every function <=50 lines. The existing vector.py contains a validatePDFPath function (camelCase) with a print statement, violating the naming and debug print standards.",
      "evidence": [
        "vector.py: validatePDFPath function definition (camelCase)",
        "vector.py: print statement in validatePDFPath: 'print(f\"Validating PDF path: {pdf_path}\")'",
        "ticket CLIP-3 acceptance criteria: snake_case names, no print() debug statements"
      ],
      "recommendation": "Rename validatePDFPath to validate_pdf_path, remove the print statement, and ensure the function is called in build_retriever. Also, verify that app.py is not modified as per ticket scope."
    },
    {
      "severity": "info",
      "confidence": 0.9,
      "title": "Compliance Subagent Introduction",
      "description": "I am the compliance subagent, responsible for checking that code changes comply with ticket requirements and team standards.",
      "evidence": [],
      "recommendation": null
    }
  ]
}"""


def main() -> None:
    result = {
        "structured_response": None,
        "messages": [AIMessage(content=SESSION_50_FINAL)],
    }
    output = _parse_aggregated(result)
    assert output.agent_name == "aggregator", output.agent_name
    assert len(output.findings) == 2, [f.title for f in output.findings]
    titles = {f.title for f in output.findings}
    assert "Diff does not match Jira ticket CLIP-3 requirements" in titles
    assert "Compliance Subagent Introduction" in titles

    # structured_response present but empty dict -> must fall through to messages
    output2 = _parse_aggregated(
        {"structured_response": {}, "messages": [AIMessage(content=SESSION_50_FINAL)]}
    )
    assert len(output2.findings) == 2, [f.title for f in output2.findings]

    # prose lead-in before the JSON must not block the reversed scan
    output3 = _parse_aggregated(
        {
            "structured_response": None,
            "messages": [
                AIMessage(content="Summarizing..."),
                AIMessage(content=SESSION_50_FINAL),
            ],
        }
    )
    assert len(output3.findings) == 2, [f.title for f in output3.findings]

    print(
        f"OK: {len(output.findings)} findings recovered from final-message content "
        f"(empty-dict structured_response and prose-lead-in variants also pass)"
    )


if __name__ == "__main__":
    main()

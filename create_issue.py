import httpx, base64, re
d = {}
for l in open(r"backend\src\code_review_agent\.env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", l.strip())
    if m: d[m.group(1)] = m.group(2)
auth = base64.b64encode((d["JIRA_USERNAME"] + ":" + d["JIRA_API_TOKEN"]).encode()).decode()
h = {"Authorization": "Basic " + auth}

def para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}

body = {
    "fields": {
        "project": {"key": "CLIP"},
        "issuetype": {"id": "10042"},
        "summary": "Extract duplicated traffic-light grade computation in scoring router",
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                para("Scope: backend/routers/scoring.py only. Extract the traffic-light grade "
                     "computation (cnss_grade / op_grade) currently duplicated inside "
                     "predict_score and what_if_simulation into a shared helper "
                     "_compute_grades(cnss_ratio, op_avg) -> (cnss_grade, op_grade). "),
                para("Acceptance criteria:"),
                {"type": "bulletList", "content": [
                    {"type": "listItem", "content": [para("new helper _compute_grades added; both endpoints call it")]},
                    {"type": "listItem", "content": [para("identical behavior: thresholds stay cnss > 0.8, cnss >= 0.5, op_avg >= 8, op_avg >= 5")]},
                    {"type": "listItem", "content": [para("helper is snake_case and <= 20 lines")]},
                    {"type": "listItem", "content": [para("no changes to any other file")]},
                ]},
            ],
        },
    }
}
r = httpx.post(d["JIRA_URL"] + "/rest/api/3/issue", headers=h, json=body, timeout=30)
print(r.status_code)
print(r.text[:500])
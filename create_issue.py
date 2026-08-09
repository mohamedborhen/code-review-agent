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
        "summary": "Add PDF path validation to vector.py",
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                para("Scope: vector.py only. Add a validate_pdf_path() function that checks the path "
                     "exists and ends in .pdf before build_retriever loads it. Do not modify app.py."),
                para("Acceptance criteria:"),
                {"type": "bulletList", "content": [
                    {"type": "listItem", "content": [para("snake_case names")]},
                    {"type": "listItem", "content": [para("every function <= 50 lines")]},
                    {"type": "listItem", "content": [para("no print() debug statements in committed code")]},
                ]},
            ],
        },
    }
}
r = httpx.post(d["JIRA_URL"] + "/rest/api/3/issue", headers=h, json=body, timeout=30)
print(r.status_code)
print(r.text[:500])
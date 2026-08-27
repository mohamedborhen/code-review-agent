"""Tests for the shared utility functions in infrastructure.agents_runtime.utils."""

from infrastructure.agents_runtime.utils import extract_text, findings_list, sanitize_for_storage, truncate


class TestTruncate:
    def test_short_text_unchanged(self):
        assert truncate("hello", limit=10) == "hello"

    def test_exact_limit_unchanged(self):
        assert truncate("12345", limit=5) == "12345"

    def test_over_limit_truncated(self):
        assert truncate("123456789", limit=5) == "12345...(truncated)"

    def test_default_limit_2000(self):
        assert truncate("a" * 2001).endswith("...(truncated)")
        assert len(truncate("a" * 2001)) == 2000 + len("...(truncated)")

    def test_empty_string(self):
        assert truncate("") == ""


class TestFindingsList:
    def test_findings_key(self):
        assert findings_list({"findings": [1, 2]}) == [1, 2]

    def test_violations_key(self):
        assert findings_list({"violations": [3]}) == [3]

    def test_nested_findings(self):
        assert findings_list({"security_review": {"findings": [4]}}) == [4]

    def test_suffixed_key(self):
        assert findings_list({"security_findings": [5]}) == [5]

    def test_no_findings(self):
        assert findings_list({"other": "data"}) is None

    def test_empty_dict(self):
        assert findings_list({}) is None


class TestExtractText:
    def test_string_input(self):
        assert extract_text("hello") == "hello"

    def test_content_list_with_text_key(self):
        class FakeResult:
            content = [{"text": "line1"}, {"text": "line2"}]
        assert extract_text(FakeResult()) == "line1\nline2"

    def test_content_list_with_type_text(self):
        class FakeResult:
            content = [{"type": "text", "text": "hello"}]
        assert extract_text(FakeResult()) == "hello"

    def test_content_dict(self):
        class FakeResult:
            content = {"text": "hello"}
        assert extract_text(FakeResult()) == "hello"

    def test_content_dict_no_text(self):
        class FakeResult:
            content = {"key": "value"}
        result = extract_text(FakeResult())
        assert "key" in result

    def test_none_content(self):
        class FakeResult:
            content = None
        assert extract_text(FakeResult()) == ""


class TestSanitizeForStorage:
    def test_no_secrets_unchanged(self):
        text = "query_graph(query='find callers of foo')"
        assert sanitize_for_storage(text) == text

    def test_truncation_applied(self):
        text = "a" * 2500
        result = sanitize_for_storage(text, limit=100)
        assert len(result) == 100 + len("...(truncated)")
        assert result.endswith("...(truncated)")

    def test_github_pat_redacted(self):
        text = "token is ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        result = sanitize_for_storage(text)
        assert "ghp_" not in result
        assert "[REDACTED]" in result

    def test_github_fine_grained_pat_redacted(self):
        token = "github_pat_" + "A" * 82
        text = f"auth: {token}"
        result = sanitize_for_storage(text)
        assert token not in result
        assert "[REDACTED]" in result

    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret"
        result = sanitize_for_storage(text)
        assert "eyJhbGci" not in result
        assert "[REDACTED]" in result

    def test_basic_auth_redacted(self):
        text = "Authorization: Basic dXNlcjpwYXNz"
        result = sanitize_for_storage(text)
        assert "dXNlcjpwYXNz" not in result
        assert "[REDACTED]" in result

    def test_aws_key_redacted(self):
        text = "key=AKIAIOSFODNN7EXAMPLE"
        result = sanitize_for_storage(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED]" in result

    def test_empty_string(self):
        assert sanitize_for_storage("") == ""

    def test_redaction_before_truncation(self):
        long_secret = "ghp_" + "X" * 2500
        result = sanitize_for_storage(long_secret, limit=50)
        assert "ghp_" not in result
        assert "[REDACTED]" in result
        assert len(result) == 50 + len("...(truncated)")

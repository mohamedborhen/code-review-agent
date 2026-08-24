"""Tests for the shared utility functions in infrastructure.agents_runtime.utils."""

from infrastructure.agents_runtime.utils import extract_text, findings_list, truncate


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

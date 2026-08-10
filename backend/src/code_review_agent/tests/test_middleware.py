"""Unit tests for model-call middleware: transient retry, deterministic diff,
and timeline rendering."""

import asyncio
import unittest

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage

from infrastructure.agents_runtime.middleware import (
    DIFF_BEGIN,
    DIFF_END,
    DiffInjectionMiddleware,
    TransientRetryMiddleware,
    _is_transient_provider_error,
    render_timeline,
)

DIFF_TEXT = (
    "diff --git a/vector.py b/vector.py\n"
    "index 5017b37..290f057 100644\n"
    "--- a/vector.py\n"
    "+++ b/vector.py\n"
    "@@ -1,3 +1,5 @@\n"
    "+from mcp import os\n"
    " from langchain_ollama import OllamaEmbeddings\n"
)


class _FakeRequest:
    pass


class TransientProviderErrorTest(unittest.TestCase):
    def test_transient(self):
        for text in (
            "[429] Too Many Requests",
            "[503] ResourceExhausted: Worker local total request limit reached (37/32)",
            "[504] Unknown Error",
            "Timeout on reading data from socket",
            "Rate limit exceeded",
            "Connection reset by peer",
            "HTTP 502 Bad Gateway",
            "overloaded_error",
        ):
            with self.subTest(text=text):
                self.assertTrue(_is_transient_provider_error(RuntimeError(text)))

    def test_fatal(self):
        for text in (
            "[401] Unauthorized",
            "[403] Forbidden",
            "[404] Not Found",
            "[400] Bad Request",
            "some unrelated ValueError",
            "Invalid API key",
        ):
            with self.subTest(text=text):
                self.assertFalse(_is_transient_provider_error(RuntimeError(text)))


class TransientRetryMiddlewareTest(unittest.TestCase):
    def test_sync_retries_transient_then_succeeds(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("[429] Too Many Requests")
            return {"ok": True}

        mw = TransientRetryMiddleware(attempts=3, base_delay=0.0)
        result = mw.wrap_model_call(_FakeRequest(), handler)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls["n"], 3)

    def test_sync_no_retry_on_fatal(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            raise ValueError("boom")

        mw = TransientRetryMiddleware(attempts=3, base_delay=0.0)
        with self.assertRaises(ValueError):
            mw.wrap_model_call(_FakeRequest(), handler)
        self.assertEqual(calls["n"], 1)

    def test_async_retries_transient_then_succeeds(self):
        async def run():
            calls = {"n": 0}

            async def handler(request):
                calls["n"] += 1
                if calls["n"] < 2:
                    raise RuntimeError("[503] Service Unavailable")
                return {"ok": True}

            mw = TransientRetryMiddleware(attempts=3, base_delay=0.0)
            result = await mw.awrap_model_call(_FakeRequest(), handler)
            self.assertEqual(result, {"ok": True})
            self.assertEqual(calls["n"], 2)

        asyncio.run(run())


def _task_response(description: str) -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "subagent_type": "compliance",
                            "description": description,
                        },
                        "id": "call_1",
                    }
                ],
            )
        ]
    )


class DiffInjectionMiddlewareTest(unittest.TestCase):
    def test_appends_canonical_diff(self):
        mw = DiffInjectionMiddleware(DIFF_TEXT)
        out = mw.wrap_model_call(_FakeRequest(), lambda _: _task_response("Review the change. owner: x, repo: y"))
        desc = out.result[0].tool_calls[0]["args"]["description"]
        self.assertTrue(desc.endswith(f"{DIFF_BEGIN}\n{DIFF_TEXT}\n{DIFF_END}"), desc)
        self.assertIn(DIFF_TEXT, desc)

    def test_idempotent(self):
        mw = DiffInjectionMiddleware(DIFF_TEXT)
        once = mw.wrap_model_call(_FakeRequest(), lambda _: _task_response("Review."))
        twice = mw.wrap_model_call(_FakeRequest(), lambda _: once)
        self.assertEqual(
            once.result[0].tool_calls[0]["args"]["description"],
            twice.result[0].tool_calls[0]["args"]["description"],
        )

    def test_replaces_mangled_diff(self):
        mw = DiffInjectionMiddleware(DIFF_TEXT)
        mangled = "Review the change.\n\nDiff:\n+from mcp import os+\n ...corrupted..."
        out = mw.wrap_model_call(_FakeRequest(), lambda _: _task_response(mangled))
        desc = out.result[0].tool_calls[0]["args"]["description"]
        self.assertNotIn("corrupted", desc)
        self.assertIn(DIFF_TEXT, desc)
        self.assertNotIn("from mcp import os+", desc)

    def test_no_op_without_diff(self):
        mw = DiffInjectionMiddleware(None)
        out = mw.wrap_model_call(_FakeRequest(), lambda _: _task_response("Review."))
        self.assertEqual(out.result[0].tool_calls[0]["args"]["description"], "Review.")

    def test_does_not_touch_non_task_calls(self):
        mw = DiffInjectionMiddleware(DIFF_TEXT)
        response = ModelResponse(
            result=[AIMessage(content="", tool_calls=[{"name": "other_tool", "args": {"x": 1}, "id": "c2"}])]
        )
        out = mw.wrap_model_call(_FakeRequest(), lambda _: response)
        self.assertEqual(out.result[0].tool_calls[0]["args"], {"x": 1})


class RenderTimelineTest(unittest.TestCase):
    def test_shape(self):
        timeline = {
            "compliance": [
                {"kind": "llm", "name": "nvidia:nvidia/fake", "duration_ms": 1200},
                {"kind": "tool", "name": "get_review_context_tool", "duration_ms": 400},
                {"kind": "tool", "name": "jira_get_issue", "duration_ms": 800},
                {"kind": "llm", "name": "nvidia:nvidia/fake", "duration_ms": 2100},
            ],
            "orchestrator": [
                {"kind": "llm", "name": "nvidia:nvidia/fake", "duration_ms": 900},
                {"kind": "llm", "name": "nvidia:nvidia/fake", "duration_ms": 10200},
            ],
        }
        text = render_timeline(timeline)
        self.assertIn("compliance:", text)
        self.assertIn("LLM call #1 (nvidia:nvidia/fake): 1.2s", text)
        self.assertIn("get_review_context_tool: 0.4s", text)
        self.assertIn("jira_get_issue: 0.8s", text)
        self.assertIn("LLM call #2 (nvidia:nvidia/fake): 2.1s", text)
        self.assertIn("orchestrator:", text)
        self.assertIn("LLM call #1 (nvidia:nvidia/fake): 0.9s", text)
        self.assertIn("final synthesis (nvidia:nvidia/fake): 10.2s", text)


if __name__ == "__main__":
    unittest.main()

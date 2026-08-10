"""Unit tests for the CaptureStore timeline/model store and the subagent
per-LLM-call timing."""

import asyncio
import unittest

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage

from infrastructure.agents_runtime.capture import CaptureStore, SubagentCaptureMiddleware


class _FakeModel:
    model_id = "nvidia:nvidia/fake"


class _FakeRequest:
    model = _FakeModel()


class CaptureStoreTest(unittest.TestCase):
    def test_record_and_consume(self):
        store = CaptureStore()
        store.record_model("compliance", "nvidia:a")
        store.record_call("compliance", "llm", "nvidia:a", 100)
        store.record_call("compliance", "tool", "jira_get_issue", 50)

        self.assertEqual(store.consume_model("compliance"), "nvidia:a")
        self.assertIsNone(store.consume_model("missing"))

        timeline = store.consume_timeline()
        self.assertEqual(
            timeline["compliance"][0],
            {"kind": "llm", "name": "nvidia:a", "duration_ms": 100},
        )
        self.assertEqual(timeline["compliance"][1]["name"], "jira_get_issue")
        self.assertEqual(store.consume_timeline(), {})  # consumed once
        self.assertEqual(store.consume_duration("compliance"), 0)

    def test_first_model_wins(self):
        store = CaptureStore()
        store.record_model("compliance", "nvidia:a")
        store.record_model("compliance", "nvidia:b")
        self.assertEqual(store.consume_model("compliance"), "nvidia:a")


class SubagentCaptureMiddlewareTest(unittest.TestCase):
    def test_awrap_records_llm_call_and_model(self):
        async def run():
            store = CaptureStore()
            mw = SubagentCaptureMiddleware("compliance", store)

            async def handler(request):
                return ModelResponse(result=[AIMessage(content="thinking...")])

            await mw.awrap_model_call(_FakeRequest(), handler)

            self.assertEqual(store.consume_model("compliance"), "nvidia:nvidia/fake")
            timeline = store.consume_timeline()
            self.assertEqual(timeline["compliance"][0]["kind"], "llm")
            self.assertEqual(timeline["compliance"][0]["name"], "nvidia:nvidia/fake")
            self.assertGreaterEqual(timeline["compliance"][0]["duration_ms"], 0)

        asyncio.run(run())

    def test_sync_records_llm_call_and_model(self):
        store = CaptureStore()
        mw = SubagentCaptureMiddleware("security", store)

        def handler(request):
            return ModelResponse(result=[AIMessage(content="thinking...")])

        mw.wrap_model_call(_FakeRequest(), handler)

        self.assertEqual(store.consume_model("security"), "nvidia:nvidia/fake")
        timeline = store.consume_timeline()
        self.assertEqual(timeline["security"][0]["kind"], "llm")


if __name__ == "__main__":
    unittest.main()

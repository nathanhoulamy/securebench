import pytest

from securebench_agent.models import (
    OpenAICompatibleError,
    OpenAICompatibleToolConfig,
    OpenAICompatibleToolModel,
    ReplayToolModel,
)
from securebench_agent.tools import TOOL_SCHEMAS


def test_replay_tool_model_returns_openai_style_tool_call():
    model = ReplayToolModel([{"tool": "read_file", "arguments": {"path": "app.py"}}])

    message = model.complete([], TOOL_SCHEMAS)

    assert message["role"] == "assistant"
    assert message["tool_calls"][0]["function"]["name"] == "read_file"
    assert '"path": "app.py"' in message["tool_calls"][0]["function"]["arguments"]


def test_openai_compatible_tool_model_builds_chat_completion_tool_request(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen = {}

    def transport(url, headers, body, timeout):
        seen["url"] = url
        seen["headers"] = headers
        seen["body"] = body
        seen["timeout"] = timeout
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "finish", "arguments": "{}"},
                            }
                        ],
                    }
                }
            ]
        }

    model = OpenAICompatibleToolModel(
        OpenAICompatibleToolConfig(
            model="test-model",
            base_url="https://llm.example/v1/",
            timeout=9,
            temperature=0,
        ),
        transport=transport,
    )

    message = model.complete([{"role": "user", "content": "task"}], TOOL_SCHEMAS)

    assert message["tool_calls"][0]["function"]["name"] == "finish"
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["tools"] == TOOL_SCHEMAS
    assert seen["body"]["parallel_tool_calls"] is False
    assert seen["timeout"] == 9


def test_openai_compatible_tool_model_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = OpenAICompatibleToolModel(
        OpenAICompatibleToolConfig(model="test-model"),
        transport=lambda url, headers, body, timeout: {"choices": [{"message": {"role": "assistant"}}]},
    )

    with pytest.raises(OpenAICompatibleError, match="Missing API key environment variable"):
        model.complete([], TOOL_SCHEMAS)

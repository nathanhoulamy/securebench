import pytest

from securebench.candidates import (
    OpenAICompatibleChatClient,
    OpenAICompatibleChatConfig,
    OpenAICompatibleError,
    TextCompletionProducer,
)
from securebench.candidates.openai_compatible import _extract_message_text
from securebench.tasks import MultipleChoiceTask


def make_task():
    return MultipleChoiceTask(
        id="mmlu/math/test/7",
        benchmark_id="mmlu",
        task_type="multiple_choice",
        question="2 + 2?",
        choices=("1", "2", "4", "5"),
        answer=2,
    )


def test_openai_compatible_chat_client_builds_chat_completion_request(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen = {}

    def transport(url, headers, body, timeout):
        seen["url"] = url
        seen["headers"] = headers
        seen["body"] = body
        seen["timeout"] = timeout
        return {"choices": [{"message": {"content": "C"}}]}

    client = OpenAICompatibleChatClient(
        OpenAICompatibleChatConfig(
            model="test-model",
            base_url="https://llm.example/v1/",
            timeout=12,
            temperature=0,
        ),
        transport=transport,
    )

    answer = client.generate(make_task().agent_payload())

    assert answer == "C"
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["temperature"] == 0
    assert seen["body"]["messages"][0]["role"] == "system"
    assert '"question": "2 + 2?"' in seen["body"]["messages"][1]["content"]
    assert seen["timeout"] == 12


def test_openai_compatible_chat_client_allows_per_call_options(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen = {}

    def transport(url, headers, body, timeout):
        seen["body"] = body
        seen["timeout"] = timeout
        return {"choices": [{"message": {"content": "C"}}]}

    client = OpenAICompatibleChatClient(
        OpenAICompatibleChatConfig(model="default-model", timeout=12),
        transport=transport,
    )

    client.generate(
        make_task().agent_payload(),
        model="override-model",
        timeout=3,
        temperature=0.2,
        extra_body={"seed": 123},
    )

    assert seen["body"]["model"] == "override-model"
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["seed"] == 123
    assert seen["timeout"] == 3


def test_openai_compatible_chat_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = OpenAICompatibleChatClient(
        OpenAICompatibleChatConfig(model="test-model"),
        transport=lambda url, headers, body, timeout: {"choices": [{"message": {"content": "C"}}]},
    )

    with pytest.raises(OpenAICompatibleError, match="Missing API key environment variable"):
        client.generate(make_task().agent_payload())


def test_extract_message_text_accepts_content_part_lists():
    assert _extract_message_text(
        {"choices": [{"message": {"content": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]}}]}
    ) == "AB"


def test_text_completion_producer_can_use_openai_compatible_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    client = OpenAICompatibleChatClient(
        OpenAICompatibleChatConfig(model="test-model"),
        transport=lambda url, headers, body, timeout: {"choices": [{"message": {"content": "C"}}]},
    )

    artifact = TextCompletionProducer(client, name="openai-compatible").produce(make_task())

    assert artifact.text == "C"
    assert artifact.metadata["producer"] == "openai-compatible"

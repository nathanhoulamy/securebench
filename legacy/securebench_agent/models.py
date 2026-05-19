"""Model adapters for the minimal workspace agent."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union


class OpenAICompatibleError(RuntimeError):
    """Raised when an OpenAI-compatible endpoint request fails."""


ToolTransport = Callable[[str, dict[str, str], dict[str, Any], Optional[float]], dict[str, Any]]


class ReplayToolModel:
    """Deterministic tool-call model for tests and dry-run scripts."""

    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = list(actions)
        self.index = 0

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        if self.index >= len(self.actions):
            return {"role": "assistant", "content": "No replay actions remain."}

        action = self.actions[self.index]
        self.index += 1

        if "message" in action:
            message = action["message"]
            if not isinstance(message, dict):
                raise ValueError("Replay action 'message' must be an object")
            return {"role": "assistant", **message}

        tool_name = action.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("Replay action requires non-empty 'tool'")
        arguments = action.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("Replay action 'arguments' must be an object")

        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"replay-{self.index}",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments, sort_keys=True),
                    },
                }
            ],
        }


@dataclass(frozen=True)
class OpenAICompatibleToolConfig:
    """Configuration for an OpenAI-compatible Chat Completions tool model."""

    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout: Optional[float] = 60.0
    temperature: Optional[float] = 0.0
    extra_body: dict[str, Any] = field(default_factory=dict)


class OpenAICompatibleToolModel:
    """Chat Completions tool-calling adapter using urllib only."""

    def __init__(
        self,
        config: OpenAICompatibleToolConfig,
        *,
        transport: Optional[ToolTransport] = None,
    ) -> None:
        self.config = config
        self.transport = transport or _default_transport

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "tools": tools,
            "parallel_tool_calls": False,
            **self.config.extra_body,
        }
        if self.config.temperature is not None:
            body["temperature"] = self.config.temperature

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key()}",
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        response = self.transport(url, headers, body, self.config.timeout)
        return _extract_assistant_message(response)

    def _api_key(self) -> str:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise OpenAICompatibleError(f"Missing API key environment variable {self.config.api_key_env!r}")
        return api_key


def load_replay_actions(path: Union[str, os.PathLike[str]]) -> list[dict[str, Any]]:
    """Load replay actions from a JSON file."""
    with open(path) as file:
        loaded = json.load(file)
    if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
        raise ValueError("Replay file must contain a JSON array of objects")
    return loaded


def _extract_assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAICompatibleError("Chat completion response did not contain choices[0].message") from exc

    if not isinstance(message, dict):
        raise OpenAICompatibleError("Chat completion message must be an object")
    if message.get("role") != "assistant":
        message = {"role": "assistant", **message}
    return message


def _default_transport(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: Optional[float],
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise OpenAICompatibleError(f"Endpoint returned HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise OpenAICompatibleError(f"Endpoint request failed: {exc.reason}") from exc

    try:
        loaded = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise OpenAICompatibleError("Endpoint returned invalid JSON") from exc
    if not isinstance(loaded, dict):
        raise OpenAICompatibleError("Endpoint JSON response must be an object")
    return loaded

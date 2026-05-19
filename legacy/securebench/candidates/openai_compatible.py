"""OpenAI-compatible Chat Completions text generator."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


class OpenAICompatibleError(RuntimeError):
    """Raised when an OpenAI-compatible endpoint request fails."""


Transport = Callable[[str, dict[str, str], dict[str, Any], float | None], dict[str, Any]]


@dataclass(frozen=True)
class OpenAICompatibleChatConfig:
    """Configuration for an OpenAI-compatible Chat Completions endpoint."""

    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout: float | None = 60.0
    temperature: float | None = 0.0
    system_prompt: str = "Return only the answer for the benchmark task."
    extra_body: dict[str, Any] = field(default_factory=dict)


class OpenAICompatibleChatClient:
    """Generate text using an OpenAI-compatible Chat Completions endpoint."""

    def __init__(
        self,
        config: OpenAICompatibleChatConfig,
        *,
        transport: Transport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or _default_transport

    def generate(self, payload: dict[str, Any], **options: Any) -> str:
        body = self._request_body(payload, options)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key()}",
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        response = self.transport(url, headers, body, options.get("timeout", self.config.timeout))
        return _extract_message_text(response)

    def _request_body(self, payload: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        system_prompt = str(options.get("system_prompt", self.config.system_prompt))
        body: dict[str, Any] = {
            "model": options.get("model", self.config.model),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _payload_to_prompt(payload)},
            ],
            **self.config.extra_body,
        }

        temperature = options.get("temperature", self.config.temperature)
        if temperature is not None:
            body["temperature"] = temperature

        extra_body = options.get("extra_body")
        if extra_body:
            body.update(extra_body)

        return body

    def _api_key(self) -> str:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise OpenAICompatibleError(f"Missing API key environment variable {self.config.api_key_env!r}")
        return api_key


def _payload_to_prompt(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _extract_message_text(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAICompatibleError("Chat completion response did not contain choices[0].message.content") from exc

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    raise OpenAICompatibleError("Chat completion message content must be a string or content-part list")


def _default_transport(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float | None,
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

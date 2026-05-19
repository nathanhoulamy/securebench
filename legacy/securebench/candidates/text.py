"""Direct text candidate production for non-agentic workflows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from securebench.candidates.base import CandidateArtifact, CandidateProducer
from securebench.tasks import SecureBenchTask


class TextGenerator(Protocol):
    """Minimal protocol for direct prompt-to-text generation."""

    def generate(self, payload: dict[str, Any], **options: Any) -> str:
        """Return text for an agent-visible task payload."""


class TextCompletionProducer(CandidateProducer):
    """Call a direct text generator outside the sandbox."""

    def __init__(
        self,
        generator: TextGenerator | Callable[..., str],
        *,
        name: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.generator = generator
        self.name = name
        self.options = options or {}

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        payload = task.agent_payload()
        options = {**self.options, **context}
        if hasattr(self.generator, "generate"):
            text = self.generator.generate(payload, **options)
        else:
            text = self.generator(payload, **options)
        return CandidateArtifact(
            text=str(text),
            metadata={
                "producer": self.name or type(self.generator).__name__,
            },
        )

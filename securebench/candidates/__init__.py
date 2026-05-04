"""Candidate production interfaces and implementations."""

from securebench.candidates.base import CandidateArtifact, CandidateProducer
from securebench.candidates.openai_compatible import (
    OpenAICompatibleChatClient,
    OpenAICompatibleChatConfig,
    OpenAICompatibleError,
)
from securebench.candidates.static import StaticCandidateProducer
from securebench.candidates.text import TextCompletionProducer
from securebench.candidates.workspace import SandboxedCommandProducer, SandboxedPatchProducer, WorkspaceAgentPatchProducer

__all__ = [
    "CandidateArtifact",
    "CandidateProducer",
    "OpenAICompatibleChatClient",
    "OpenAICompatibleChatConfig",
    "OpenAICompatibleError",
    "SandboxedCommandProducer",
    "SandboxedPatchProducer",
    "StaticCandidateProducer",
    "TextCompletionProducer",
    "WorkspaceAgentPatchProducer",
]

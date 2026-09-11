"""Candidate-producing harnesses for tester YAML runs."""

from securebench.harnesses.claude_code import ClaudeCodeHarnessProducer, ClaudeCodeOverlay
from securebench.harnesses.codex import CodexHarnessProducer, CodexOverlay, DockerPlatform
from securebench.harnesses.command import CommandHarnessProducer
from securebench.harnesses.opencode import OpenCodeHarnessProducer, OpenCodeOverlay
from securebench.harnesses.registry import build_harness_producer

__all__ = [
    "ClaudeCodeHarnessProducer",
    "ClaudeCodeOverlay",
    "CodexHarnessProducer",
    "CodexOverlay",
    "CommandHarnessProducer",
    "DockerPlatform",
    "OpenCodeHarnessProducer",
    "OpenCodeOverlay",
    "build_harness_producer",
]

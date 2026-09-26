"""Agent profile of a campaign: which agent and model run, and where results go.

    CAMPAIGN_PROFILE=sonnet5 python -m tools.native_baseline.campaign run --rep 1

``luna`` (the default) is the 2026-09-24/25 Codex campaign and keeps its paths.
Every other profile writes under ``runs/campaign-<profile>/`` and shares the
native venv, upstream checkouts and admitted task lists in ``runs/campaign/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "runs" / "campaign"


@dataclass(frozen=True)
class Profile:
    name: str
    agent: str  # "codex" | "claude_code"
    model: str
    effort: str
    version: str
    native_model: str  # Harbor/Pier -m
    native_agents: str  # module holding the Pier*/Harbor* capture agents
    pier_agent: str
    harbor_agent: str
    native_log: str  # agent stdout file in the trial's agent/ dir
    credential_env: str  # the secret key_scan looks for
    # Env the native agents set themselves; SecureBench gets it through harness.env.
    agent_env: dict[str, str] = field(default_factory=dict)
    # USD per token, or None when the run is billed to a subscription.
    price: dict[str, float] | None = None

    @property
    def root(self) -> Path:
        return SHARED if self.name == "luna" else ROOT / "runs" / f"campaign-{self.name}"


PROFILES = {
    "luna": Profile(
        name="luna", agent="codex", model="gpt-6-luna", effort="max", version="0.156.1",
        native_model="openai/gpt-6-luna",
        native_agents="tools.native_baseline.codex_agents",
        pier_agent="PierCodexCapture", harbor_agent="HarborCodexCapture",
        native_log="codex.txt", credential_env="OPENAI_API_KEY",
        # litellm model_cost for gpt-6-luna (USD per token); see FREEZE.md.
        price={"input": 1e-07, "cached_input": 1e-08, "output": 5e-07},
    ),
    "sonnet5": Profile(
        name="sonnet5", agent="claude_code", model="claude-sonnet-5", effort="medium",
        version="2.1.283",
        native_model="anthropic/claude-sonnet-5",
        native_agents="tools.native_baseline.claude_agents",
        pier_agent="PierClaudeCodeCapture", harbor_agent="HarborClaudeCodeCapture",
        native_log="claude-code.txt", credential_env="CLAUDE_CODE_OAUTH_TOKEN",
        agent_env={"FORCE_AUTO_BACKGROUND_TASKS": "1", "ENABLE_BACKGROUND_TASKS": "1"},
    ),
}


def current() -> Profile:
    name = os.environ.get("CAMPAIGN_PROFILE", "luna")
    if name not in PROFILES:
        raise SystemExit(f"CAMPAIGN_PROFILE must be one of: {', '.join(PROFILES)}")
    return PROFILES[name]


PROFILE = current()

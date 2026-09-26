"""Write <campaign>/FREEZE.md: everything needed to reproduce the campaign.

    python -m tools.native_baseline.freeze

Never includes secrets: configs reference ``.env`` by path only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from tools.native_baseline.campaign import PRICE
from tools.native_baseline.campaign_configs import AGENT_VERSION, CONFIGS, MODEL, REASONING_EFFORT
from tools.native_baseline.profile import PROFILE, SHARED

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = PROFILE.root


def sh(*command: str, cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return (completed.stdout or completed.stderr).strip()


def image_rows() -> list[dict]:
    rows = []
    with (CONFIGS / "resources.csv").open() as handle:
        resources = {r["task"]: r for r in csv.DictReader(handle)}
    upstream_digest = {}
    digests = SHARED / "phase0" / "image-digests.tsv"
    for line in digests.read_text().splitlines():
        task, _, resolved = line.split("\t")
        upstream_digest[task] = resolved
    for task, r in resources.items():
        sb = r["securebench_image"]
        local = sh("docker", "image", "inspect", sb, "--format", "{{.Id}}")
        rows.append({"pack": r["pack"], "task": task, "securebench_image": sb,
                     "securebench_local_id": local, "upstream_image": r["upstream_image"],
                     "upstream_tag_digest_at_freeze": upstream_digest.get(task, "")})
    return rows


def agent_lines(native_bin: Path) -> list[str]:
    if PROFILE.agent == "codex":
        return [
            f"- Codex CLI `@openai/codex@{AGENT_VERSION}` (both conditions; pinned, not `latest`)",
            f"- Model `{MODEL}`, reasoning effort `{REASONING_EFFORT}` (both conditions)",
            "- Model id accepted by the API: `GET /v1/models/gpt-6-luna` returned 200 on 2026-09-24.",
            f"- Cost is computed from Codex-reported token usage with litellm's `{MODEL}` prices "
            f"(USD/token): input {PRICE['input']}, cached input {PRICE['cached_input']}, output {PRICE['output']} "
            f"(litellm `{sh(str(native_bin / 'python'), '-c', 'import importlib.metadata as m; print(m.version(\"litellm\"))')}`).",
        ]
    return [
        f"- Claude Code `@anthropic-ai/claude-code@{AGENT_VERSION}` (both conditions; pinned, not `latest`)",
        f"- Model `{MODEL}`, effort `{REASONING_EFFORT}` (both conditions)",
        "- Auth: Claude subscription OAuth token (`CLAUDE_CODE_OAUTH_TOKEN` from `.env`). Native passes it",
        "  into the agent container (upstream behaviour); SecureBench keeps it in the host-side relay.",
        "- Cost: none billed; `cost_usd` is Claude Code's own API-price estimate (`total_cost_usd`).",
        f"- Both conditions set {', '.join(f'`{k}={v}`' for k, v in PROFILE.agent_env.items())} "
        "(upstream agents set them; SecureBench via `harness.env`).",
        "- Upstream image digests are from the Luna campaign's phase 0 (2026-09-24).",
    ]


def main() -> int:
    head = sh("git", "rev-parse", "HEAD")
    dirty = sh("git", "status", "--porcelain=v1")
    mem_kb = int(next(l for l in Path("/proc/meminfo").read_text().splitlines()
                      if l.startswith("MemTotal")).split()[1])
    cpu = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines()
                if l.startswith("model name")), platform.processor())
    native_bin = SHARED / "native-venv" / "bin"
    lines = [
        "# Campaign freeze",
        "",
        f"Written {datetime.now(timezone.utc).isoformat(timespec='seconds')}.",
        "",
        "## Code",
        "",
        f"- SecureBench git SHA: `{head}` (branch `{sh('git', 'branch', '--show-current')}`)",
        "- Working tree at freeze (uncommitted paths; the campaign uses only committed rows,",
        "  see ISSUES.md I-01, plus the campaign tooling under `tools/native_baseline/`):",
        "",
        "```",
        dirty,
        "```",
        "",
        "## Agent",
        "",
        *agent_lines(native_bin),
        "",
        "## Native harnesses (condition A)",
        "",
        f"- Harbor `{sh(str(native_bin / 'python'), '-c', 'import importlib.metadata as m; print(m.version(\"harbor\"))')}` "
        "(Terminal-Bench 2.0), Pier "
        f"`{sh(str(native_bin / 'python'), '-c', 'import importlib.metadata as m; print(m.version(\"datacurve-pier\"))')}` (DeepSWE)",
        f"- Terminal-Bench 2.0: `harbor-framework/terminal-bench-2` at `{sh('git', 'rev-parse', 'HEAD', cwd=SHARED / 'upstream' / 'tb2')}`",
        f"- DeepSWE: `datacurve-ai/deep-swe` at `{sh('git', 'rev-parse', 'HEAD', cwd=SHARED / 'upstream' / 'deep-swe')}`",
        "",
        "## Host",
        "",
        f"- Docker: `{sh('docker', 'version', '--format', 'client {{.Client.Version}} / server {{.Server.Version}}')}`",
        f"- CPU: {cpu}, {sh('nproc')} logical CPUs",
        f"- RAM: {mem_kb / 1024 / 1024:.1f} GiB",
        f"- OS: {sh('sh', '-c', '. /etc/os-release; echo $PRETTY_NAME')}, kernel {platform.release()}",
        f"- Python (SecureBench venv): {sh(str(ROOT / '.venv' / 'bin' / 'python'), '--version')}",
        "",
        "## Images",
        "",
        "`securebench_image` is the digest SecureBench pins. `upstream_tag_digest_at_freeze` is what",
        "the upstream tag resolved to at freeze. They differ only for the 7 locally rebuilt TB images",
        "(ISSUES.md I-06).",
        "",
        "| pack | task | securebench_image | upstream_image | upstream tag digest at freeze |",
        "|---|---|---|---|---|",
    ]
    for r in image_rows():
        lines.append(f"| {r['pack']} | {r['task']} | `{r['securebench_image']}` | `{r['upstream_image']}` | "
                     f"`{r['upstream_tag_digest_at_freeze']}` |")
    lines += ["", "## Per-task limits", "",
              "From `configs/resources.csv` (upstream task.toml vs the SecureBench config):", "",
              "```csv", (CONFIGS / "resources.csv").read_text().strip(), "```", "",
              "## Campaign configs (SecureBench, condition B)", "",
              "Generated by `python -m tools.native_baseline.campaign_configs`; one config and one-row",
              "task file per task. Full text follows.", ""]
    for config in sorted(CONFIGS.glob("securebench/*/*/config.yaml")):
        digest = hashlib.sha256(config.read_bytes()).hexdigest()
        lines += [f"### {config.relative_to(CAMPAIGN)} (sha256 `{digest[:16]}`)", "", "```yaml",
                  config.read_text().strip(), "```", ""]
    lines += ["## Native commands (condition A)", "",
              "Built by `tools/native_baseline/campaign.py:native_command`; example:", "", "```"]
    from tools.native_baseline.campaign import native_command
    for task in ("deep-swe/cattrs-partial-structuring-recovery", "terminal-bench/chess-best-move"):
        lines.append(" ".join(native_command(task, Path("<run dir>"))).replace(str(ROOT) + "/", ""))
    lines += ["```", ""]
    (CAMPAIGN / "FREEZE.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {CAMPAIGN / 'FREEZE.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

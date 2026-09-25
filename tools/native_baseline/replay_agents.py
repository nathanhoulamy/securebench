"""Fixed-candidate replay agents for the upstream harnesses (Phase 1 and 5).

These play the role of Pier's/Harbor's ``oracle`` agent, but install a given
candidate instead of the upstream solution, so the *upstream* verifier grades
exactly the bytes SecureBench grades.

* ``PierPatchReplayAgent`` (DeepSWE): uploads a patch and installs it the way
  upstream ``solution/solve.sh`` installs the reference: ``git apply``, branch,
  ``git add -A``, commit. An empty patch replays the base state.
* ``HarborBundleReplayAgent`` (Terminal-Bench): uploads a tar of candidate files
  (guest-absolute paths, symlinks preserved) and extracts it at ``/``.

Pass the candidate with ``--ak candidate=<host path>``. Run with
``--agent-import-path tools.native_baseline.replay_agents:<Class>`` from the
repo root (so ``tools`` is importable).
"""

from __future__ import annotations

import shlex
from pathlib import Path

from harbor.agents.base import BaseAgent as HarborBaseAgent
from pier.agents.base import BaseAgent as PierBaseAgent

PATCH_TARGET = "/tmp/campaign-candidate.patch"
BUNDLE_TARGET = "/tmp/campaign-candidate.tar"

INSTALL_PATCH = f"""\
set -u
cd /app
if [ -s {PATCH_TARGET} ]; then
  git apply --whitespace=nowarn {PATCH_TARGET} || {{ echo "campaign-replay: git apply failed"; exit 3; }}
fi
git checkout -b feature/solution 2>/dev/null || true
git add -A
git -c user.name="oracle" -c user.email="oracle@local" commit -q --no-verify -m "Apply candidate" || true
"""

INSTALL_BUNDLE = f"tar --no-same-owner -xpf {BUNDLE_TARGET} -C / && rm -f {BUNDLE_TARGET}"


def _write_log(logs_dir: Path, name: str, result) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / name).write_text(
        f"return_code={result.return_code}\n--- stdout\n{result.stdout or ''}\n"
        f"--- stderr\n{result.stderr or ''}\n",
        encoding="utf-8",
    )


class PierPatchReplayAgent(PierBaseAgent):
    def __init__(self, logs_dir: Path, *args, candidate: str | None = None, **kwargs):
        super().__init__(logs_dir, *args, **kwargs)
        if not candidate:
            raise ValueError("PierPatchReplayAgent requires --ak candidate=<patch path>")
        self._candidate = Path(candidate)

    @staticmethod
    def name() -> str:
        return "campaign-patch-replay"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment) -> None:
        return

    async def run(self, instruction, environment, context) -> None:
        await environment.upload_file(self._candidate, PATCH_TARGET)
        result = await environment.exec(command=INSTALL_PATCH)
        _write_log(self.logs_dir, "replay.txt", result)
        if result.return_code != 0:
            raise RuntimeError(f"candidate install failed (exit {result.return_code})")


class HarborBundleReplayAgent(HarborBaseAgent):
    def __init__(self, logs_dir: Path, *args, candidate: str | None = None, clear: str | None = None, **kwargs):
        super().__init__(logs_dir, *args, **kwargs)
        if not candidate:
            raise ValueError("HarborBundleReplayAgent requires --ak candidate=<tar path>")
        self._candidate = Path(candidate)
        # Declared candidate paths: removed first so the candidate *replaces* them
        # (a directory tree must not be merged into the base state).
        self._clear = [p for p in (clear or "").split(",") if p.startswith("/")]

    @staticmethod
    def name() -> str:
        return "campaign-bundle-replay"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment) -> None:
        return

    async def run(self, instruction, environment, context) -> None:
        await environment.upload_file(self._candidate, BUNDLE_TARGET)
        clear = " ".join(shlex.quote(p) for p in self._clear)
        command = (f"rm -rf -- {clear} && " if clear else "") + INSTALL_BUNDLE
        result = await environment.exec(command=command)
        _write_log(self.logs_dir, "replay.txt", result)
        if result.return_code != 0:
            raise RuntimeError(f"candidate install failed (exit {result.return_code})")

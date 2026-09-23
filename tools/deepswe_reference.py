"""Install a DeepSWE row's upstream solution as host-only qualification material.

For each task this copies the pinned upstream ``solution/solution.patch`` to
``benchmarks/deep-swe/v2/hidden/<task>/qualification/reference.patch`` and
records its provenance, following the convention established by the
``go-critic-doc-link-checker`` conversion:

* ``reference.patch`` is byte-identical to the upstream solution;
* ``provenance.json`` binds it to the source revision, path, digest, and base
  commit, and states that it is qualification material, never a grading Oracle
  or a runtime resource;
* ``LICENSE.deepswe`` is the DeepSWE dataset licence, and
  ``LICENSE.<upstream>`` is the upstream project's licence taken from the
  repository at the base commit inside the pinned image, since the patch is a
  derivative of that project.

The qualification directory is never referenced from a row, so it is never
mounted into the Agent or Evaluation environment.

Usage::

    python -m tools.deepswe_reference --source /path/to/deep-swe cattrs-partial-structuring-recovery
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HIDDEN = ROOT / "benchmarks" / "deep-swe" / "v2" / "hidden"
EXPECTED_REVISION = "e016041a6ccf8da29906afc9a3f5a8df940a1f78"
LICENSE_CANDIDATES = (
    "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING",
    "LICENSE-APACHE", "LICENSE-MIT", "LICENSE-APACHE2", "UNLICENSE",
    "license", "license.md", "License", "License.txt",
)


def _source_revision(source: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _upstream_licenses(image: str, workdir: str) -> list[tuple[str, str]]:
    """Read every upstream licence file from the repo inside the image.

    Dual-licensed projects (for example ``LICENSE-APACHE`` plus ``LICENSE-MIT``)
    ship several files, and all of them apply, so none is dropped.
    """
    found = []
    for name in LICENSE_CANDIDATES:
        completed = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat",
             image, f"{workdir}/{name}"],
            capture_output=True, text=True,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            found.append((name, completed.stdout))
    return found


def install(source: Path, task: str, *, image: str | None, workdir: str) -> Path:
    task_root = source / "tasks" / task
    solution = task_root / "solution" / "solution.patch"
    if not solution.is_file():
        raise SystemExit(f"{task}: no upstream solution at {solution}")

    meta = tomllib.loads((task_root / "task.toml").read_text(encoding="utf-8"))
    metadata = meta.get("metadata", {})
    base_commit = metadata.get("base_commit_hash")
    repository = metadata.get("repository_url", "")
    upstream = repository.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "upstream"

    destination = HIDDEN / task / "qualification"
    destination.mkdir(parents=True, exist_ok=True)
    data = solution.read_bytes()
    (destination / "reference.patch").write_bytes(data)

    provenance = {
        "source_revision": _source_revision(source),
        "source_path": f"tasks/{task}/solution/solution.patch",
        "sha256": hashlib.sha256(data).hexdigest(),
        "purpose": (
            "Host-only qualification candidate; never a grading oracle or "
            "runtime resource."
        ),
        "baseline_commit": base_commit,
        "upstream_repository": repository,
    }
    (destination / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )

    dataset_license = source / "LICENSE"
    if dataset_license.is_file():
        (destination / "LICENSE.deepswe").write_bytes(dataset_license.read_bytes())

    if image is not None:
        found = _upstream_licenses(image, workdir)
        if not found:
            print(f"{task}: WARNING no upstream licence found in {workdir}", file=sys.stderr)
        elif len(found) == 1:
            (destination / f"LICENSE.{upstream}").write_text(found[0][1], encoding="utf-8")
        else:
            for name, text in found:
                suffix = name.removeprefix("LICENSE").lstrip("-.").lower() or "main"
                (destination / f"LICENSE.{upstream}-{suffix}").write_text(text, encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--image", help="pinned image to read the upstream licence from")
    parser.add_argument("--workdir", default="/app")
    parser.add_argument("tasks", nargs="+")
    arguments = parser.parse_args()

    revision = _source_revision(arguments.source)
    if revision != EXPECTED_REVISION:
        raise SystemExit(
            f"source is at {revision}, expected pinned revision {EXPECTED_REVISION}"
        )
    for task in arguments.tasks:
        path = install(arguments.source, task, image=arguments.image, workdir=arguments.workdir)
        print(f"{task}: installed {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

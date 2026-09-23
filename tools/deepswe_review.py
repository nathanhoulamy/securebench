"""Static review of a DeepSWE conversion before it is integrated.

Complements the Docker qualification rather than replacing it. Qualification
proves the gold solution passes and mutants fail; it cannot by itself prove the
adapter is assertion-free, because an adapter that quietly embeds expected
values can still pass every gate. This check looks for that directly.

It flags:

* verdict-shaped tokens in the adapter (``passed``, ``verdict``, ``score``,
  ``expected``) — an adapter reports observations, it never judges them;
* any sufficiently distinctive string literal that appears both in the adapter
  and in the host-only Oracle directory — the signature of expected data that
  leaked from the Oracle into a component the candidate can read;
* ``from __future__ import annotations`` in Python adapters (playbook defect #4);
* ``/tmp`` used as a build or execution directory (playbook defect #1).

A finding is a prompt for human review, not an automatic rejection: a literal
can legitimately appear in both places (a protocol name, a field name).

Usage::

    python -m tools.deepswe_review termenv-preserve-ansi-resets
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "benchmarks" / "deep-swe" / "v2"
VERDICT_TOKENS = re.compile(r"\b(passed|verdict|score|expected|pass_fail)\b", re.I)
# Only build/execute locations matter: scratch *data* in /tmp is fine.
EXEC_IN_TMP = re.compile(
    r"(CARGO_TARGET_DIR|GOTMPDIR|GOCACHE|GOBIN)[\"']?\s*[:=,]\s*[\"']/tmp"
)
# Identifiers and module or file paths are shared with the Oracle by design
# (protocol field names, import paths). Data-like literals are what leak.
NOT_DATA = re.compile(r"^[A-Za-z_][\w]*$|^[\w.\-]+(/[\w.\-]+)+$|^[\w]+(\.[\w]+)+$")
MIN_LITERAL = 8


def _literals(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    found: set[str] = set()
    if path.suffix == ".py":
        try:
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    found.add(node.value)
        except SyntaxError:
            pass
    else:
        found.update(re.findall(r'"((?:[^"\\\n]|\\.){%d,})"' % MIN_LITERAL, text))
        found.update(re.findall(r"'((?:[^'\\\n]|\\.){%d,})'" % MIN_LITERAL, text))
    return {
        item for item in found
        if len(item.strip()) >= MIN_LITERAL and not NOT_DATA.match(item.strip())
    }


def _postponed_with_local_classes(text: str) -> bool:
    """True only for a real future import in a module that nests classes."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    postponed = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )
    if not postponed:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(isinstance(child, ast.ClassDef) for child in ast.walk(node)):
                return True
    return False


def _files(directory: Path) -> list[Path]:
    return [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]


def review(name: str) -> list[str]:
    adapter_dir = V2 / "evaluation_inputs" / name / "adapter"
    oracle_dir = V2 / "hidden" / name / "oracle"
    findings: list[str] = []
    if not adapter_dir.is_dir():
        return [f"no adapter directory at {adapter_dir.relative_to(ROOT)}"]

    adapter_files = _files(adapter_dir)
    for path in adapter_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT)
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*", '"""')):
                continue
            if VERDICT_TOKENS.search(line):
                findings.append(f"{rel}:{number}: verdict-shaped token: {stripped[:100]}")
        if path.suffix == ".py" and _postponed_with_local_classes(text):
            findings.append(
                f"{rel}: postponed annotations with locally defined classes "
                "(playbook defect #4)"
            )
        for match in EXEC_IN_TMP.finditer(text):
            findings.append(f"{rel}: possible build/exec in noexec /tmp: {match.group(0)[:80]}")

    if oracle_dir.is_dir():
        oracle_literals: set[str] = set()
        for path in _files(oracle_dir):
            if path.suffix in {".py", ".json", ".yaml", ".txt", ".go", ".ts", ".rs"}:
                oracle_literals |= _literals(path)
        for path in adapter_files:
            shared = _literals(path) & oracle_literals
            for literal in sorted(shared)[:20]:
                findings.append(
                    f"{path.relative_to(ROOT)}: literal also in host Oracle: {literal[:80]!r}"
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="+")
    arguments = parser.parse_args()
    status = 0
    for name in arguments.tasks:
        findings = review(name)
        print(f"== {name}: {len(findings)} finding(s)")
        for finding in findings:
            print(f"   {finding}")
        status = status or bool(findings)
    return status


if __name__ == "__main__":
    raise SystemExit(main())

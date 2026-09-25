"""gpt2-codegolf candidate builder (declared candidate: /app/gpt2.c).

Native compiles gpt2.c and runs it on ONE hardcoded prompt, checking a single
expected substring is in stdout. SecureBench's Oracle feeds TWO prompts (the
public one plus a hidden second) and requires both continuations.

  base  : compiles, prints nothing -> both fail
  forge : ignores the model; prints the one known continuation substring ->
          native passes (only the public prompt is tested); SecureBench fails
          the hidden second case.
No genuine reference (a working <5000-byte GPT-2) is authored.
"""
from __future__ import annotations

from pathlib import Path

ROW = "terminal-bench/gpt2-codegolf"
CANDIDATES = ["base", "forge"]

BASE = r"""#include <stdio.h>
int main(int argc, char** argv) { return 0; }
"""

# Native checks: "WARRANTY OF ANY KIND, EXPRESS OR IMPLIED" in stdout for the
# public prompt. Print a continuation containing that substring, ignoring input.
FORGE = r"""#include <stdio.h>
int main(int argc, char** argv) {
    printf(" WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY\n");
    return 0;
}
"""


def build(name: str, ws: Path):
    contents = {"base": BASE, "forge": FORGE}
    (ws / "gpt2.c").write_text(contents[name])
    if name == "base":
        return False, "compiles but prints nothing", "-"
    return False, "ignores the model; prints the one known continuation substring", "G1/G4 (single public case; hidden case defeats it)"

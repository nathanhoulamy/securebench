#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("usage: produce_candidate.py TASK_JSON OUTPUT_PATCH")

task = json.loads(Path(sys.argv[1]).read_text())
base_commit = task["base_commit"]
matches = [path for path in Path("solutions").glob("*.patch") if base_commit in path.read_text()]
if len(matches) != 1:
    matches = list(Path("solutions").glob("*.patch"))
if len(matches) != 1:
    raise SystemExit(f"expected one smoke candidate patch, found {len(matches)}")
source = matches[0]
shutil.copyfile(source, sys.argv[2])

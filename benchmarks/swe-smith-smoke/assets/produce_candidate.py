#!/usr/bin/env python3
from __future__ import annotations
import shutil, sys
from pathlib import Path
matches = list(Path('solutions').glob('*.patch'))
if len(matches) != 1:
    raise SystemExit(f'expected one patch, found {len(matches)}')
shutil.copyfile(matches[0], sys.argv[2])

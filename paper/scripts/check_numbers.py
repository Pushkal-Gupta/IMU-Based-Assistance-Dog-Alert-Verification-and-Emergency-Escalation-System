#!/usr/bin/env python3
"""Fail if the manuscript cites an undefined number or types a generated one.

Two checks over paper/main.tex and paper/sections/*.tex:

1. every ``\\R{key}`` is defined in generated/numbers.json;
2. no bare decimal literal in the prose equals a generated value -- a typed
   result is one that will silently go stale when the experiments are re-run.
   Literals that are inputs rather than results (window lengths, timings,
   literature figures) are listed in ALLOWED.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parents[1]

#: Decimal literals that legitimately appear in the prose: design inputs,
#: literature values, and axis/grid settings -- not results of this work.
ALLOWED = {
    "0.25", "0.30", "0.50", "0.5", "0.95", "1.5", "2.5", "2.6", "1.3", "2.1", "3.6", "1.6", "3.1",
    "0.91", "2.1", "0.2", "1.92", "0.20", "79.4", "78.7", "51.2", "2.4", "0.01", "0.1", "1.0",
}


def main() -> int:
    numbers = json.loads((PAPER / "generated" / "numbers.json").read_text())
    sources = [PAPER / "main.tex", *sorted((PAPER / "sections").glob("*.tex"))]
    missing, typed = [], []
    generated_values = {v for v in numbers.values() if re.fullmatch(r"\d+\.\d+", v)}
    for path in sources:
        text = re.sub(r"(?m)(?<!\\)%.*$", "", path.read_text())
        for key in re.findall(r"\\R\{([^}]+)\}", text):
            if key not in numbers:
                missing.append(f"{path.name}: \\R{{{key}}}")
        prose = re.sub(r"\\R\{[^}]+\}", "", text)
        for lit in re.findall(r"(?<![\w.{])(\d+\.\d+)(?![\w.])", prose):
            if lit in generated_values and lit not in ALLOWED:
                typed.append(f"{path.name}: bare literal {lit} equals a generated value")
    for line in missing + typed:
        print(line)
    if missing or typed:
        print(f"{len(missing)} undefined, {len(typed)} typed results", file=sys.stderr)
        return 1
    print(f"ok: every number in {len(sources)} files is generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

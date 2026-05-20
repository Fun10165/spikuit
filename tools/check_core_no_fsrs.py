#!/usr/bin/env python3
"""Fail the build if spikuit-core reaches for the FSRS library.

Stage 2 (``docs/design/tutor-extraction-stage2.md`` §3, §7) retired the
learner model from the substrate: FSRS card state and scheduling now
live wholly in ``spikuit-tutor``. ``spikuit-core/src/**`` must therefore
contain **zero** ``import fsrs`` / ``from fsrs import …`` — this script
is the machine-checkable statement of "the substrate has no learner
model" (design §3 requirement 2).

Sibling of ``check_app_imports.py``; dependency-free on purpose — runs
on a bare Python with nothing installed.
"""

from __future__ import annotations

import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / "spikuit-core" / "src"


def _is_fsrs(name: str) -> bool:
    """Whether a dotted module name is the ``fsrs`` package or a submodule."""
    return name == "fsrs" or name.startswith("fsrs.")


def main() -> int:
    if not SRC.is_dir():
        print(f"check_core_no_fsrs: source tree not found: {SRC}", file=sys.stderr)
        return 1

    bad: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if _is_fsrs(node.module or ""):
                    bad.append(f"{path}:{node.lineno}: from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_fsrs(alias.name):
                        bad.append(f"{path}:{node.lineno}: import {alias.name}")

    if bad:
        print("Substrate learner-model leak — spikuit-core/src must not import")
        print("the FSRS library (Stage 2 §3: the substrate has no learner model).")
        print("FSRS scheduling belongs to spikuit-tutor.\n")
        print("\n".join(bad))
        return 1

    print("Substrate FSRS-free OK — spikuit-core/src contains no `import fsrs`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

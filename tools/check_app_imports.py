#!/usr/bin/env python3
"""Fail the build if spikuit-tutor reaches past the appkit contract.

Application packages may import from spikuit-core only through the
curated facade ``spikuit_core.appkit`` (see
``docs/design/tutor-extraction-stage1.md`` §4.1 / §6). Any other
``spikuit_core`` import in ``spikuit-tutor/src`` is a contract breach
and must fail CI.

Dependency-free on purpose — runs on a bare Python with nothing
installed. If a linter is adopted later this folds into ruff
(``flake8-tidy-imports`` banned-api), but the AST script states the
one allowed prefix explicitly and needs no new dependency.
"""

from __future__ import annotations

import ast
import pathlib
import sys

# The only spikuit_core spelling permitted inside spikuit-tutor/src.
ALLOWED = {"spikuit_core.appkit"}
SRC = pathlib.Path(__file__).resolve().parent.parent / "spikuit-tutor" / "src"


def main() -> int:
    if not SRC.is_dir():
        print(f"check_app_imports: source tree not found: {SRC}", file=sys.stderr)
        return 1

    bad: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("spikuit_core") and mod not in ALLOWED:
                    bad.append(f"{path}:{node.lineno}: from {mod} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith("spikuit_core") and name not in ALLOWED:
                        bad.append(f"{path}:{node.lineno}: import {name}")

    if bad:
        allowed = ", ".join(sorted(ALLOWED))
        print(f"App import boundary violated — spikuit-tutor/src may import")
        print(f"spikuit_core only via: {allowed}\n")
        print("\n".join(bad))
        return 1

    print("App import boundary OK — spikuit-tutor/src imports spikuit_core")
    print("only through spikuit_core.appkit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

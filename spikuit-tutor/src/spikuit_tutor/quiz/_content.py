"""Shared helpers for pulling title/body out of neuron markdown."""

from __future__ import annotations


def extract_title(content: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def extract_body(content: str) -> str:
    text = content
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()

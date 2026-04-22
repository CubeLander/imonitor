from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG_FILES = ("hprofile.yaml", "hprofile.yml")


def _load_example_config() -> str:
    default_template = Path(__file__).resolve().parent / "profile.default.yaml"
    try:
        return default_template.read_text(encoding="utf-8")
    except OSError:
        # Keep help usable even if the template file is unavailable in unusual packaging contexts.
        return (
            "# hprofile runtime config (yaml-like)\n"
            "# template file missing: analyzer/hprofile/profile.default.yaml\n"
        )


EXAMPLE_CONFIG = _load_example_config()


def find_default_config(cwd: Path) -> Path | None:
    for name in DEFAULT_CONFIG_FILES:
        p = cwd / name
        if p.exists() and p.is_file():
            return p.resolve()
    return None


def _strip_inline_comment(s: str) -> str:
    # Minimal comment stripping that respects simple quotes.
    in_single = False
    in_double = False
    out = []
    for ch in s:
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            continue
        if ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return ""

    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]

    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in {"null", "none"}:
        return None

    try:
        if any(ch in s for ch in (".", "e", "E")):
            return float(s)
        return int(s)
    except ValueError:
        return s


def _parse_yaml_like(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: list[tuple[int, Dict[str, Any]]] = [(-1, root)]

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_inline_comment(raw)
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        if "\t" in raw:
            raise ValueError(f"tabs are not supported in yaml-like config (line {lineno})")

        stripped = line.strip()
        if ":" not in stripped:
            raise ValueError(f"invalid line {lineno}: expected 'key: value' or 'key:'")

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        key, remainder = stripped.split(":", 1)
        key = key.strip()
        remainder = remainder.strip()
        if not key:
            raise ValueError(f"empty key at line {lineno}")

        if not remainder:
            child: Dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child))
            continue

        current[key] = _parse_scalar(remainder)

    return root


def load_config(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if stripped.startswith("{"):
        data = json.loads(stripped)
        if not isinstance(data, dict):
            raise ValueError("config JSON root must be an object")
        return data
    return _parse_yaml_like(text)

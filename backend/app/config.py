from __future__ import annotations
"""Paths, settings and Claude CLI discovery."""
import glob
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
PROJECTS = DATA / "projects"
PROJECTS.mkdir(exist_ok=True)
CACHE = DATA / "cache"
CACHE.mkdir(exist_ok=True)
CLI_CWD = DATA / "cli_cwd"  # neutral cwd so the CLI doesn't pick up project CLAUDE.md files
CLI_CWD.mkdir(exist_ok=True)


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()

DEFAULT_SETTINGS = {
    # Opus for anything that judges accuracy, Sonnet for mechanical/structural work.
    "models": {"rules": "sonnet", "structure": "sonnet", "scan": "opus", "judge": "opus", "spelling": "sonnet"},
    "claude_bin": "",
    "figma_token": "",
    "port": 8765,
}


def settings() -> dict:
    p = DATA / "settings.json"
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if p.exists():
        try:
            saved = json.loads(p.read_text())
            s["models"].update(saved.pop("models", {}))
            s.update(saved)
        except Exception:
            pass
    return s


def save_settings(new: dict):
    cur = settings()
    if "models" in new:
        cur["models"].update(new["models"])
    for k in ("claude_bin", "figma_token"):
        if k in new:
            cur[k] = new[k]
    (DATA / "settings.json").write_text(json.dumps(cur, indent=2))


def figma_token() -> str:
    return settings().get("figma_token") or os.environ.get("FIGMA_TOKEN", "")


def claude_bin() -> str | None:
    cands = [settings().get("claude_bin"), os.environ.get("CLAUDE_BIN"), shutil.which("claude")]
    cands += sorted(
        glob.glob(os.path.expanduser("~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude")),
        key=lambda p: [int(x) if x.isdigit() else 0 for x in p.split("claude-code-")[1].split("-")[0].split(".")],
        reverse=True,
    )
    cands += [os.path.expanduser("~/.claude/local/claude"), os.path.expanduser("~/.local/bin/claude")]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None

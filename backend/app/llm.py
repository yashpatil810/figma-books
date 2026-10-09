"""LLM provider: shells out to the Claude Code CLI so the user's Max plan is used (no API key).

Every call is cached on disk by hash of (model, system, prompt), so re-scans and re-verifies of
unchanged content cost nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading

from . import config

_sem = threading.Semaphore(3)


class LLMError(RuntimeError):
    pass


def status() -> dict:
    b = config.claude_bin()
    if not b:
        return {"ok": False, "bin": None, "error": "Claude CLI not found. Install Claude Code or set its path in Settings."}
    try:
        r = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=20)
        return {"ok": r.returncode == 0, "bin": b, "version": r.stdout.strip()}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "bin": b, "error": str(e)}


def _call(prompt: str, model: str, system: str | None, timeout: int) -> str:
    b = config.claude_bin()
    if not b:
        raise LLMError("Claude CLI not found")
    cmd = [b, "-p", "--model", model, "--output-format", "json", "--tools", "", "--no-session-persistence"]
    if system:
        cmd += ["--system-prompt", system]
    with _sem:
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=str(config.CLI_CWD))
        except subprocess.TimeoutExpired:
            raise LLMError(f"Claude CLI timed out after {timeout}s")
    out = r.stdout.strip()
    if r.returncode != 0 and not out:
        raise LLMError(f"Claude CLI failed: {r.stderr.strip()[:500]}")
    try:
        obj = json.loads(out)
    except json.JSONDecodeError:
        return out
    if obj.get("is_error"):
        raise LLMError(f"Claude CLI error: {str(obj.get('result'))[:500]}")
    return obj.get("result") or ""


def ask(prompt: str, model: str = "sonnet", system: str | None = None, timeout: int = 900, cache: bool = True) -> str:
    key = hashlib.sha256(json.dumps([model, system, prompt]).encode()).hexdigest()
    f = config.CACHE / f"{key}.txt"
    if cache and f.exists():
        return f.read_text()
    text = _call(prompt, model, system, timeout)
    if cache and text:
        f.write_text(text)
    return text


def extract_json(text: str):
    """Pull the first balanced JSON object/array out of a model reply (handles ``` fences)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    firsts = sorted((t.find(o), o, c) for o, c in (("{", "}"), ("[", "]")) if t.find(o) >= 0)
    for i, opener, closer in firsts:
        depth, instr, esc = 0, False, False
        for j in range(i, len(t)):
            c = t[j]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
                continue
            if c == '"':
                instr = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(t[i : j + 1])
    raise ValueError("no JSON found in reply")


JSON_ONLY = "Reply with valid JSON and nothing else: no prose, no markdown fences. When a list is requested reply with a JSON array holding every item, never just one."


def ask_json(prompt: str, model: str = "sonnet", system: str | None = None, timeout: int = 900):
    sys_ = (system + "\n\n" if system else "") + JSON_ONLY
    for attempt in range(2):
        text = ask(prompt + ("\n\nYour previous reply was not valid JSON. " + JSON_ONLY if attempt else ""), model, sys_, timeout, cache=(attempt == 0))
        try:
            return extract_json(text)
        except Exception:
            if attempt:
                raise LLMError("Model did not return valid JSON: " + text[:300])


def as_list(x):
    """Models sometimes return a single object (or {"items": [...]}) where a list was asked for."""
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in ("items", "results", "findings", "differences"):
            if isinstance(x.get(k), list):
                return x[k]
        return [x]
    return []


def ask_vision(prompt: str, files: dict, model: str = "sonnet", system: str | None = None, timeout: int = 1200, cache: bool = True) -> str:
    """Ask Claude about local images. files = {name: Path}. The CLI reads them with its Read tool, in a scratch dir."""
    import shutil
    import uuid
    from pathlib import Path

    keyparts = [model, system, prompt] + [f"{n}:{hashlib.sha1(Path(p).read_bytes()).hexdigest()}" for n, p in sorted(files.items())]
    key = hashlib.sha256(json.dumps(keyparts).encode()).hexdigest()
    f = config.CACHE / f"{key}.txt"
    if cache and f.exists():
        return f.read_text()
    b = config.claude_bin()
    if not b:
        raise LLMError("Claude CLI not found")
    work = config.CLI_CWD / ("v" + uuid.uuid4().hex[:8])
    work.mkdir(parents=True, exist_ok=True)
    try:
        for n, p in files.items():
            shutil.copy(p, work / n)
        cmd = [b, "-p", "--model", model, "--output-format", "json", "--tools", "Read", "--allowed-tools", "Read", "--no-session-persistence"]
        if system:
            cmd += ["--system-prompt", system]
        with _sem:
            try:
                r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=str(work))
            except subprocess.TimeoutExpired:
                raise LLMError(f"Claude CLI timed out after {timeout}s")
        out = r.stdout.strip()
        if r.returncode != 0 and not out:
            raise LLMError(f"Claude CLI failed: {r.stderr.strip()[:500]}")
        try:
            obj = json.loads(out)
        except json.JSONDecodeError:
            text = out
        else:
            if obj.get("is_error"):
                raise LLMError(f"Claude CLI error: {str(obj.get('result'))[:500]}")
            text = obj.get("result") or ""
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if cache and text:
        f.write_text(text)
    return text

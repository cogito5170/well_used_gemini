#!/usr/bin/env python3
"""well_used_gemini MCP 서버(stdio, JSON-RPC 2.0) -- Gemini CLI 확장이 띄운다. 표준 라이브러리만.

도구 넷. 전부 `wug.py` 를 **자식 프로세스로** 부른다 -- 이 프로세스의 stdout 은 JSON-RPC 통로라서, 여기서 다른 것이
한 줄이라도 찍히면 통로가 깨진다.

    agentic_run(question)   se_new 의 agentic 파이프라인(앞단 · 제어부 · Gate01 · 사고부 · 루프 탐지기 · sandbox ·
                            MCP · RAG)으로 물음 하나를 끝까지. 결과는 **런타임 원장에서 그린 보고서** 그대로
    agentic_setup()         처음 한 번: se_new 를 고정 커밋으로 받고 가상환경을 만든다(몇 분)
    agentic_doctor()        무엇이 준비됐나 -- 점검을 실제로 돌린다
    agentic_versions()      고정 커밋 · 설정 모델 · MCP 버전 셋

보고서의 상태 · 루프 · Gate01 · MCP 칸은 원장에서만 나온다. 모델(Gemini CLI)이 그 칸을 다시 쓰면 그것은 보고가 아니다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
VERSION = "0.1"

TOOLS = [
    {"name": "agentic_run",
     "description": "Run one request through the gated agentic pipeline (fixed model gemini-3.1-flash-lite, "
                    "runtime-checked gates, sandboxed tools). Returns the runtime report. The status, loop, gate "
                    "and MCP fields of that report come from the runtime ledger; do not restate or reinterpret them.",
     "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    {"name": "agentic_setup", "description": "First-time setup: fetch the pinned se_new commit and create the "
                                             "virtual environment. Takes a few minutes.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "agentic_doctor", "description": "Check what is ready. Runs real checks and reports each one.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "agentic_versions", "description": "Pinned se_new commit, configured model, and the MCP versions "
                                                "(protocol, sdk, server) reported by the server itself.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _wug(*args: str, timeout: int = 900) -> "tuple[int, str]":
    try:
        p = subprocess.run([sys.executable, str(HERE / "wug.py"), *args], cwd=str(HERE), env=dict(os.environ),
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + ("\n" + p.stderr if p.stderr.strip() else "")).strip()
    except subprocess.TimeoutExpired:
        return 124, f"[wug] {timeout}초 안에 안 끝났다 -- 멈췄다"


def call(name: str, a: dict) -> "tuple[str, bool]":
    """(글, isError)."""
    if name == "agentic_run":
        q = str(a.get("question", "")).strip()
        if not q:
            return "question 이 비었다", True
        code, out = _wug("run", q)
        return out + f"\n\n[wug] 끝값 {code}" + ("" if code == 0 else " (DONE 이 아니다)"), code != 0
    if name == "agentic_setup":
        code, out = _wug("setup", timeout=1800)
        return out, code != 0
    if name == "agentic_doctor":
        code, out = _wug("doctor")
        return out, code != 0
    if name == "agentic_versions":
        code, out = _wug("versions")
        return out, code != 0
    raise KeyError(name)


def handle(msg: dict) -> "dict | None":
    mid = msg.get("id")
    method = msg.get("method", "")
    if mid is None:
        return None
    try:
        if method == "initialize":
            want = (msg.get("params") or {}).get("protocolVersion")
            res = {"protocolVersion": want if want in SUPPORTED else SUPPORTED[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "well-used-gemini", "version": VERSION}}
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params") or {}
            name = p.get("name", "")
            if name not in {t["name"] for t in TOOLS}:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool: {name}"}}
            text, err = call(name, p.get("arguments") or {})
            res = {"content": [{"type": "text", "text": text}], "isError": err}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    except Exception as e:  # noqa: BLE001 -- 서버는 죽지 않고 오류로 답한다
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not JSON"}}
        else:
            out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

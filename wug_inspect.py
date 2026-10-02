#!/usr/bin/env python3
"""받아 온 se_new 의 agentic 상태를 **읽기만** 하는 도우미. wug.py 가 가상환경 파이썬으로, 체크아웃을 cwd 로 부른다.

    tools                 등록된 도구(이름 · 종류 · 설명)와 거절된 수
    runs [N]              최근 실행 N 개(기본 10): 실행 id · 끝 상태(원장의 TERMINAL) · 사건 수
    report RUN_ID         그 실행의 런타임 보고서(원장에서 그린 것 그대로)
    memory 물음            RAG 기억에서 꺼낸 메모(신뢰 안 함)
    repairs               수리 요청 대기열

아무것도 쓰지 않는다. 상태 칸은 전부 원장(events.jsonl)에서 읽는다 -- 여기서 지어내지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CO = Path.cwd()
sys.path.insert(0, str(CO))
_RUN_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def _runs_base() -> Path:
    from agentic.run import runs_root
    return Path(runs_root())


def tools() -> int:
    d = json.loads((CO / "agentic" / "tool_registry.json").read_text(encoding="utf-8"))
    print(f"등록 {len(d['tools'])}개 · 거절 {len(d.get('rejected', {}))}개 (등록 판 HEAD {str(d.get('head_sha'))[:12]})")
    for name, t in sorted(d["tools"].items()):
        decl = t.get("declaration") or {}
        params = ", ".join(sorted((decl.get("parameters") or {}).get("properties") or {}))
        desc = " ".join((decl.get("description") or "").split())[:140]
        print(f"- {name} [{t.get('kind')}] ({params}) {desc}")
    return 0


def _summary(run_dir: Path) -> dict:
    from agentic.ledger import read_events
    try:
        ev = read_events(run_dir)
    except (OSError, ValueError) as e:
        return {"run_id": run_dir.name, "state": f"(원장 못 읽음: {type(e).__name__})"}
    term = [e for e in ev if e.get("type") == "TERMINAL"]
    return {"run_id": run_dir.name, "state": (term[-1]["data"].get("state") if term else "(끝 기록 없음)"),
            "reason": (term[-1]["data"].get("reason", "") if term else ""), "events": len(ev)}


def runs(n: int = 10) -> int:
    base = _runs_base()
    dirs = sorted((p for p in base.glob("*") if (p / "events.jsonl").is_file()),
                  key=lambda p: (p / "events.jsonl").stat().st_mtime, reverse=True) if base.is_dir() else []
    if not dirs:
        print(f"실행 기록 없음 ({base})")
        return 0
    for p in dirs[:max(1, min(n, 50))]:
        s = _summary(p)
        print(f"- {s['run_id']} · {s['state']}" + (f" ({s.get('reason')})" if s.get("reason") else "")
              + (f" · 사건 {s['events']}개" if "events" in s else ""))
    return 0


def report(run_id: str) -> int:
    if not _RUN_ID.match(run_id or ""):
        print(f"run_id 꼴이 틀렸다: {run_id!r}", file=sys.stderr)
        return 2
    d = _runs_base() / run_id
    if not (d / "events.jsonl").is_file():
        print(f"그런 실행이 없다: {run_id} -- runs 로 목록을 본다", file=sys.stderr)
        return 1
    from agentic.ledger import read_events
    from agentic.render import render
    print(render(read_events(d), d))
    return 0


def memory(query: str) -> int:
    if not query.strip():
        print("물음이 비었다", file=sys.stderr)
        return 2
    import agentic.config as C
    from agentic import memory as M
    rag = C.load().rag
    hits = M.recall(query, _runs_base(), max(int(rag.get("k", 3)), 5), bool(rag.get("repo_graph", True)))
    print(M.as_context(hits) if hits else "꺼낸 메모 없음")
    return 0


def repairs() -> int:
    from agentic import breaker as BR
    ts = BR.tickets(_runs_base())
    if not ts:
        print("수리 요청 없음")
    for t in ts:
        print(json.dumps({k: t.get(k) for k in ("id", "tool", "status", "error", "reproduce")}, ensure_ascii=False))
    return 0


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "tools":
        return tools()
    if cmd == "runs":
        return runs(int(rest[0]) if rest and rest[0].isdigit() else 10)
    if cmd == "report" and rest:
        return report(rest[0])
    if cmd == "memory":
        return memory(" ".join(rest))
    if cmd == "repairs":
        return repairs()
    print(f"모르는 명령: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

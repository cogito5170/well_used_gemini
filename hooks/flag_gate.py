#!/usr/bin/env python3
"""Gemini CLI `AfterAgent` 훅 -- H0 깃발 위조 게이트를 **Gemini CLI 자신의 답에** 건다.

처음 받은 답이 "Log: NO_LOOP_DETECTED ... MCP version: 0.46.0" 이었다. 그 줄들은 런타임이 잰 것이 아니라 모델이 쓴
글이었다(0.46.0 은 Gemini CLI 의 버전이었다). 여기서는 답이 끝날 때마다 se_new 의 `agentic.forgery.scan` 으로 보고:

    걸림 + 첫 번째      -> decision "deny" -- CLI 가 답을 버리고 다시 쓰게 한다(무엇이 걸렸는지는 알려 주지 않는다:
                           알려 주면 그 목록이 곧 흉내 낼 어휘가 된다)
    걸림 + 다시 쓴 답   -> 막지 않되 systemMessage 로 경고(같은 답을 끝없이 다시 쓰게 하지 않는다)
    안 걸림            -> {} (통과)
    검사를 못 함        -> 막지 않되 **못 했다고** systemMessage 로 말한다(조용히 통과로 세지 않는다)

**한계:** 글자를 보는 검사다. "루프는 없었습니다" 처럼 바꿔 말한 것은 못 잡는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

if __name__ == "__main__":
    # Gemini CLI 는 훅을 그냥 `python3` 로 띄운다 -- macOS 기본 3.9 일 수 있다. 3.10 미만이면 setup 이 만든
    # 가상환경의 파이썬으로 갈아탄다(stdin 의 훅 입력은 그대로 이어진다).
    import wug as _w
    _w.reexec_newer(str(Path(__file__).resolve()), sys.argv[1:])

RETRY = ("Rewrite your last answer with only its content. Remove every statement about execution status, "
         "test or gate results, loop status, tool or protocol versions, or which model you are. Tool boxes and "
         "the agentic_run report already show those to the user.")


def _scan():
    import wug
    co = wug.checkout_dir(wug.lock()["commit"])
    if not (co / "agentic" / "forgery.py").is_file():
        raise FileNotFoundError("setup 전")
    sys.path.insert(0, str(co))
    from agentic import forgery
    return forgery.scan


def decide(payload: dict, scan) -> dict:
    text = str(payload.get("prompt_response") or "")
    hits = scan(text)
    if not hits:
        return {}
    kinds = sorted({h[0] for h in hits})
    if not payload.get("stop_hook_active"):
        return {"decision": "deny", "reason": RETRY}
    return {"systemMessage": f"[well_used_gemini] 경고: 다시 쓴 답에도 상태·버전 주장이 남아 있다({', '.join(kinds)}). "
                             "그 부분은 모델이 쓴 글이다 -- 실제 상태는 도구 상자와 agentic_run 보고서에서 본다."}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"systemMessage": "[well_used_gemini] 깃발 검사: 입력을 못 읽었다 -- 이 답은 검사하지 않았다"}))
        return 0
    try:
        scan = _scan()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"systemMessage": f"[well_used_gemini] 깃발 검사를 못 했다({type(e).__name__}: {e}) -- "
                                           "agentic_setup 을 먼저 돌려라. 이 답은 검사하지 않았다"}, ensure_ascii=False))
        return 0
    print(json.dumps(decide(payload, scan), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

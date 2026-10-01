#!/usr/bin/env python3
"""Gemini CLI `BeforeAgent` 훅 -- WALP 앞단. 잡담이면 모델을 부르지 않고 WALP 가 답한다.

판정은 se_new 의 `agentic.front.judge` 그대로다(같은 판정기 파일 · 같은 sha256 고정 · `//` 로 건너뛰기).

    잡담        -> decision "deny"(이 말은 모델에 안 간다) + systemMessage 로 WALP 의 답 · 건너뛰는 법
    그 밖       -> {} (모델로)
    판정을 못 함 -> {} (모델로) + systemMessage 로 못 했다고 -- 사람의 말을 잃는 쪽으로 틀리지 않는다

**알려진 약점(WALP 저장소가 잰 것):** 일이 섞인 말("고마워요 이제 머지해줘")을 잡담으로 삼킨다. 그래서 잡담으로 답할
때마다 `//` 를 같이 보인다. 끄려면 Gemini CLI 를 `WUG_FRONT=0` 으로 띄운다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

if __name__ == "__main__":
    # Gemini CLI 는 훅을 그냥 `python3` 로 띄운다 -- macOS 기본 3.9 일 수 있다. 3.10 미만이면 setup 이 만든
    # 가상환경의 파이썬으로 갈아탄다(stdin 의 훅 입력은 그대로 이어진다).
    import wug as _w
    _w.reexec_newer(str(Path(__file__).resolve()), sys.argv[1:])


def _judge_fn():
    import wug
    co = wug.checkout_dir(wug.lock()["commit"])
    if not (co / "agentic" / "front.py").is_file():
        raise FileNotFoundError("setup 전")
    sys.path.insert(0, str(co))
    from agentic import config as C
    from agentic import front as W
    cfg = C.load(co / "agentic" / "config.json")
    return lambda text: W.judge(text, cfg)


def decide(prompt: str, judge) -> dict:
    r = judge(prompt)
    if r.route != "small":
        return {}
    return {"decision": "deny", "reason": "WALP 앞단이 잡담으로 답했다(모델 호출 0)",
            "systemMessage": f"[WALP] {r.reply}  (모델 호출 0 · {r.data.get('ms')} ms -- 일이 담긴 말이었다면 "
                             "앞에 // 를 붙여 다시 보내라)"}


def main() -> int:
    if os.environ.get("WUG_FRONT") == "0":
        print("{}")
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        out = decide(str(payload.get("prompt") or ""), _judge_fn())
    except Exception as e:  # noqa: BLE001
        out = {"systemMessage": f"[well_used_gemini] WALP 앞단을 못 돌렸다({type(e).__name__}) -- 그대로 모델로 보낸다"}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

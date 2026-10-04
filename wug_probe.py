"""D3 탐침 -- 진짜 키로 분당 한도를 넘겨 보는 한 번의 실행 (CMD-WUG2 S4 · HUMAN_QUEUE Q10).

    python3 wug.py d3

  · 모델 요청은 **많아야 15번**이다(CMD-WUG2 rev 2 · 무료 하루 20번을 여러 세션이 나눠 쓴다)
  · 다시 쳐도 안전하다: 원장(out/sched.jsonl)에 한 번이라도 보낸 기록이 있으면 **하나도 보내지 않고** 그때의 결과를 다시 찍는다
  · 지킴이를 분당 60 으로 풀어 아주 짧은 요청을 잇달아 보낸다 -- 서버의 분당 한도에 부딪힐 때까지
  · 분당 429 가 나면 rlo 가 retryDelay 만큼 **자고** 그 걸음을 다시 보낸다. 다시 보낸 것이 성공하면 거기서 멈춘다
    (넘었다 · 기다렸다 · 같은 모델로 이어 받았다 -- 그것이 D3 이다). 하루 429 · 다른 오류면 그 자리에서 멈춘다
  · 키는 GEMINI_API_KEY 에서 읽는다(wug.py 가 keys.env · ~/.gemini/.env 에서 채운다). 화면 · 원장 어디에도 안 싣는다

마지막 두 줄이 붙여 보낼 것이다:
    [d3] 보냄 N/15 · 성공 K · 429 분당 M (retryDelay s [...]) · 기다린 뒤 성공 R · 429 하루 D · 다른 오류 E · 모델 gemini-3-flash-preview · 응답이 밝힌 모델 [...] · 넘음=예|아니오
    exit=0 넘고 이어 받음 · 6 넘었지만 상한까지 못 이어 받음 · 5 15번에 못 넘음 · 4 하루 한도 · 1 다른 오류
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import wug_media as WM  # noqa: E402
from wug_model import MODEL  # noqa: E402

CAP = 15         # 모델 요청 상한 -- CMD-WUG2 rev 2 S4
RPM = 60         # 지킴이를 풀어 둔다: 한도를 정하는 것은 서버다
ASK = "Reply with the single word: ok"


def default_out() -> Path:
    return Path(os.environ.get("WUG_HOME") or Path.home() / ".cache" / "well_used_gemini") / "d3-probe"


def _rows(out: Path, name: str) -> list:
    p = out / name
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def summary(out: Path) -> "tuple[str, int]":
    """원장 두 개(rlo 의 sched.jsonl · 우리 probe.jsonl)를 센다.
    끝값: 0 넘고 이어 받음 · 6 넘었지만 못 이어 받음 · 5 못 넘음 · 4 하루 한도 · 1 다른 오류."""
    probe = _rows(out, "probe.jsonl")
    sent = len(probe)                           # 서버로 실제 나간 요청(멈춘 뒤의 걸음은 rlo 에 dispatch 로 남아도 안 나갔다)
    oks = [r for r in probe if r.get("outcome") == "ok"]
    minute = [r for r in probe if r.get("outcome") == "429" and r.get("scope") == "minute"]
    day = [r for r in probe if r.get("outcome") == "429" and r.get("scope") == "day"]
    other = [r for r in probe if r.get("outcome") == "error"]
    first429 = min((r["i"] for r in minute), default=None)
    resumed = [r for r in oks if first429 is not None and r["i"] > first429]
    models = sorted({r.get("modelVersion") or "미보고" for r in oks})
    crossed = bool(minute)
    line = (f"[d3] 보냄 {sent}/{CAP} · 성공 {len(oks)} · 429 분당 {len(minute)} (retryDelay s {[r.get('seconds') for r in minute]}) · "
            f"기다린 뒤 성공 {len(resumed)} · 429 하루 {len(day)} · "
            f"다른 오류 {len(other)}{(' ' + str([r.get('error') for r in other])) if other else ''} · "
            f"모델 {MODEL} · 응답이 밝힌 모델 {models} · 넘음={'예' if crossed else '아니오'}")
    code = 1 if other else 4 if day else (0 if resumed else 6) if crossed else 5
    return WM._hide(line), code


def run(out: "Path | None" = None, poster=None, clock=None, sleep=None) -> "tuple[str, int]":
    out = Path(out or default_out())
    if any(r.get("kind") == "dispatch" for r in _rows(out, "sched.jsonl")):
        print(f"[d3] 이미 돌렸다 -- 하나도 보내지 않고 그때의 원장을 다시 센다 ({out})")
        return summary(out)
    try:
        from rlo.governor import Governor
        from rlo.scheduler import Scheduler, Step
    except ImportError:
        return "[d3] rlo(ga-sdk)가 가상환경에 없다 -- python3 wug.py setup", 1
    WM._key()                                   # 키가 없으면 보내기 전에 멈춘다(no_api_key)
    out.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    sent = {"n": 0, "seen429": False, "stop": False}

    def record(row: dict) -> None:
        with lock, open(out / "probe.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def provider(payload):
        with lock:
            if sent["stop"]:                    # 할 일을 다 했거나(넘고 이어 받음) 멈춰야 한다(다른 오류) -- 보내지 않는다
                return {"text": None, "skipped": True}
            if sent["n"] >= CAP:                # rlo 가 무엇을 하든 상한 너머는 없다
                raise RuntimeError("cap_reached")
            sent["n"] += 1
            i = sent["n"]
        try:
            resp = WM._post(MODEL, payload, poster)
        except WM.QuotaWait as q:
            with lock:
                sent["seen429"] = True
            record({"i": i, "outcome": "429", "scope": q.scope, "seconds": q.seconds})
            raise
        except Exception as e:                  # noqa: BLE001 -- 원장에 적고 rlo 에 넘긴다
            with lock:
                sent["stop"] = True
            record({"i": i, "outcome": "error", "error": WM._hide(str(e))[:160]})
            raise
        with lock:
            if sent["seen429"]:                 # 429 뒤에 기다렸다 보낸 것이 성공 -- 증거가 다 모였다
                sent["stop"] = True
        record({"i": i, "outcome": "ok", "modelVersion": resp.get("modelVersion")})
        return {"text": "\n".join(WM._texts(resp)).strip()[:40], "modelVersion": resp.get("modelVersion") or "미보고"}

    body = {"contents": [{"role": "user", "parts": [{"text": ASK}]}],
            "generationConfig": {"maxOutputTokens": 8, "temperature": 0}}
    steps = [Step(f"ping{i}", "probe.ping", payload=body) for i in range(1, CAP + 1)]
    gov = Governor({MODEL: {"rpm": RPM}}, **({"clock": clock} if clock else {}))
    sched = Scheduler(steps, gov, provider, kinds={"schema": "rlo-step-kinds/1", "steps": {"probe.ping": "model"}},
                      run_id="d3", ledger=str(out / "sched.jsonl"), l0=str(out / "l0.jsonl"), state=str(out / "state.json"),
                      **({"clock": clock} if clock else {}), **({"sleep": sleep} if sleep else {}))
    sched.run(wait=True)                        # 분당 429 면 retryDelay 만큼 자고 다시 보낸다 · 하루 429 면 세우고 돌아온다
    return summary(out)


def main(argv) -> int:
    try:
        line, code = run()
    except WM.MediaError as e:
        print(f"[d3] {WM._hide(str(e))}")
        return 1
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

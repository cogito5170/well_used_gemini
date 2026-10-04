"""D3 탐침(wug_probe.py · wug.py d3) 시험 -- 가짜 Gemini 서버에 **프로세스째** 돌린다(진짜 HTTP · 진짜 rlo).
진짜 Gemini 는 부르지 않는다. 보는 것: 서버가 받은 요청 수가 15를 넘지 않는다 · 분당 429 뒤 기다렸다 이어 받으면 멈춘다 · 다시 치면 0번 보낸다 ·
429 분당/하루를 가린다 · 끝값 · 키가 출력에 없다.

    ~/.cache/well_used_gemini/venv/bin/python tests/test_d3_probe.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = []


def ok(cond, label):
    print(f"    {'OK  ' if cond else '실패'} {label}")
    if not cond:
        fails.append(label)


KEY = "AIza" + "SyD3PROBE0" * 3
plan = {"mode": "ok", "hits": 0, "bodies": []}


def q429(per: str, delay: str = "41s") -> dict:
    d = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
          "violations": [{"quotaId": f"GenerateRequestsPer{per}PerProjectPerModel-FreeTier"}]}]
    if per == "Minute":
        d.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    return {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": f"quota {KEY}", "details": d}}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        plan["hits"] += 1
        plan["bodies"].append((self.path, self.headers.get("x-goog-api-key"), body))
        n, mode = plan["hits"], plan["mode"]
        if mode == "minute_once" and n == 2:              # 2번째에 한 번만 분당 429 -- 기다렸다 다시 보내면 통과
            code, obj = 429, q429("Minute", "0.5s")
        elif mode == "minute_forever" and n >= 2:         # 2번째부터 계속 분당 429 -- 상한까지
            code, obj = 429, q429("Minute", "0.2s")
        elif mode == "day":
            code, obj = 429, q429("Day")
        elif mode == "500":
            code, obj = 500, {"error": {"message": "boom"}}
        else:
            code, obj = 200, {"modelVersion": "gemini-3-flash-preview-001",
                              "candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def probe(home: Path, mode: str, key: "str | None" = KEY) -> "tuple[int, str]":
    plan["mode"] = mode
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
    env.update({"WUG_GEMINI_API": f"http://127.0.0.1:{srv.server_port}/v1beta", "WUG_HOME": str(home),
                "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1", "HOME": str(home)})
    if key:
        env["GEMINI_API_KEY"] = key
    r = subprocess.run([sys.executable, str(ROOT / "wug_probe.py")], env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


with tempfile.TemporaryDirectory() as tmp:
    T = Path(tmp)

    def last_line(out):
        return out.strip().splitlines()[-1] if out.strip() else ""

    print("[넘고 이어 받음] 2번째에 분당 429 -- retryDelay 만큼 자고 같은 모델로 다시 보내 성공하면 멈춘다")
    plan["hits"], plan["bodies"] = 0, []
    code, out = probe(T / "a", "minute_once")
    last = last_line(out)
    ok(code == 0 and "넘음=예" in last and "429 분당 1 (retryDelay s [0.5])" in last and "기다린 뒤 성공 1" in last
       and "보냄 3/15" in last, f"끝값 0 · 넘음=예 · 기다린 뒤 성공 1 ({last})")
    ok(plan["hits"] == 3, f"서버가 받은 요청 3번(성공 · 429 · 다시 보냄) -- 이어 받은 뒤 더 안 보낸다({plan['hits']})")
    ok(all(b[1] == KEY and "/models/gemini-3-flash-preview:generateContent" in b[0] for b in plan["bodies"]),
       "키는 머리로 · 모델은 하나(gemini-3-flash-preview) -- 다시 보낸 것도 같은 모델")
    ok(KEY not in out and "AIza" not in out, "출력에 키가 없다(서버가 오류 글에 키를 실어 보내도)")

    print("[다시 치기] 같은 자리에서 또 치면 하나도 보내지 않는다")
    before = plan["hits"]
    code2, out2 = probe(T / "a", "ok")
    ok(plan["hits"] == before and code2 == code and last_line(out2) == last and "이미 돌렸다" in out2,
       f"요청 0번 · 같은 줄 · 같은 끝값 ({plan['hits'] - before})")

    print("[하루 한도] 첫 요청에서 하루 429 -- 끝값 4, 1번만 · 다시 쳐도 0번(세운 걸음을 이어 보내지 않는다)")
    plan["hits"] = 0
    code, out = probe(T / "c", "day")
    last = last_line(out)
    ok(plan["hits"] == 1 and code == 4 and "429 하루 1" in last, f"요청 1번 · 끝값 4 ({last})")
    code2, out2 = probe(T / "c", "ok")
    ok(plan["hits"] == 1 and code2 == 4, f"한도가 풀린 뒤 다시 쳐도 더 안 보낸다 -- 하루 몫은 한 번만(합 {plan['hits']})")

    print("[못 넘음] 15번 다 성공이면 15에서 멈추고 '아니오' -- 끝값 5")
    plan["hits"] = 0
    code, out = probe(T / "b", "ok")
    last = last_line(out)
    ok(plan["hits"] == 15 and code == 5 and "보냄 15/15" in last and "넘음=아니오" in last
       and "['gemini-3-flash-preview-001']" in last, f"요청 15번 · 끝값 5 ({last})")

    print("[넘었지만 못 이어 받음] 2번째부터 계속 분당 429 -- 상한 15에서 멈춘다, 끝값 6")
    plan["hits"] = 0
    code, out = probe(T / "g", "minute_forever")
    last = last_line(out)
    ok(plan["hits"] == 15 and code == 6 and "기다린 뒤 성공 0" in last and "429 분당 14" in last,
       f"요청 15번 · 끝값 6 ({last})")

    print("[다른 오류] 500 -- 끝값 1, 그 자리에서 멈춘다")
    plan["hits"] = 0
    code, out = probe(T / "d", "500")
    last = last_line(out)
    ok(code == 1 and plan["hits"] == 1 and "다른 오류 1" in last, f"끝값 1 · 요청 {plan['hits']}번 ({last})")

    print("[키 없음] 보내기 전에 멈춘다")
    plan["hits"] = 0
    code, out = probe(T / "e", "ok", key=None)
    ok(code == 1 and plan["hits"] == 0 and "no_api_key" in out, f"요청 0번 · no_api_key ({out.strip()[-80:]})")

srv.shutdown()
print()
if fails:
    print(f"d3 probe: {len(fails)}개 실패 -- {fails}")
    sys.exit(1)
print("d3 probe: 15번 상한 · 넘고 이어 받음 · 다시 치면 0번 · 429 분당/하루 · 끝값 · 키 가림 -- 통과")

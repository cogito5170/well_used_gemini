"""글쓰기 실험(wug_bench.py) · 글쓰기 모드(wug.py write) 시험 -- 가짜 `gemini` 명령과 가짜 Gemini API 서버를 지어
**실험을 끝까지 돌린다.** 진짜 모델은 부르지 않는다.

    python3 tests/test_bench.py        (requests 가 있는 파이썬 -- setup 의 가상환경)
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
sys.path.insert(0, str(ROOT))
fails = []


def ok(cond, label):
    print(f"    {'OK  ' if cond else '실패'} {label}")
    if not cond:
        fails.append(label)


import wug_bench as B  # noqa: E402

print("[재기] 대리 지표가 오늘 본 증상을 가르는가")
facts = ["상점 창|쇼윈도", "코트|coat", "강가|river"]
good = "나는 불 켜진 상점 창 앞에 선 사람 앞에서 멈춘다.\n긴 코트가 빛을 받는다.\n\n## 주의할 점\n- 샤넬 인용(출처 미확인)"
bad = "패션은 공간과 나를 잇는 필터다.\n공기의 밀도와 완벽히 호흡함.\n레이아웃을 제안함."
g, b = B.measure(good, facts, B.DEFAULT_ABSTRACT), B.measure(bad, facts, B.DEFAULT_ABSTRACT)
ok(g["photo_facts"] == 2 and b["photo_facts"] == 0, f"사진 사실: {g['photo_facts']} vs {b['photo_facts']}")
ok(g["memo_ratio"] == 0 and b["memo_ratio"] == round(2 / 3, 3), f"메모체 비율: {g['memo_ratio']} vs {b['memo_ratio']}")
ok(g["abstract"] == 0 and b["abstract"] == 4, f"추상어: {g['abstract']} vs {b['abstract']}")
ok(g["review"] and not b["review"], "자기 검토 표지")
ok(B.measure("", facts, [])["memo_ratio"] is None, "문장이 없으면 비율은 None(0 이 아니다)")
ok(B.measure("Long coat by the river.", facts, [])["photo_facts"] == 2, "영어 동의어도 센다(대소문자 무시)")

print("[모델] 큰 모델은 목록에서 -- 미리보기가 아닌 pro 먼저")
lst = [{"name": "models/gemini-9.0-pro-preview", "supportedGenerationMethods": ["generateContent"]},
       {"name": "models/gemini-8.5-pro", "supportedGenerationMethods": ["generateContent"]},
       {"name": "models/gemini-9.0-pro-image", "supportedGenerationMethods": ["generateContent"]},
       {"name": "models/gemini-9.0-flash", "supportedGenerationMethods": ["generateContent"]}]
os.environ.pop("WUG_BENCH_BIG", None)
ok(B.pick_big(lambda: lst) == "gemini-8.5-pro", "pro · 미리보기 아님 · image 아님")
os.environ["WUG_BENCH_BIG"] = "x-big"
ok(B.pick_big(lambda: lst) == "x-big", "WUG_BENCH_BIG 이 이긴다")
os.environ.pop("WUG_BENCH_BIG")

seen = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append((self.path, self.headers.get("x-goog-api-key"), body))
        model = self.path.split("/models/")[1].split(":")[0]
        text = ("강가에 선 코트. 문장이다." if "big" in model else "공간과 나를 잇는 필터임.") + f" #{len(seen)}"
        parts = [{"thought": True, "text": "THOUGHT-생각"}, {"text": text}]
        b = json.dumps({"modelVersion": model + "-001", "candidates": [{"content": {"parts": parts}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()

FAKE_GEMINI = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = os.environ["FAKE_LOG"]
rec = {"argv": a, "cwd": os.getcwd(), "files": sorted(os.listdir(".")), "sysmd": os.environ.get("GEMINI_SYSTEM_MD"),
       "mode": os.environ.get("WUG_MODE")}
open(log, "a").write(json.dumps(rec, ensure_ascii=False) + "\n")
if "-p" not in a:
    sys.exit(0)
text = ("강가의 올리브 파카 앞에서 멈춘다.\n\n## 주의할 점\n- 없음" if rec["sysmd"] else "패션은 필터임.") + " #" + str(sum(1 for _ in open(log)))
print(json.dumps({"session_id": "s", "response": text, "stats": {"models": {"gemini-3.1-flash-lite-002": {}}}}))
'''

with tempfile.TemporaryDirectory() as tmp:
    T = Path(tmp)
    (T / "bin").mkdir()
    (T / "bin" / "gemini").write_text(FAKE_GEMINI)
    (T / "bin" / "gemini").chmod(0o755)
    (T / "p1.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    key = "AIza" + "SyBENCHTEST" * 3
    spec = {"prompt": "패션 문항 셋에 답하라", "photos": [str(T / "p1.jpg")], "facts": ["강가|river", "파카|parka"],
            "runs": 2}
    (T / "spec.json").write_text(json.dumps(spec, ensure_ascii=False))
    env = {**os.environ, "PATH": f"{T / 'bin'}:{os.environ['PATH']}", "FAKE_LOG": str(T / "log.jsonl"),
           "GEMINI_API_KEY": key, "WUG_GEMINI_API": f"http://127.0.0.1:{srv.server_port}/v1beta",
           "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1", "GEMINI_SYSTEM_MD": "/should/not/leak/into/a"}

    print("[실험] 네 조건을 끝까지 -- 가짜 gemini 명령 · 가짜 API")
    p = subprocess.run([sys.executable, str(ROOT / "wug_bench.py"), str(T / "spec.json"), "--big", "my-big",
                        "--out", str(T / "out")], env=env, capture_output=True, text=True, timeout=120)
    ok(p.returncode == 0, f"끝값 0 ({p.stderr.strip()[-200:]})")
    calls = [json.loads(l) for l in (T / "log.jsonl").read_text().splitlines()]
    ok(len(calls) == 4, f"CLI 는 a·b 만, 2번씩 = 4번 ({len(calls)})")
    a_calls = [c for c in calls if not c["sysmd"]]
    b_calls = [c for c in calls if c["sysmd"]]
    ok(len(a_calls) == 2 and len(b_calls) == 2, "a 에는 GEMINI_SYSTEM_MD 가 없다(부모 환경에 있어도 지운다) · b 에는 있다")
    ok(all(c["sysmd"] == str(ROOT / "writing" / "system.md") for c in b_calls), "b 의 지시문은 writing/system.md")
    c0 = calls[0]["argv"]
    ok(c0[c0.index("-m") + 1] == "gemini-3.1-flash-lite" and "-o" in c0 and "--skip-trust" in c0,
       "a·b 는 -m 작은 모델 · -o json · --skip-trust")
    ok("@photo1.jpg" in c0[c0.index("-p") + 1] and all("photo1.jpg" in c["files"] for c in calls),
       "사진을 빈 임시 폴더로 복사해 @photo1.jpg 로 붙인다")
    ok(all(c["cwd"] != str(ROOT) for c in calls), "CLI 는 이 저장소가 아니라 임시 폴더에서 돈다")
    api = [s for s in seen]
    ok(len(api) == 4 and sum("flash-lite" in s[0] for s in api) == 2 and sum("my-big" in s[0] for s in api) == 2,
       "API 는 c(작은 모델)·d(큰 모델) 2번씩")
    body = api[0][2]
    st = body["system_instruction"]["parts"][0]["text"]
    ok("writing partner" in st and "${AvailableTools}" not in st, "c·d 도 같은 글쓰기 지시문(도구 칸은 채웠다)")
    ok(body["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg" and api[0][1] == key,
       "사진은 inline · 키는 머리로")
    rep = (T / "out" / "report.md").read_text()
    ok("| a CLI 그대로 | 2/2 |" in rep and "| d API · 큰 모델 | 2/2 |" in rep, "보고서 표에 네 조건")
    ok("gemini-3.1-flash-lite-002" in rep and "my-big-001" in rep, "모델 칸은 응답이 밝힌 이름")
    ok("2 (2–2) / 2" in rep.split("| b ")[1].split("\n")[0] and "0 (0–0) / 2" in rep.split("| a ")[1].split("\n")[0],
       "사진 사실: b 2/2 · a 0/2 (가짜가 준 글 그대로 셌다)")
    key_map = json.loads((T / "out" / "key.json").read_text())
    blind_md = (T / "out" / "blind.md").read_text()
    ok(len(key_map) == 8 and all(f"## {t}" in blind_md for t in key_map), "블라인드 8벌 · 열쇠가 다 맞는다")
    ok("CLI" not in blind_md and "flash" not in blind_md and "my-big" not in blind_md, "blind.md 에 출처가 안 새어 나온다")
    raw = {f.name for f in (T / "out" / "raw").iterdir()}
    ok(not any("THOUGHT" in (T / "out" / "raw" / n).read_text() for n in raw), "모델의 생각(thought) 부분은 글에 안 넣는다")
    ok(len({(T / "out" / "raw" / n).read_text() for n in raw}) == 8, "가짜가 매번 다른 글을 준다(열쇠 검사가 뜻을 갖게)")
    for tag, k in key_map.items():
        txt = blind_md.split(f"## {tag}\n\n")[1].split("\n\n---")[0].strip()
        if txt != (T / "out" / "raw" / f"{k['cond']}-{k['run']}.md").read_text().strip():
            ok(False, f"열쇠 {tag} 가 다른 글을 가리킨다")
            break
    else:
        ok(len(raw) == 8, "열쇠가 가리키는 글이 그 조건의 원문과 같다(8벌 전부)")

    rows = [{"cond": c, "run": i, "models": [], "text": f"{c}{i}"} for c in "abcd" for i in (1, 2)]
    order = []
    for seed in range(5):
        d = T / f"blind{seed}"
        d.mkdir()
        B.blind(rows, d, seed=seed)
        order.append([v["cond"] + str(v["run"]) for v in json.loads((d / "key.json").read_text()).values()])
    ok(all(o != [r["cond"] + str(r["run"]) for r in rows] for o in order),
       "블라인드 순서는 실행 순서가 아니다(자리로 출처가 새지 않게)")

    print("[실험] 실패도 표에 남는다")
    (T / "bin" / "gemini").unlink()
    p = subprocess.run([sys.executable, str(ROOT / "wug_bench.py"), str(T / "spec.json"), "--only", "a",
                        "--runs", "1", "--out", str(T / "out2")], env=env, capture_output=True, text=True, timeout=60)
    ok("gemini_not_found" in (T / "out2" / "report.md").read_text() and "0/1" in (T / "out2" / "report.md").read_text(),
       "gemini 가 없으면 '0/1 · gemini_not_found' -- 조용히 빠지지 않는다")
    p = subprocess.run([sys.executable, str(ROOT / "wug_bench.py"), str(T / "spec.json"), "--measure", str(T / "spec.json")],
                       env=env, capture_output=True, text=True)
    ok(p.returncode == 0 and "사진 사실" in p.stdout, "--measure 는 실험 없이 글만 잰다")

    print("[글쓰기 모드] wug.py write 가 지시문을 바꿔 gemini 를 띄운다")
    (T / "bin" / "gemini").write_text(FAKE_GEMINI)
    (T / "bin" / "gemini").chmod(0o755)
    (T / "log.jsonl").unlink()
    p = subprocess.run([sys.executable, str(ROOT / "wug.py"), "write", "--version"],
                       env={**env, "WUG_HOME": str(T / "home")}, capture_output=True, text=True, timeout=60)
    rec = json.loads((T / "log.jsonl").read_text().splitlines()[0])
    ok(rec["sysmd"] == str(ROOT / "writing" / "system.md") and rec["mode"] == "write" and rec["argv"] == ["--version"],
       "GEMINI_SYSTEM_MD=writing/system.md · 인자는 그대로 넘긴다")

print("[지시문] writing/system.md")
s = (ROOT / "writing" / "system.md").read_text()
ok("${AvailableTools}" in s and "fewer than 3 lines" not in s, "도구 목록 자리 · '3줄 이하' 없음")
ok("주의할 점" in s and "출처 미확인" in s and "Never invent events" in s, "검토 칸 · 미확인 인용 표시 · 사용자 삶을 지어내지 않기")
ok(all(w not in s for w in ("NO_LOOP", "A_TO_B", "RED_RED")), "깃발 어휘가 없다")

srv.shutdown()
print()
if fails:
    print(f"bench: {len(fails)}개 실패 -- {fails}")
    sys.exit(1)
print("bench: 대리 지표 · 네 조건 · 응답이 밝힌 모델 · 블라인드 열쇠 · 실패 기록 · 글쓰기 모드 -- 통과")

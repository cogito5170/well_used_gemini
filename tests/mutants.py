"""D4 변이 -- 시험이 그 결함을 정말 잡는지 저장소에서 다시 돌린다 (CMD-WUG1 D4 · CMD-WUG2 S2).

변이마다 저장소 사본(git ls-files 의 파일들)을 임시 폴더에 만들고, 한 곳을 바꾸고, 정해진 시험을 돌린다.
시험이 **빨개지면** 잡은 것(killed), 초록이면 살아남은 것(SURVIVED)이다. 작업 디렉터리는 건드리지 않는다.
먼저 바꾸지 않은 사본에서 같은 시험이 초록인지 본다 -- 원래 빨간 시험으로 '잡았다' 고 하지 않으려고.

    python3 tests/mutants.py            # 전부
    python3 tests/mutants.py M6         # 하나만
    끝값 0 = 전부 잡음 · 1 = 살아남은 것 · 터진 것(단언이 아니라 오류로 빨간 것) · 바꾸지 못한 것이 있다

rlo · PIL · requests 가 있는 파이썬으로 돌린다(setup 이 만든 가상환경):
    ~/.cache/well_used_gemini/venv/bin/python tests/mutants.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

POST = "        resp = WM._post(MODEL, payload, poster)\n"

# (id, 무엇을 망가뜨리나, 시험 파일, [(파일, 옛 글, 새 글), ...])
MUTANTS = [
    ("M1", "busy_retry: 공급자가 429 를 기다리지 않고 바로 3번 되풀이한다", "tests/test_essay.py",
     [("wug_essay.py", POST,
       "        for _ in range(3):\n"
       "            try:\n"
       "                resp = WM._post(MODEL, payload, poster)\n"
       "                break\n"
       "            except WM.QuotaWait:\n"
       "                continue\n")]),
    ("M2", "budget_ignored: 지킴이 예산을 무한으로 -- 예산이 비어도 모델 걸음을 보낸다", "tests/test_essay.py",
     [("wug_essay.py", '    gov = Governor({MODEL: {"rpm": rpm}}', '    gov = Governor({MODEL: {"rpm": 10**9}}')]),
    ("M3", "tool_blocked: 검사(도구) 걸음이 모든 초안(모델)을 기다린다 -- 모델 줄에 막힌다", "tests/test_essay.py",
     [("wug_essay.py",
       '        steps.append(Step(f"gate{k}", "essay.gate", after=(f"draft{k}",), fn=gate_k))',
       "        pending_gates.append((k, gate_k))"),
      ("wug_essay.py",
       "    temps = TEMPS[:n] + [1.0] * max(0, n - len(TEMPS))\n",
       "    temps = TEMPS[:n] + [1.0] * max(0, n - len(TEMPS))\n    pending_gates = []\n"),
      ("wug_essay.py",
       "    def select(res):",
       "    for k, gk in pending_gates:\n"
       '        steps.append(Step(f"gate{k}", "essay.gate", after=tuple(f"draft{j}" for j in range(1, n + 1)), fn=gk))\n\n'
       "    def select(res):")]),
    ("M4", "unbounded_result: 도구 결과를 자르지 않는다", "tests/test_wug.py",
     [("wug_mcp.py", "    if len(text) <= cap:\n        return text\n", "    if True:\n        return text\n")]),
    ("M5", "unbounded_read: result_read 가 상한 없이 읽는다", "tests/test_wug.py",
     [("wug_mcp.py", "    length = max(1, min(int(length), RESULT_CAP))", "    length = max(1, int(length))")]),
    ("M6", "day_retry_20: 하루 한도 429 를 20번 되풀이한다(baseline BD-276 의 M6)", "tests/test_essay.py",
     [("wug_essay.py", POST,
       "        for _try in range(20):\n"
       "            try:\n"
       "                resp = WM._post(MODEL, payload, poster)\n"
       "                break\n"
       "            except WM.QuotaWait as q:\n"
       '                if q.scope != "day" or _try == 19:\n'
       "                    raise\n")]),
    ("M7", "probe_cap_4: D3 탐침이 4번 보낸다(상한 3)", "tests/test_d3_probe.py",
     [("wug_probe.py", "CAP = 3 ", "CAP = 4 ")]),
    ("M8", "probe_rerun_sends: 다시 치면 또 보낸다(하루 몫을 두 번 쓴다)", "tests/test_d3_probe.py",
     [("wug_probe.py", '    if any(r.get("kind") == "dispatch" for r in _rows(out, "sched.jsonl")):',
       '    if False:')]),
]


def copy_repo(dst: Path) -> None:
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
    for rel in filter(None, files.decode().split("\0")):
        src = ROOT / rel
        if src.is_file():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst / rel)


def run_test(repo: Path, test: str) -> "tuple[int, str]":
    """끝값과 **무엇에서** 빨개졌는지(첫 '실패' 줄, 없으면 Traceback 의 끝 줄) -- 엉뚱한 이유(문법 오류 · 로드 실패)로
    빨개진 것을 '잡았다' 고 하지 않으려고 같이 보인다."""
    r = subprocess.run([sys.executable, test], cwd=repo, capture_output=True, text=True, timeout=900)
    lines = (r.stdout + r.stderr).splitlines()
    why = next((x.strip() for x in lines if x.startswith("    실패")), "")
    if not why and r.returncode != 0:
        why = "CRASH " + (lines[-1].strip() if lines else "(출력 없음)")
    return r.returncode, why


def main(argv) -> int:
    want = set(argv)
    todo = [m for m in MUTANTS if not want or m[0] in want]
    if not todo:
        print(f"그런 변이가 없다: {sorted(want)} (있는 것: {[m[0] for m in MUTANTS]})")
        return 2
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        base.mkdir()
        copy_repo(base)
        for test in sorted({m[2] for m in todo}):
            code, why = run_test(base, test)
            print(f"[기준] 바꾸지 않은 사본 · {test} · 끝값 {code} {why}")
            if code != 0:
                print("  기준이 이미 빨갛다 -- 이 위에서 '잡았다' 는 뜻이 없다")
                return 1
        for mid, what, test, edits in todo:
            repo = Path(tmp) / mid
            shutil.copytree(base, repo)
            applied = True
            for f, old, new in edits:
                p = repo / f
                s = p.read_text(encoding="utf-8")
                if s.count(old) != 1:
                    applied = False
                    break
                p.write_text(s.replace(old, new, 1), encoding="utf-8")
            if not applied:
                print(f"{mid} NOT_APPLIED  {what}  -- 바꿀 자리를 못 찾았다(코드가 바뀌었으면 변이도 고쳐라)")
                bad.append(mid)
                continue
            code, why = run_test(repo, test)
            # 시험의 단언이 빨개져야 잡은 것이다. 터져서(CRASH) 빨간 것은 시험이 그 결함을 본 것이 아니다
            verdict = "SURVIVED" if code == 0 else ("CRASHED" if why.startswith("CRASH") else "killed")
            print(f"{mid} {verdict:<8} {test} 끝값 {code}  {what}\n      -> {why or '(초록)'}")
            if verdict != "killed":
                bad.append(mid)
    print(f"\n변이 {len(todo)}개 · 잡음 {len(todo) - len(bad)} · 못 잡음 {bad or '없음'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

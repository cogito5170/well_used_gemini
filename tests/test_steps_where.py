"""steps.json 의 where 가 가리키는 함수가 **지금 있는지** 본다 (CMD-WUG2 S3).

baseline BD-276: where 가 이미 없어진 함수(step_facts · step_drafts …)를 가리키고 있었다. 글자로 적힌 이름은 코드가
바뀌어도 안 바뀐다 -- 그래서 기계가 매번 찾아본다. 이름은 ast 로 찾는다(grep 이 아니다: 주석 · 문자열 속 이름은 안 맞는다).

    '<file>::<qualname>'          이 저장소의 파일
    'se_new:<file>::<qualname>'   se_new.lock 의 커밋에서 (git show 로 그 커밋의 파일을 읽는다 -- 작업 디렉터리가 아니다)
    'external:<name>'             우리 코드가 아니다(Gemini CLI · ga-sdk)

se_new 저장소는 WUG_SE_NEW_REPO · ~/.cache/well_used_gemini/se_new-<커밋12> · 옆 폴더 ../se_new 순으로 찾는다.
못 찾으면 **실패**다 -- 확인 못 한 것은 확인된 것이 아니다.

    python3 tests/test_steps_where.py
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = []


def ok(cond, label):
    print(f"    {'OK  ' if cond else '실패'} {label}")
    if not cond:
        fails.append(label)


def has_qualname(source: str, qual: str) -> bool:
    """'a.b.c' -- 맨 위의 def/class a 안에서 b, 그 안에서 c (중첩 함수 · 메서드)."""
    nodes = ast.parse(source).body
    found = None
    for part in qual.split("."):
        cands = [n for n in _children(nodes) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                 and n.name == part]
        if not cands:
            return False
        found = cands[0]
        nodes = found.body
    return found is not None


def _children(body):
    """한 몸통 안의 정의들 -- if/try/for 안에 든 것까지(함수 몸통 안 중첩 정의는 다음 단계에서 본다)."""
    out = []
    stack = list(body)
    while stack:
        n = stack.pop(0)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(n)
        elif hasattr(n, "body") and isinstance(getattr(n, "body"), list):
            stack.extend(n.body)
            stack.extend(getattr(n, "orelse", []) or [])
            stack.extend(getattr(n, "finalbody", []) or [])
            for h in getattr(n, "handlers", []) or []:
                stack.extend(h.body)
    return out


def se_new_repo(commit: str) -> "Path | None":
    home = Path(os.environ.get("WUG_HOME") or Path.home() / ".cache" / "well_used_gemini")
    for c in (os.environ.get("WUG_SE_NEW_REPO"), home / f"se_new-{commit[:12]}", ROOT.parent / "se_new"):
        if not c:
            continue
        c = Path(c)
        if (c / ".git").exists() and subprocess.run(["git", "-C", str(c), "cat-file", "-e", f"{commit}^{{commit}}"],
                                                    capture_output=True).returncode == 0:
            return c
    return None


def resolve(ref: str, se_repo, commit: str) -> "tuple[bool, str]":
    if ref.startswith("external:"):
        return bool(ref[len("external:"):].strip()), "external"
    if "::" not in ref:
        return False, "꼴이 틀렸다('<file>::<qualname>' 이 아니다)"
    path, qual = ref.rsplit("::", 1)
    if path.startswith("se_new:"):
        if se_repo is None:
            return False, "se_new 저장소를 못 찾아 확인 못 함"
        r = subprocess.run(["git", "-C", str(se_repo), "show", f"{commit}:{path[len('se_new:'):]}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return False, f"se_new@{commit[:7]} 에 파일이 없다"
        src = r.stdout
    else:
        p = ROOT / path
        if not p.is_file():
            return False, "파일이 없다"
        src = p.read_text(encoding="utf-8")
    return (True, "") if has_qualname(src, qual) else (False, f"{qual} 이 없다")


commit = json.loads((ROOT / "se_new.lock").read_text())["commit"]
se_repo = se_new_repo(commit)

print("[자기 점검] 찾는 장치가 없는 것을 '없다' 고 하는가 -- 늘 초록인 검사는 검사가 아니다")
src = "def a():\n    def b():\n        pass\nclass C:\n    def m(self):\n        pass\nif True:\n    def d():\n        pass\n"
ok(has_qualname(src, "a") and has_qualname(src, "a.b") and has_qualname(src, "C.m") and has_qualname(src, "d"),
   "있는 것: a · a.b · C.m · if 안의 d")
ok(not has_qualname(src, "b") and not has_qualname(src, "a.c") and not has_qualname(src, "C.x")
   and not has_qualname("# def step_facts\nx = 'def step_facts'\n", "step_facts"),
   "없는 것: 맨 위의 b · a.c · C.x · 주석/문자열 속 이름")
ok(not resolve("wug_essay.py::step_facts", se_repo, commit)[0], "BD-276 이 짚은 옛 이름 step_facts 는 없다고 나온다")
ok(not resolve("wug_essay.py step_facts", se_repo, commit)[0], "옛 꼴(빈칸으로 가른 글)은 거절")

print("[S3] steps.json 의 where 마다 -- 그 함수가 지금 있다")
st = json.loads((ROOT / "steps.json").read_text())
ok(se_repo is not None, f"se_new@{commit[:7]} 를 찾았다 ({se_repo})")
bad = []
n = 0
for s in st["steps"]:
    w = s.get("where")
    if not isinstance(w, list) or not w:
        bad.append(f"{s['id']}: where 가 목록이 아니다")
        continue
    for ref in w:
        n += 1
        good, why = resolve(ref, se_repo, commit)
        if not good:
            bad.append(f"{s['id']}: {ref} -- {why}")
ok(not bad, f"걸음 {len(st['steps'])}개 · 참조 {n}개가 다 있다" + (f" -- 없는 것 {bad}" if bad else ""))

print()
if fails:
    print(f"steps where: {len(fails)}개 실패 -- {fails}")
    sys.exit(1)
print("steps where: 모든 where 가 지금 있는 함수를 가리킨다 -- 통과")

"""well_used_gemini 시험 -- 진입점(wug.py) · Gemini CLI 훅 둘 · MCP 서버.

가짜 상류(se_new 자리)를 tmp 에 git 저장소로 **지어서** wug.py 를 끝까지 돌린다(이 저장소가 배운 것: 셸·진입점은 글자를
검사하지 말고 실제로 돌려 본다). 망 · pip · 진짜 se_new 는 안 쓴다(WUG_SKIP_PIP=1).

    python3 tests/test_wug.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hooks"))

fails = []


def ok(cond, label):
    print(f"    {'OK  ' if cond else '실패'} {label}")
    if not cond:
        fails.append(label)


def sh(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


FAKE_RUN = '''import os, sys
key = "있음" if os.environ.get("GEMINI_API_KEY") else "없음"
print("FAKE agentic.run v=%s q=%s key=%s" % (open("VERSION").read().strip(), sys.argv[1], key))
sys.exit(3 if sys.argv[1] == "fail" else 0)
'''

with tempfile.TemporaryDirectory() as tmp:
    T = Path(tmp)
    up = T / "upstream"
    (up / "agentic").mkdir(parents=True)
    sh("git", "init", "-q", "-b", "main", str(up))
    sh("git", "-C", str(up), "config", "user.email", "t@t")
    sh("git", "-C", str(up), "config", "user.name", "t")
    (up / "agentic" / "__init__.py").write_text("")
    (up / "agentic" / "run.py").write_text(FAKE_RUN)
    (up / "VERSION").write_text("1")
    (up / "agentic" / "tool_registry.json").write_text(json.dumps({"head_sha": "f" * 40, "rejected": {"x": ["no_probe"]},
        "tools": {"concept": {"kind": "compute", "declaration": {"description": "Look up a concept",
                  "parameters": {"properties": {"name": {"type": "STRING"}}}}}}}))
    sh("git", "-C", str(up), "add", "-A")
    sh("git", "-C", str(up), "commit", "-qm", "c1")
    c1 = sh("git", "-C", str(up), "rev-parse", "HEAD")
    (up / "VERSION").write_text("2")
    sh("git", "-C", str(up), "commit", "-qam", "c2")
    c2 = sh("git", "-C", str(up), "rev-parse", "HEAD")

    W = T / "wrapper"
    W.mkdir()
    shutil.copy(ROOT / "wug.py", W / "wug.py")
    shutil.copy(ROOT / "wug_inspect.py", W / "wug_inspect.py")
    shutil.copy(ROOT / "wug_media.py", W / "wug_media.py")
    shutil.copy(ROOT / "wug_model.py", W / "wug_model.py")
    (W / "requirements.txt").write_text("")

    def lock(commit):
        (W / "se_new.lock").write_text(json.dumps({"url": str(up), "commit": commit}))

    (T / "userhome").mkdir()
    env = {**os.environ, "WUG_HOME": str(T / "home"), "WUG_SKIP_PIP": "1", "HOME": str(T / "userhome"),
           "WUG_NO_GH_CLI": "1"}
    for k_ in ("GEMINI_API_KEY", "GITHUB_TOKEN"):
        env.pop(k_, None)

    def wug(*args, extra=None, stdin=None):
        p = subprocess.run([sys.executable, str(W / "wug.py"), *args], cwd=W, env={**env, **(extra or {})},
                           capture_output=True, text=True, input=stdin)
        return p.returncode, p.stdout + p.stderr

    print("[setup] 고정 커밋을 받는다 -- 상류 main 이 앞서 있어도")
    lock(c1)
    code, out = wug("run", "q")
    ok(code == 1 and "아직 setup 을 안 했다" in out, "setup 전 run 은 이유를 말하고 1")
    code, out = wug("setup")
    co1 = T / "home" / f"se_new-{c1[:12]}"
    ok(code == 0 and sh("git", "-C", str(co1), "rev-parse", "HEAD") == c1, f"체크아웃이 c1 (main 은 c2) ({out.strip()[-80:]})")
    code, out = wug("setup")
    ok(code == 0, "두 번째 setup 도 0 (다시 안 받는다)")

    print("[run] 물음 · 끝값 · 키")
    code, out = wug("run", "안녕", "세상")
    ok(code == 0 and "FAKE agentic.run v=1 q=안녕 세상 key=없음" in out, "물음을 넘기고 고정 커밋의 코드가 돈다(v=1)")
    code, out = wug("inspect", "tools")
    ok(code == 0 and "등록 1개 · 거절 1개" in out and "- concept [compute] (name) Look up a concept" in out,
       f"inspect tools 가 체크아웃의 등록부를 읽는다 ({out.strip()[-120:]})")
    code, out = wug("inspect", "report", "../../etc")
    ok(code == 2 and "꼴이 틀렸다" in out, "report 의 run_id 로 경로를 못 빠져나간다")
    code, out = wug("media", "frob", "{}")
    ok(code == 2, "media 는 setup 의 가상환경에서 돈다(모르는 하위 명령은 2)")
    code, out = wug("run", "fail")
    ok(code == 3, "끝값을 그대로 돌려준다(3)")
    secret = "AIza" + "SyTESTONLY" * 3
    (W / ".env").write_text(f"GEMINI_API_KEY={secret}\nOTHER_SECRET=nope\n")
    code, out = wug("run", "q")
    ok("key=있음" in out and secret not in out, ".env 의 키는 자식에 넘어가고 화면에는 값이 없다")
    (W / ".env").unlink()

    print("[키] 설치 때 묻지 않는다 -- 한 번 저장하면 재설치해도 남는다")
    code, out = wug("key", "gemini", stdin=secret + "\n")
    kf = T / "home" / "keys.env"
    ok(code == 0 and kf.is_file() and secret not in out, "wug key 가 WUG_HOME/keys.env 에 쓰고 값은 안 찍는다")
    ok(oct(kf.stat().st_mode & 0o777) == "0o600", f"keys.env 권한 600 ({oct(kf.stat().st_mode & 0o777)})")
    code, out = wug("key", "gemini", stdin=secret[:-1] + "Z\n")
    ok(kf.read_text().count("GEMINI_API_KEY=") == 1 and secret[:-1] + "Z" in kf.read_text(), "다시 저장하면 옛 줄을 바꾼다(두 줄이 안 된다)")
    code, out = wug("key", "#", "마지막으로", "(화면에", "안", "보임)", stdin=secret + "\n")
    ok(code == 0 and f"GEMINI_API_KEY={secret}" in kf.read_text(),
       "zsh 가 넘긴 '# 설명' 낱말은 버리고 gemini 키로 받는다")
    code, out = wug("key", "gemini", stdin="\n")
    ok(code == 2, "빈 값은 안 쓴다")
    ok(not str(kf).startswith(str(W)), "keys.env 는 확장 폴더 밖이다(재설치가 지우는 자리가 아니다)")
    code, out = wug("run", "q")
    ok("key=있음" in out, "저장한 키를 run 의 자식이 받는다")
    kf.unlink()
    (T / "userhome" / ".gemini").mkdir()
    (T / "userhome" / ".gemini" / ".env").write_text(f"GEMINI_API_KEY={secret}\nOTHER=x\n")
    code, out = wug("run", "q")
    ok("key=있음" in out, "~/.gemini/.env 의 키를 그대로 쓴다(Gemini CLI 가 읽는 그 파일)")
    (T / "userhome" / ".gemini" / ".env").unlink()
    code, out = wug("run", "q")
    ok("key=없음" in out, "어디에도 없으면 없음")

    print("[격리] 받아 온 se_new 를 덮어쓰지 않는다")
    (co1 / "agentic" / "run.py").write_text("print('누가 손댔다')\n")
    code, out = wug("setup")
    ok(code == 1 and "커밋 안 된 변경" in out and "누가 손댔다" in (co1 / "agentic" / "run.py").read_text(),
       "더러운 체크아웃이면 setup 이 멈추고 파일은 그대로")
    sh("git", "-C", str(co1), "checkout", "--", "agentic/run.py")

    print("[올리기] lock 을 바꾸면 새 커밋을 새 자리에")
    lock(c2)
    code, out = wug("run", "q")
    ok(code == 1 and "setup" in out, "lock 이 바뀌면 setup 전까지 안 돈다")
    code, out = wug("setup")
    co2 = T / "home" / f"se_new-{c2[:12]}"
    ok(code == 0 and sh("git", "-C", str(co2), "rev-parse", "HEAD") == c2 and co1.exists(), "새 자리 · 옛 자리는 그대로")
    code, out = wug("run", "q")
    ok("v=2" in out, "이제 c2 의 코드가 돈다")
    (W / "se_new.lock").write_text('{"url": "x", "commit": "short"}')
    code, out = wug("setup")
    ok(code == 1 and "se_new.lock" in out, "lock 꼴이 틀리면 1")
    code, out = wug("frobnicate")
    ok(code == 2, "모르는 명령은 2")

print("[파이썬] 3.10 미만이면 더 새 파이썬을 찾아 갈아탄다 (macOS 기본 python3 = 3.9)")
import wug as W  # noqa: E402
_which, _dirs = W.shutil.which, W.SEARCH_DIRS
try:
    W.shutil.which = lambda n: "/x/python3.12" if n == "python3.12" else None
    ok(W.find_python() == "/x/python3.12", "PATH 의 python3.12 를 찾는다(3.13 이 없으면)")
    W.shutil.which = lambda n: None
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "python3.11"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        W.SEARCH_DIRS = (d,)
        ok(W.find_python() == str(fake), "PATH 에 없으면 Homebrew 자리(/opt/homebrew/bin 등)에서 찾는다")
        W.SEARCH_DIRS = ()
        ok(W.find_python() is None, "아무 데도 없으면 None -- 그때 setup 은 brew 명령을 알려 주고 멈춘다")
finally:
    W.shutil.which, W.SEARCH_DIRS = _which, _dirs
if sys.version_info >= W.MIN_PY:      # 3.9 에서 부르면 정말로 갈아탄다(그것이 맞는 동작이다) -- 그래서 여기서만 본다
    ok(W.reexec_newer("x", []) is None, "3.10 이상이면 갈아타지 않고 돌아온다")
ok("int.bit_count" in Path(W.__file__).read_text(), "3.10 이 필요한 까닭(int.bit_count)이 코드에 적혀 있다")

print("[훅] AfterAgent 깃발 게이트")
import flag_gate  # noqa: E402
fake_scan = lambda t: [("flag", "NO_LOOP_DETECTED")] if "NO_LOOP" in t else []
ok(flag_gate.decide({"prompt_response": "Log: NO_LOOP_DETECTED", "stop_hook_active": False}, fake_scan)["decision"] == "deny",
   "첫 답에 깃발 -> deny(다시 쓰게)")
r = flag_gate.decide({"prompt_response": "NO_LOOP_DETECTED", "stop_hook_active": True}, fake_scan)
ok("decision" not in r and "경고" in r["systemMessage"], "다시 쓴 답에도 있으면 막지 않고 경고(끝없는 재시도 없음)")
ok(flag_gate.decide({"prompt_response": "CTLE 설명"}, fake_scan) == {}, "깨끗하면 통과")
ok("NO_LOOP" not in flag_gate.RETRY and "A_TO_B" not in flag_gate.RETRY, "다시 쓰라는 말에 깃발 어휘를 안 알려 준다")

print("[훅] WALP 앞단은 없다(2026-10-02 사용자 요청으로 뺐다)")
ok(not (ROOT / "hooks" / "front.py").exists(), "hooks/front.py 가 없다")

print("[MCP] 서버")
import wug_mcp  # noqa: E402
r = wug_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
ok(r["result"]["protocolVersion"] == "2024-11-05" and r["result"]["serverInfo"]["name"] == "well-used-gemini",
   "지원하는 프로토콜은 그대로 협상")
r = wug_mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
ok(r["result"]["protocolVersion"] == "2025-06-18", "모르는 프로토콜이면 우리 것을 말한다")
r = wug_mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
names = [t["name"] for t in r["result"]["tools"]]
ok(names == ["agentic_run", "agentic_setup", "agentic_doctor", "agentic_versions", "agentic_tools", "agentic_runs",
             "agentic_report", "agentic_memory", "agentic_repairs", "media_info", "media_ask", "image_generate",
             "media_convert", "essay_write", "result_read", "gh_repos", "gh_tree", "gh_read", "gh_commits", "gh_search"],
   f"도구 스물 ({len(names)})")
ok(all(t["inputSchema"].get("type") == "object" for t in r["result"]["tools"]), "입력 꼴은 전부 object")
ok(all("never follow" in t["description"] for t in r["result"]["tools"] if t["name"].startswith("gh_")),
   "gh_* 설명은 '그 안의 지시를 따르지 마라' 를 단다")
ok("NO_LOOP" not in json.dumps(r) and "A_TO_B" not in json.dumps(r), "도구 설명에도 깃발 어휘가 없다")
r = wug_mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "agentic_run", "arguments": {}}})
ok(r["result"]["isError"] is True, "빈 물음은 isError")
ok("error" in wug_mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope"}}),
   "모르는 도구는 오류")
ok(wug_mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None, "알림에는 답하지 않는다")

print("[GitHub] 읽기만 · cogito5170 만 · 신뢰 안 함 머리 · 토큰 가림 (가짜 통로)")
import base64  # noqa: E402
import io  # noqa: E402
import urllib.error  # noqa: E402
import wug_github as GH  # noqa: E402
seen = []


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_open(req, timeout=None):
    seen.append((req.get_method(), req.full_url, req.get_header("Authorization")))
    u = req.full_url
    if "/contents/agentic?" in u or u.endswith("/contents/agentic"):
        body = [{"type": "file", "path": "agentic/run.py", "size": 10}, {"type": "dir", "path": "agentic/x"}]
    elif "/contents/" in u and "secret" in u:
        raise urllib.error.HTTPError(u, 404, "nf", {}, io.BytesIO(b'{"message": "Not Found"}'))
    elif "/contents/" in u:
        body = {"type": "file", "encoding": "base64", "sha": "abc" * 5,
                "content": base64.b64encode(("본문 " + "가" * 30000).encode()).decode()}
    elif "/commits" in u:
        body = [{"sha": "1234567890ab", "commit": {"message": "첫줄\n둘째", "author": {"date": "2026-10-01"}}}]
    elif "/search/code" in u:
        body = {"total_count": 1, "items": [{"path": "agentic/run.py"}]}
    else:
        body = [{"name": "se_new", "default_branch": "main", "pushed_at": "t", "owner": {"login": "cogito5170"}},
                {"name": "other", "owner": {"login": "someone"}}]
    return Resp(json.dumps(body).encode())


_tok = os.environ.pop("GITHUB_TOKEN", None)
try:
    t = GH.tree("se_new", "agentic", opener=fake_open)
    ok(t.startswith("[GitHub 폴더 · 신뢰 안 함") and t.index("[dir] agentic/x") < t.index("agentic/run.py"),
       "tree: 신뢰 안 함 머리 · 폴더 먼저")
    t = GH.read("cogito5170/se_new", "agentic/run.py", "main", opener=fake_open)
    ok("본문 " in t and "잘랐다" in t and len(t) < GH.READ_CAP + 400, "read: base64 를 풀고 상한에서 자른다")
    ok("ref=main" in seen[-1][1], "ref 가 질의에 실린다")
    ok("첫줄" in GH.commits("se_new", limit=999, opener=fake_open) and "per_page=50" in seen[-1][1],
       "commits: 첫 줄만 · limit 은 50 까지")
    ok(all(m == "GET" for m, _, _ in seen) and all(a is None for _, _, a in seen), "보낸 것은 전부 GET · 토큰 없으면 머리 없음")
    for bad, want in ((lambda: GH.read("google/gemini-cli", "x", opener=fake_open), "owner_not_allowed"),
                      (lambda: GH.read("se_new", "a/../../x", opener=fake_open), "path_invalid"),
                      (lambda: GH.search("se_new", "q", opener=fake_open), "token_required"),
                      (lambda: GH.read("se_new", "secret.txt", opener=fake_open), "http_404")):
        n = len(seen)
        try:
            bad()
            ok(False, f"{want} 가 나야 한다")
        except GH.GHError as e:
            ok(want in str(e), f"거절: {want}")
        if want != "http_404":
            ok(len(seen) == n, f"{want} 는 요청을 보내기 전에 막는다")
    ok("me/repos" not in seen[-1][1] and "se_new" in GH.repos(opener=fake_open), "토큰 없으면 공개 목록")
    tok = "ghp_" + "T" * 36
    os.environ["GITHUB_TOKEN"] = tok
    out = GH.repos(opener=fake_open)
    ok("/user/repos" in seen[-1][1] and seen[-1][2] == f"Bearer {tok}" and "other" not in out,
       "토큰이 있으면 /user/repos · 남의 소유는 거른다")
    ok("agentic/run.py" in GH.search("se_new", "def run", opener=fake_open) and "repo%3Acogito5170/se_new" in seen[-1][1],
       "search 는 그 저장소로 좁힌다")
    try:
        GH.read("se_new", "secret.txt", opener=lambda r, timeout=None: (_ for _ in ()).throw(
            urllib.error.HTTPError(r.full_url, 401, "x", {}, io.BytesIO(json.dumps({"message": "bad " + tok}).encode()))))
    except GH.GHError as e:
        ok(tok not in str(e) and "토큰 가림" in str(e), "오류 글에 토큰이 안 실린다")
    real = GH.urllib.request.urlopen
    GH.urllib.request.urlopen = fake_open
    try:
        r = wug_mcp.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                            "params": {"name": "gh_read", "arguments": {"repo": "se_new", "path": "agentic/run.py"}}})
        ok(r["result"]["isError"] is False and "본문" in r["result"]["content"][0]["text"], "MCP gh_read 가 끝까지 돈다")
        r = wug_mcp.handle({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                            "params": {"name": "gh_tree", "arguments": {"repo": "torvalds/linux"}}})
        ok(r["result"]["isError"] is True and "owner_not_allowed" in r["result"]["content"][0]["text"],
           "MCP 로도 남의 저장소는 거절(isError)")
    finally:
        GH.urllib.request.urlopen = real
finally:
    os.environ.pop("GITHUB_TOKEN", None)
    if _tok is not None:
        os.environ["GITHUB_TOKEN"] = _tok

print("[모델] wug.py model -- API 로 있는지 확인한 뒤에만 settings.json 의 model.name 하나를 바꾼다")
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402


class _M(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        name = self.path.split("/models/", 1)[1]
        if self.headers.get("x-goog-api-key") != "AIzaMODELTEST":
            code, body = 403, {"error": {"message": "bad key"}}
        elif name == "gemini-3-flash-preview":
            code, body = 200, {"name": "models/gemini-3-flash-preview", "displayName": "Gemini 3 Flash Preview",
                               "inputTokenLimit": 1048576, "supportedGenerationMethods": ["generateContent"]}
        elif name == "embed-x":
            code, body = 200, {"name": "models/embed-x", "supportedGenerationMethods": ["embedContent"]}
        else:
            code, body = 404, {"error": {"message": "not found"}}
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


_srv = HTTPServer(("127.0.0.1", 0), _M)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory() as tmp:
    H = Path(tmp)
    (H / ".gemini").mkdir()
    sp = H / ".gemini" / "settings.json"
    sp.write_text(json.dumps({"model": {"name": "auto", "maxSessionTurns": 5}, "ui": {"theme": "x"}}))
    base = {**os.environ, "HOME": str(H), "WUG_HOME": str(H / "wh"), "WUG_NO_GH_CLI": "1",
            "WUG_GEMINI_API": f"http://127.0.0.1:{_srv.server_port}/v1beta", "NO_PROXY": "127.0.0.1",
            "no_proxy": "127.0.0.1"}
    for k_ in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        base.pop(k_, None)

    def m(*a, key=True):
        p = subprocess.run([sys.executable, str(ROOT / "wug.py"), "model", *a], capture_output=True, text=True,
                           env={**base, **({"GEMINI_API_KEY": "AIzaMODELTEST"} if key else {})}, timeout=60)
        return p.returncode, p.stdout + p.stderr
    before = sp.read_text()
    code, out = m("gemini-3-flash-preview", key=False)
    ok(code == 1 and sp.read_text() == before and "키가 없어" in out, "키가 없으면 확인 못 함 -> 안 쓴다")
    code, out = m("gemini-3-flash-previe")
    ok(code == 1 and sp.read_text() == before and "404" in out, "API 가 모르는 이름(오타)은 안 쓴다")
    code, out = m("embed-x")
    ok(code == 1 and sp.read_text() == before, "generateContent 를 안 받는 모델은 안 쓴다")
    code, out = m("gemini-3-flash-preview")
    d = json.loads(sp.read_text())
    one = [{"model": "gemini-3-flash-preview", "isLastResort": True}]
    ok(code == 0 and d["model"] == {"name": "gemini-3-flash-preview", "maxSessionTurns": 5} and d["ui"] == {"theme": "x"},
       f"model.name 을 바꾸고 다른 칸은 그대로 ({d})")
    ok(d["experimental"] == {"dynamicModelConfiguration": True}
       and d["modelConfigs"]["modelChains"] == {k: one for k in ("preview", "default", "auto-preview", "auto-default")},
       "폴백 사슬을 이 모델 하나로 묶는다(Gemini CLI 0.62.0 은 3-flash-preview 가 막히면 3.1-pro-preview 를 내민다)")
    ok(d.get("telemetry") == {"enabled": True, "target": "local", "outfile": os.devnull, "logPrompts": False},
       "힙 고침: 텔레메트리를 켜되 파일은 버리고 프롬프트는 안 적는다(0.62.0 의 telemetryBuffer 가 비워진다)")
    baks = list((H / ".gemini").glob("settings.json.bak-*"))
    ok(len(baks) == 1 and json.loads(baks[0].read_text())["model"]["name"] == "auto", "옛 설정을 .bak 으로 남긴다")
    code, out = m()
    ok(code == 0 and "gemini-3-flash-preview" in out and "있음" in out, "인자 없이 부르면 지금 값과 API 확인을 보인다")
    sp.write_text(json.dumps({"telemetry": {"enabled": True, "target": "gcp", "logPrompts": True}}))
    code, out = m("gemini-3-flash-preview")
    ok(json.loads(sp.read_text())["telemetry"] == {"enabled": True, "target": "gcp", "logPrompts": True},
       "이미 켜 둔 사용자의 텔레메트리 설정은 안 건드린다")
    sp.write_text('{\n  // 주석\n  "ui": {}\n}\n')
    code, out = m("gemini-3-flash-preview")
    ok(code == 1 and "// 주석" in sp.read_text() and "덮어쓰지 않는다" in out, "주석이 든 settings.json 은 안 건드린다")
    sp.unlink()
    code, out = m("gemini-3-flash-preview")
    ok(code == 0 and json.loads(sp.read_text())["model"] == {"name": "gemini-3-flash-preview"}, "파일이 없으면 새로 만든다")
_srv.shutdown()

print("[모델] 하나 · 폴백 없음")
import wug_model as WMD  # noqa: E402
ok(WMD.MODEL == "gemini-3-flash-preview" and WMD.CLI_VERSION == "0.62.0", "사용자 결정: gemini-3-flash-preview · Gemini CLI 0.62.0")
import wug_media as WMED  # noqa: E402
import wug_essay as WESS  # noqa: E402
ok(WMED.pick_image_model(lambda: [{"name": "models/other-image"}]) == WMD.MODEL and WESS.MODEL == WMD.MODEL,
   "묻기 · 그림 · 글쓰기가 같은 모델(목록을 보고 다른 것을 고르지 않는다)")
_srcs = "".join((ROOT / f).read_text() for f in ("wug_media.py", "wug_essay.py", "wug_bench.py", "wug.py", "wug_mcp.py"))
ok("flash-lite" not in _srcs and "WUG_ESSAY_MODEL" not in _srcs and "WUG_ASK_MODEL" not in _srcs
   and "WUG_BENCH_BIG" not in _srcs, "다른 모델 이름 · 모델을 바꾸는 환경 변수가 코드에 없다")

print("[한도] agentic_run 의 BLOCKED(quota_wait) 는 실패가 아니라 quota wait 로 (CMD-WUG1 S7)")
_ow = wug_mcp._wug
try:
    wug_mcp._wug = lambda *a, **k: (1, "상태: BLOCKED (quota_wait:minute:37) -- 모델 호출을 진행할 수 없다")
    t, e = wug_mcp.call("agentic_run", {"question": "q"})
    ok(not e and t.startswith("quota wait 37 s"), f"분당 -> quota wait 37 s · isError 아님 ({t[:40]})")
    wug_mcp._wug = lambda *a, **k: (1, "상태: BLOCKED (quota_wait:day:0)")
    t, e = wug_mcp.call("agentic_run", {"question": "q"})
    ok(not e and "다음 날" in t, "하루 -> 다음 날까지")
    wug_mcp._wug = lambda *a, **k: (1, "상태: BLOCKED (model_unavailable)")
    t, e = wug_mcp.call("agentic_run", {"question": "q"})
    ok(e and not t.startswith("quota wait"), "다른 BLOCKED 는 그대로 오류")
finally:
    wug_mcp._wug = _ow

print("[결과 상한] 긴 도구 결과는 앞부분 + result_id, 전체는 디스크 (CMD-WUG1 S3)")
with tempfile.TemporaryDirectory() as _rt:
    import wug as _wug_mod
    _old_home = _wug_mod.WUG_HOME
    _wug_mod.WUG_HOME = Path(_rt)
    try:
        long = "".join(f"{i:05d}|" for i in range(3000))          # 18000 자
        out = wug_mcp.cap_result(long)
        # 단언이 먼저다 -- 자르지 않는 변이(tests/mutants.py M4)가 꼬리말 파싱에서 터지지 않고 이 줄에서 빨개지게
        ok(len(out) < wug_mcp.RESULT_CAP + 200, f"긴 결과는 상한 {wug_mcp.RESULT_CAP} 자 + 꼬리말로 잘린다 ({len(out)})")
        rid = out.rsplit("result_id ", 1)[1].split(" ")[0] if "result_id " in out else ""
        ok(out.startswith(long[:wug_mcp.RESULT_CAP]) and len(rid) == 16, f"앞부분 그대로 + result_id ({rid!r})")
        ok(wug_mcp.cap_result("짧다") == "짧다", "짧은 결과는 그대로")
        got, off = "", wug_mcp.RESULT_CAP
        got = long[:off]
        while rid:
            t, e = wug_mcp.read_result(rid, off)
            assert not e, t
            body = t.split("\n", 1)[1].rsplit("\n", 1)[0]
            got += body
            if t.endswith("[끝]"):
                break
            off = int(t.rsplit("offset=", 1)[1].rstrip("]"))
        ok(got == long, "result_read 로 이어 읽으면 원문 그대로 다 나온다")
        ok(wug_mcp.read_result("../../etc/passwd")[1] and wug_mcp.read_result("f" * 16)[1], "id 꼴이 틀리거나 없으면 오류")
        r = wug_mcp.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                            "params": {"name": "result_read", "arguments": {"result_id": rid, "offset": 0, "length": 99999}}})
        ok(len(r["result"]["content"][0]["text"]) <= wug_mcp.RESULT_CAP + 120, "result_read 자체도 상한을 넘지 않는다")
        t, _ = wug_mcp.read_result(rid, 0, 99999)
        ok(len(t) <= wug_mcp.RESULT_CAP + 120, "read_result 도 한 번에 상한까지만(바깥 상한에 기대지 않는다)")
        _orig = wug_mcp.call
        wug_mcp.call = lambda n, a: ("y" * 50000, False)
        try:
            r = wug_mcp.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "gh_repos", "arguments": {}}})
        finally:
            wug_mcp.call = _orig
        ok(len(r["result"]["content"][0]["text"]) < wug_mcp.RESULT_CAP + 200, "모든 도구의 결과가 handle 에서 상한을 지난다")
    finally:
        _wug_mod.WUG_HOME = _old_home

print("[단계표] steps.json -- 빠진 단계가 없고 kind 는 model | tool 뿐 (CMD-WUG1 S5)")
_st = json.loads((ROOT / "steps.json").read_text())
_ids = [x["id"] for x in _st["steps"]]
ok(len(_ids) == len(set(_ids)) and all(x["kind"] in ("model", "tool") for x in _st["steps"]), "id 가 겹치지 않고 kind 는 닫혀 있다")
ok(all(f"mcp.{t['name']}" in _ids for t in wug_mcp.TOOLS), "MCP 도구마다 한 줄")
ok(all(f"essay.{n}" in _ids for n in ("facts", "roles", "thesis", "points_clean", "draft", "gate", "select", "revise", "report")),
   "글쓰기 단계마다 한 줄")
ok(_st["model"] == WMD.MODEL, "단계표의 모델 = wug_model.MODEL")
ok(all((x["model_calls"] == 0) == (x["kind"] == "tool") for x in _st["steps"] if isinstance(x["model_calls"], int)),
   "tool 은 모델 호출 0, model 은 1 이상")

print("[확장] 매니페스트 · 훅 파일 꼴 (Gemini CLI 0.46.0 문서 · 로더 기준)")
m = json.loads((ROOT / "gemini-extension.json").read_text())
ok(m["name"] == "well-used-gemini" and m["contextFileName"] == "GEMINI.md", "이름(소문자·대시) · 컨텍스트 파일")
ok("settings" not in m, "설치 때 키를 묻지 않는다(settings 없음) -- 키는 wug key · ~/.gemini/.env 에서")
h = json.loads((ROOT / "hooks" / "hooks.json").read_text())
ok(isinstance(h.get("hooks"), dict) and set(h["hooks"]) == {"AfterAgent"}, "hooks.json 최상위는 hooks 객체")
g = (ROOT / "GEMINI.md").read_text()
ok("NO_LOOP" not in g and "A_TO_B" not in g and "RED_RED" not in g, "GEMINI.md 에 깃발 어휘가 없다(알려 주면 흉내 낸다)")

print()
if fails:
    print(f"well_used_gemini: {len(fails)}개 실패 -- {fails}")
    sys.exit(1)
print("well_used_gemini: 고정 커밋 · run · inspect · 키 · 격리 · 올리기 · 훅 둘 · MCP · GitHub · 확장 꼴 -- 통과")

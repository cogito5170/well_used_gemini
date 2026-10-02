#!/usr/bin/env python3
"""well_used_gemini -- Gemini 를 정책 게이트 뒤에서 돌리는 얇은 진입점.

실제 일은 `cogito5170/se_new` 의 `agentic/` 이 한다(WALP 앞단 · 제어부 · Gate01 · 사고부(ReAct) · 루프 탐지기 ·
sandbox 실행 · MCP · RAG). 여기는 그것을 **고정된 커밋으로** 받아 와서 부르기만 한다.

    python3 wug.py setup              se_new 를 se_new.lock 의 커밋으로 받고(~/.cache/well_used_gemini/), 가상환경에 requests
    python3 wug.py doctor             무엇이 준비됐고 무엇이 안 됐는지 -- 키 없이도 도는 점검을 실제로 돌린다
    python3 wug.py run "물음"          agentic.run 을 부른다. 끝값: 0 = DONE, 그 밖 = 그 상태
    python3 wug.py versions           고정 커밋 · 설정 모델 · MCP 버전 셋(서버가 말한 것)
    python3 wug.py key [gemini|github]  키를 한 번 저장한다(WUG_HOME/keys.env · 권한 600 · 재설치해도 남는다)
    python3 wug.py media info|ask|generate|convert '<JSON>'   사진·PDF 받기/내보내기(wug_media.py)
    python3 wug.py write [gemini 인자...]  Gemini CLI 를 글쓰기 모드로(writing/system.md 가 기본 지시문을 바꾼다)
    python3 wug.py bench spec.json [--runs 3] [--only abcd]   글쓰기 품질 차이를 원인별로 가르는 실험
    python3 wug.py inspect tools|runs [N]|report ID|memory 물음|repairs   agentic 상태를 읽기만(wug_inspect.py)

규칙(se_new 의 CLAUDE.md 에서 온 것):
  · **고정 커밋만 쓴다.** se_new 의 main 이 움직여도 여기는 se_new.lock 이 바뀔 때만 바뀐다 -- 남이 받아 가는 것이
    검사한 것과 같아야 한다. 올리려면 se_new.lock 을 고치는 커밋을 낸다
  · **받아 온 se_new 를 고치지 않는다.** 그 안에 커밋 안 된 변경이 있으면 setup 이 멈춘다(덮어쓰지 않는다)
  · **키는 화면에 안 찍는다.** 있다/없다만. 자식 프로세스에는 환경 변수로만 넘긴다
  · **모르는 것은 안 된 것으로 다룬다.** 점검이 못 돈 것을 통과로 세지 않는다
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = HERE / "se_new.lock"
ENV_FILE = HERE / ".env"
# 받아 온 se_new 와 가상환경은 **이 폴더 밖에** 둔다. Gemini CLI 는 확장을 설치할 때 사본을 만들고 update 때
# 갈아 끼우므로, 확장 폴더 안에 두면 업데이트마다 사라진다. 체크아웃은 고정 커밋마다 따로다.
WUG_HOME = Path(os.environ.get("WUG_HOME") or (Path.home() / ".cache" / "well_used_gemini"))
VENV = WUG_HOME / "venv"


def checkout_dir(commit: str) -> Path:
    return WUG_HOME / f"se_new-{commit[:12]}"
KEY_NAMES = ("GEMINI_API_KEY", "GEMINI_API_KEY_FALLBACK") + tuple(f"GEMINI_API_KEY_FALLBACK{i}" for i in range(2, 9))
WRAPPER_VERSION = "0.1"


def die(msg: str, code: int = 1) -> int:
    print(f"[wug] {msg}", file=sys.stderr)
    return code


def lock() -> dict:
    d = json.loads(LOCK.read_text(encoding="utf-8"))
    if not (isinstance(d.get("url"), str) and isinstance(d.get("commit"), str) and len(d["commit"]) == 40):
        raise ValueError("se_new.lock 꼴이 틀렸다: {url, commit(40자)}")
    return d


def git(*args, cwd=None, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


MIN_PY = (3, 10)   # se_new 의 walp 가 int.bit_count() 를 쓴다(3.10 부터). 3.9 에서는 WALP 앞단이 AttributeError 로 꺼진다(실측)
CANDIDATES = ("python3.13", "python3.12", "python3.11", "python3.10")
SEARCH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")   # macOS Homebrew(Apple 칩 · 인텔) · 리눅스


def find_python() -> "str | None":
    """3.10 이상 파이썬을 찾는다: PATH 의 python3.1x, 그다음 Homebrew 자리. 없으면 None."""
    for name in CANDIDATES:
        hit = shutil.which(name)
        if hit:
            return hit
    for d in SEARCH_DIRS:
        for name in CANDIDATES:
            p = Path(d) / name
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


def reexec_newer(script: str, argv: list) -> None:
    """지금 파이썬이 3.10 미만이면 더 새 파이썬으로 이 스크립트를 다시 띄운다(돌아오지 않는다).
    가상환경이 있으면 그것을 먼저 쓴다 -- setup 이 만든 것이라 3.10 이상이고 requests 도 있다.
    stdin/stdout 은 그대로 이어진다(Gemini CLI 의 훅 · MCP 통로가 끊기지 않는다)."""
    if sys.version_info >= MIN_PY or os.environ.get("WUG_REEXEC") == "1":
        return
    target = str(venv_python()) if venv_python().exists() else find_python()
    if not target:
        return
    os.environ["WUG_REEXEC"] = "1"            # 두 번 갈아타지 않는다(되돌이 방지)
    os.execv(target, [target, script, *argv])


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# 키를 어디서 읽나 -- **설치할 때 묻지 않는다.** 확장 설정(settings)은 재설치마다 다시 물어서 뺐다(2026-10-02 사용자).
#   1. 지금 환경 변수
#   2. KEY_FILE  -- `wug.py key` 가 한 번 써 둔 것. 확장 폴더 **밖**(WUG_HOME)이라 재설치해도 남는다
#   3. 확장 폴더의 .env (터미널에서 clone 해 쓰는 경우)
#   4. ~/.gemini/.env -- Gemini CLI 자체가 읽는 파일. 거기 GEMINI_API_KEY 를 둔 사람은 따로 할 일이 없다
#   (GitHub 토큰만) 5. `gh auth token` -- gh 로 로그인해 둔 사람
# 이 이름들 말고는 그 파일들에서 아무것도 안 읽는다.
KEY_FILE = WUG_HOME / "keys.env"
GH_NAMES = ("GITHUB_TOKEN",)


def env_files() -> list:
    return [KEY_FILE, ENV_FILE, Path.home() / ".gemini" / ".env"]


def read_env_file(path: Path, names=None) -> dict:
    names = names or (KEY_NAMES + GH_NAMES)
    out = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k in names and v and k not in out:
            out[k] = v
    return out


def _gh_cli_token() -> str:
    if os.environ.get("WUG_NO_GH_CLI") == "1" or not shutil.which("gh"):
        return ""
    try:
        p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def key_sources(env=None) -> dict:
    """{이름: 어디서 왔나} -- 값은 안 담는다. doctor 가 보인다."""
    src = {k: "환경 변수" for k in KEY_NAMES + GH_NAMES if (env if env is not None else os.environ).get(k)}
    for f in env_files():
        for k in read_env_file(f):
            src.setdefault(k, str(f))
    return src


def child_env() -> dict:
    """자식 환경: 지금 환경 + 위 파일들의 키(지금 환경에 없을 때만, 앞의 것이 이긴다)."""
    env = dict(os.environ)
    for f in env_files():
        for k, v in read_env_file(f).items():
            if not env.get(k):
                env[k] = v
    if not env.get("GITHUB_TOKEN"):
        t = _gh_cli_token()
        if t:
            env["GITHUB_TOKEN"] = t
    return env


def save_key(which: str, value: str) -> int:
    """KEY_FILE 에 한 줄 쓴다(같은 이름의 옛 줄은 바꾼다). 권한 600. 값은 화면에 안 찍는다."""
    name = {"gemini": "GEMINI_API_KEY", "github": "GITHUB_TOKEN"}.get(which)
    if not name:
        return die(f"모르는 키: {which} (gemini · github)", 2)
    value = value.strip()
    if not value or any(c.isspace() for c in value):
        return die("값이 비었거나 공백이 들어 있다 -- 안 썼다", 2)
    WUG_HOME.mkdir(parents=True, exist_ok=True)
    try:
        old = KEY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        old = []
    lines = [l for l in old if not l.strip().removeprefix("export ").strip().startswith(name + "=")]
    lines.append(f"{name}={value}")
    fd = os.open(str(KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(KEY_FILE, 0o600)
    print(f"[wug] {name} 를 {KEY_FILE} 에 저장했다(권한 600, 값은 안 찍는다). 재설치해도 남는다")
    return 0


def key_cmd(rest: list) -> int:
    cut = next((i for i, a in enumerate(rest) if a.startswith("#")), len(rest))
    rest = rest[:cut]                     # zsh 는 줄 끝의 '# 설명' 을 인자로 넘긴다 -- '#' 부터 끝까지 버린다
    which = (rest[0] if rest else "gemini").lower()
    if sys.stdin.isatty():
        import getpass
        value = getpass.getpass(f"{which} 키(입력이 화면에 안 보인다): ")
    else:
        value = sys.stdin.readline()
    return save_key(which, value)


def has_key(env: dict) -> bool:
    return any(env.get(k) for k in KEY_NAMES)


def setup(skip_pip: bool = False) -> int:
    try:
        lk = lock()
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return die(f"se_new.lock 을 못 읽었다: {e}")
    if shutil.which("git") is None:
        return die("git 이 없다")
    co = checkout_dir(lk["commit"])
    WUG_HOME.mkdir(parents=True, exist_ok=True)
    if sys.version_info < MIN_PY:
        return die(f"파이썬 3.10 이상이 필요하다(지금 {sys.version.split()[0]}, 3.10 이상을 못 찾았다).\n"
                   "      macOS: brew install python@3.12   그다음 같은 명령을 다시")
    if not (co / ".git").exists():
        print(f"[wug] se_new 를 받는다: {lk['url']} -> {co}")
        r = git("clone", "--quiet", lk["url"], str(co), check=False)
        if r.returncode != 0:
            return die(f"clone 실패: {r.stderr.strip()[-300:]}")
    dirty = git("status", "--porcelain", "--untracked-files=no", cwd=co).stdout.strip()
    if dirty:
        return die(f"{co.name}/ 에 커밋 안 된 변경이 있다 -- 덮어쓰지 않는다. 직접 보고 치워라:\n{dirty}")
    head = git("rev-parse", "HEAD", cwd=co, check=False).stdout.strip()
    if head != lk["commit"]:
        if git("cat-file", "-e", lk["commit"] + "^{commit}", cwd=co, check=False).returncode != 0:
            r = git("fetch", "--quiet", "origin", cwd=co, check=False)
            if r.returncode != 0:
                return die(f"fetch 실패: {r.stderr.strip()[-300:]}")
        r = git("-c", "advice.detachedHead=false", "checkout", "--quiet", lk["commit"], cwd=co, check=False)
        if r.returncode != 0:
            return die(f"고정 커밋으로 못 옮겼다: {r.stderr.strip()[-300:]}")
    head = git("rev-parse", "HEAD", cwd=co).stdout.strip()
    if head != lk["commit"]:
        return die(f"HEAD 가 고정 커밋이 아니다: {head} != {lk['commit']}")
    print(f"[wug] se_new 고정 커밋 {head[:12]}")
    if not venv_python().exists():
        print(f"[wug] {VENV.name}/ 를 만든다")
        venv.EnvBuilder(with_pip=not skip_pip).create(VENV)
    if not skip_pip:
        r = subprocess.run([str(venv_python()), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                            "-r", str(HERE / "requirements.txt")], capture_output=True, text=True)
        if r.returncode != 0:
            return die(f"pip 실패: {r.stderr.strip()[-400:]}")
    print("[wug] 준비 끝. 다음: python3 wug.py doctor")
    return 0


def _ready() -> "str | None":
    try:
        lk = lock()
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return f"se_new.lock: {e}"
    co = checkout_dir(lk["commit"])
    if not (co / ".git").exists():
        return "아직 setup 을 안 했다 -- python3 wug.py setup"
    head = git("rev-parse", "HEAD", cwd=co, check=False).stdout.strip()
    if head != lk["commit"]:
        return f"{co.name}/ 가 고정 커밋이 아니다({head[:12]} != {lk['commit'][:12]}) -- python3 wug.py setup"
    if not venv_python().exists():
        return "가상환경이 없다 -- python3 wug.py setup"
    return None


def co_now() -> Path:
    return checkout_dir(lock()["commit"])


def run(question: str) -> int:
    why = _ready()
    if why:
        return die(why)
    co = co_now()
    p = subprocess.run([str(venv_python()), "-m", "agentic.run", question], cwd=co, env=child_env())
    return p.returncode


def _check(label: str, argv: list, want_in: str = "", env=None) -> bool:
    co = co_now()
    try:
        p = subprocess.run(argv, cwd=co, env=env or child_env(), capture_output=True, text=True, timeout=600)
        ok = p.returncode == 0 and (want_in in p.stdout)
        lines = (p.stdout + p.stderr).strip().splitlines()
        # 실패면 **까닭이 적힌 줄**을 보인다 -- 첫 판은 마지막 줄('답: (채택된 답 없음)')만 보여 원인이 안 보였다
        why = ([l for l in lines if l.startswith(("상태:", "  작업", "  실패", "진단 로그:", "Traceback", "ModuleNotFound",
                                                     "ImportError"))] or lines[-1:] or [""])
    except (OSError, subprocess.TimeoutExpired) as e:
        ok, why = False, [f"{type(e).__name__} (600초 상한)"]
    print(f"  {'통과' if ok else '실패'}  {label}")
    if not ok:
        for l in why[:6]:
            print(f"        {l[:200]}")
    return ok


def doctor() -> int:
    print(f"[wug] well_used_gemini {WRAPPER_VERSION}")
    why = _ready()
    if why:
        print(f"  실패  준비: {why}")
        return 1
    lk = lock()
    env = child_env()
    print(f"  통과  se_new 고정 커밋 {lk['commit'][:12]}")
    src = key_sources()
    gk = next((src[k] for k in KEY_NAMES if k in src), None)
    print(f"  {'있음' if has_key(env) else '없음'}  Gemini 키 (값은 안 찍는다)"
          + (f" -- {gk}" if gk else "" if has_key(env) else
             " -- 없으면 모델이 필요한 물음은 BLOCKED(no_api_key). 한 번만: python3 wug.py key"))
    print(f"  {'있음' if env.get('GITHUB_TOKEN') else '없음'}  GitHub 토큰 (선택)"
          + (f" -- {src.get('GITHUB_TOKEN', 'gh auth token')}" if env.get("GITHUB_TOKEN") else
             " -- 없으면 공개 저장소만. 넣으려면: python3 wug.py key github"))
    py = str(venv_python())
    results = [
        _check("requests 가 가상환경에 있다", [py, "-c", "import requests"]),
        _check("설정이 정책 A 를 지킨다(agentic.config)", [py, "-c", "import agentic.config as c; print(c.load().model)"],
               "gemini-"),
        _check("MCP 서버와 붙는다(버전 셋)", [py, "-m", "agentic.mcp_client", "--versions", "walp"], '"protocol"'),
        _check("모델 없이 도는 길: 제어부 + sandbox 실행 (처음에는 sandbox 의존성을 까느라 몇 분 걸린다)",
               [py, "-m", "agentic.run", "agentic/config.json 파일 읽어줘"],
               "DONE (controller_tool)"),
    ]
    n = sum(results)
    print(f"[wug] 점검 {n}/{len(results)} 통과" + ("" if n == len(results) else " -- 실패한 줄을 먼저 본다"))
    if n == len(results) and has_key(env):
        print('[wug] 다음: python3 wug.py run "//안녕"   (// = 잡담 앞단을 건너뛰고 Gemini 를 진짜로 부른다)')
    return 0 if n == len(results) else 1


def versions() -> int:
    why = _ready()
    if why:
        return die(why)
    lk = lock()
    co = co_now()
    py = str(venv_python())
    model = subprocess.run([py, "-c", "import agentic.config as c; print(c.load().model)"], cwd=co,
                           capture_output=True, text=True).stdout.strip() or "(못 읽음)"
    mcp = subprocess.run([py, "-m", "agentic.mcp_client", "--versions", "walp"], cwd=co,
                         capture_output=True, text=True).stdout.strip() or "(못 읽음)"
    print(json.dumps({"well_used_gemini": WRAPPER_VERSION, "se_new_commit": lk["commit"], "model": model,
                      "mcp_walp": json.loads(mcp) if mcp.startswith("{") else mcp}, ensure_ascii=False, indent=1))
    return 0


def inspect(rest: list) -> int:
    why = _ready()
    if why:
        return die(why)
    p = subprocess.run([str(venv_python()), str(HERE / "wug_inspect.py"), *rest], cwd=co_now(), env=child_env())
    return p.returncode


def media(rest: list) -> int:
    """wug_media.py 를 가상환경에서. Pillow · pypdfium2 가 없으면 **스스로 한 번 깐다**(사람에게 시키지 않는다)."""
    if not venv_python().exists():
        return die("가상환경이 없다 -- python3 wug.py setup")
    argv = [str(venv_python()), str(HERE / "wug_media.py"), *rest]
    probe = subprocess.run([str(venv_python()), "-c", "import PIL, pypdfium2, requests"], capture_output=True)
    if probe.returncode != 0 and os.environ.get("WUG_SKIP_PIP") != "1":
        print("[wug] 사진·PDF 도구가 쓸 패키지(Pillow · pypdfium2)를 가상환경에 깐다(처음 한 번)", file=sys.stderr)
        r = subprocess.run([str(venv_python()), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                            "-r", str(HERE / "requirements.txt")], capture_output=True, text=True)
        if r.returncode != 0:
            return die(f"pip 실패: {r.stderr.strip()[-400:]}")
    return subprocess.run(argv, cwd=str(HERE), env=child_env()).returncode


def write(rest: list) -> int:
    """Gemini CLI 의 기본 지시문("software engineering" · "fewer than 3 lines")을 글쓰기 지시문으로 바꿔 띄운다.
    Gemini CLI 0.46.0 의 GEMINI_SYSTEM_MD(파일 경로)를 쓴다. GEMINI.md 와 확장 도구는 그대로 붙는다."""
    gem = shutil.which("gemini")
    if not gem:
        return die("gemini 명령이 없다 -- Gemini CLI 가 PATH 에 있어야 한다")
    sysmd = HERE / "writing" / "system.md"
    env = {**child_env(), "GEMINI_SYSTEM_MD": str(sysmd), "WUG_MODE": "write"}
    print(f"[wug] 글쓰기 모드: GEMINI_SYSTEM_MD={sysmd}", file=sys.stderr)
    os.execvpe(gem, [gem, *rest], env)
    return 0


def bench(rest: list) -> int:
    if not venv_python().exists():
        return die("가상환경이 없다 -- python3 wug.py setup")
    return subprocess.run([str(venv_python()), str(HERE / "wug_bench.py"), *rest], env=child_env()).returncode


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if sys.version_info < MIN_PY and os.environ.get("WUG_REEXEC") != "1":
        target = str(venv_python()) if venv_python().exists() else find_python()
        if target:
            print(f"[wug] 지금 파이썬 {sys.version.split()[0]} -- 3.10 이상인 {target} 로 다시 띄운다", file=sys.stderr)
        reexec_newer(str(Path(__file__).resolve()), argv)
    if cmd == "setup":
        return setup(skip_pip=os.environ.get("WUG_SKIP_PIP") == "1")
    if cmd == "doctor":
        return doctor()
    if cmd == "versions":
        return versions()
    if cmd == "run":
        if not rest:
            return die('물음이 없다: python3 wug.py run "물음"', 2)
        return run(" ".join(rest))
    if cmd == "write":
        return write(rest)
    if cmd == "bench":
        return bench(rest)
    if cmd == "media":
        return media(rest)
    if cmd == "key":
        return key_cmd(rest)
    if cmd == "inspect":
        return inspect(rest)
    return die(f"모르는 명령: {cmd} (setup · doctor · run · versions · key · write · bench · media · inspect)", 2)


if __name__ == "__main__":
    sys.exit(main())

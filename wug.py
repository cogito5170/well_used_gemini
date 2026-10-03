#!/usr/bin/env python3
"""well_used_gemini -- Gemini 를 정책 게이트 뒤에서 돌리는 얇은 진입점.

실제 일은 `cogito5170/se_new` 의 `agentic/` 이 한다(제어부 · Gate01 · 사고부(ReAct) · 루프 탐지기 ·
sandbox 실행 · MCP · RAG). 여기는 그것을 **고정된 커밋으로** 받아 와서 부르기만 한다.

    python3 wug.py setup              se_new 를 se_new.lock 의 커밋으로 받고(~/.cache/well_used_gemini/), 가상환경에 requests
    python3 wug.py doctor             무엇이 준비됐고 무엇이 안 됐는지 -- 키 없이도 도는 점검을 실제로 돌린다
    python3 wug.py run "물음"          agentic.run 을 부른다. 끝값: 0 = DONE, 그 밖 = 그 상태
    python3 wug.py versions           고정 커밋 · 설정 모델 · MCP 버전 셋(서버가 말한 것)
    python3 wug.py key [gemini|github]  키를 한 번 저장한다(WUG_HOME/keys.env · 권한 600 · 재설치해도 남는다)
    python3 wug.py media info|ask|generate|convert '<JSON>'   사진·PDF 받기/내보내기(wug_media.py)
    python3 wug.py model [이름]          Gemini CLI 의 기본 모델(~/.gemini/settings.json 의 model.name). 이름을 주면
                                      API 로 실제 있는지 확인한 뒤에만 쓴다(기본 wug_model.MODEL) · 폴백 없는 사슬도 같이 쓴다
    python3 wug.py ga "할 일" [--resume]   ga gemini(턴마다 짧은 CLI · rlo 지킴이 · 우리 MCP 도구가 도구 걸음)
    python3 wug.py essay spec.json        글쓰기 파이프라인(사진 사실 · 논지 · 문항 역할 · 초안 N벌 · 코드 관문 · 한 번 고침)
    python3 wug.py cli [gemini 인자...]    Gemini CLI 를 힙 임시방편(8 GB · 한계 근처 스냅숏)으로 띄운다
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
import re
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wug_model import MODEL as DEFAULT_CLI_MODEL, NO_FALLBACK_CHAINS, CLI_VERSION  # noqa: E402

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


MIN_PY = (3, 10)   # se_new 의 walp/grownet.py 가 int.bit_count() 를 쓴다(3.10 부터)
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
        _check(f"설정이 정책 A 를 지키고 모델이 {DEFAULT_CLI_MODEL} 하나다(agentic.config)",
               [py, "-c", "import agentic.config as c; print(c.load().model)"], DEFAULT_CLI_MODEL),
        _check("MCP 서버와 붙는다(버전 셋)", [py, "-m", "agentic.mcp_client", "--versions", "walp"], '"protocol"'),
        _check("모델 없이 도는 길: 제어부 + sandbox 실행 (처음에는 sandbox 의존성을 까느라 몇 분 걸린다)",
               [py, "-m", "agentic.run", "agentic/config.json 파일 읽어줘"],
               "DONE (controller_tool)"),
    ]
    n = sum(results)
    cli_check()
    print(f"[wug] 점검 {n}/{len(results)} 통과" + ("" if n == len(results) else " -- 실패한 줄을 먼저 본다"))
    if n == len(results) and has_key(env):
        print('[wug] 다음: python3 wug.py run "안녕"')
    return 0 if n == len(results) else 1


def gemini_cli_version() -> "str | None":
    gem = shutil.which("gemini")
    if not gem:
        return None
    try:
        p = subprocess.run([gem, "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"\d+\.\d+\.\d+", p.stdout or "")
    return m.group(0) if m else None


def cli_check() -> bool:
    """Gemini CLI 버전(사용자 결정: CLI_VERSION) · settings.json 의 모델과 폴백 사슬. 점검 수에는 안 센다(CLI 없이도 확장은 돈다)."""
    v = gemini_cli_version()
    ok_v = v == CLI_VERSION
    print(f"  {'통과' if ok_v else '실패'}  Gemini CLI {v or '(못 찾음)'} -- 정한 판 {CLI_VERSION}"
          + ("" if ok_v else f"  (npm install -g @google/gemini-cli@{CLI_VERSION})"))
    try:
        cur = json.loads(gemini_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {}
    name = (cur.get("model") or {}).get("name") if isinstance(cur.get("model"), dict) else None
    chains = ((cur.get("modelConfigs") or {}).get("modelChains") or {}) if isinstance(cur.get("modelConfigs"), dict) else {}
    pinned = (cur.get("experimental") or {}).get("dynamicModelConfiguration") is True and all(
        chains.get(k) == [{"model": DEFAULT_CLI_MODEL, "isLastResort": True}] for k in NO_FALLBACK_CHAINS)
    ok_m = name == DEFAULT_CLI_MODEL and pinned
    tel = cur.get("telemetry") if isinstance(cur.get("telemetry"), dict) else {}
    ok_t = tel.get("enabled") is True
    print(f"  {'통과' if ok_t else '실패'}  힙 고침: telemetry.enabled {'켜짐' if ok_t else '꺼짐 -- 0.62.0 은 이때 모델 요청마다 대화 전체를 붙들고 안 비운다'}"
          + ("" if ok_t else f"  (python3 wug.py model {DEFAULT_CLI_MODEL})"))
    print(f"  {'통과' if ok_m else '실패'}  CLI 기본 모델 {name or '(없음 -> auto)'} · 폴백 사슬 {'하나로 묶임' if pinned else '안 묶임'}"
          + ("" if ok_m else f"  (python3 wug.py model {DEFAULT_CLI_MODEL})"))
    if os.environ.get("GEMINI_MODEL") and os.environ["GEMINI_MODEL"] != DEFAULT_CLI_MODEL:
        print(f"  실패  환경 변수 GEMINI_MODEL={os.environ['GEMINI_MODEL']} 가 settings.json 보다 이긴다")
        ok_m = False
    return ok_v and ok_m and ok_t


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
    bad = ensure_deps()
    if bad:
        return die(bad)
    return subprocess.run(argv, cwd=str(HERE), env=child_env()).returncode


def ensure_deps(mods: str = "PIL, pypdfium2, requests, rlo, ga") -> "str | None":
    """가상환경에 requirements.txt 의 패키지가 없으면 한 번 깐다(사람에게 시키지 않는다). 실패하면 까닭을 돌려준다."""
    probe = subprocess.run([str(venv_python()), "-c", f"import {mods}"], capture_output=True)
    if probe.returncode == 0 or os.environ.get("WUG_SKIP_PIP") == "1":
        return None
    print("[wug] 가상환경에 requirements.txt 의 패키지를 깐다(처음 한 번 · ga-sdk 는 고정 커밋)", file=sys.stderr)
    r = subprocess.run([str(venv_python()), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                        "-r", str(HERE / "requirements.txt")], capture_output=True, text=True)
    return None if r.returncode == 0 else f"pip 실패: {r.stderr.strip()[-400:]}"


GEMINI_API = os.environ.get("WUG_GEMINI_API", "https://generativelanguage.googleapis.com/v1beta")


def gemini_settings_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def check_model(name: str, env: dict) -> "tuple[bool | None, str]":
    """(True 있음 | False 없음 | None 모름, 설명). 키로 GET models/<이름> -- 목록에 기대지 않고 그 이름 하나를 묻는다."""
    import urllib.error
    import urllib.request
    key = next((env.get(k) for k in KEY_NAMES if env.get(k)), "")
    if not key:
        return None, "키가 없어 API 로 확인 못 한다 -- python3 wug.py key"
    req = urllib.request.Request(f"{GEMINI_API}/models/{name}", headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, f"API 가 '{name}' 을 모른다(404)"
        return None, f"API 조회 실패 http_{e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, f"API 조회 실패 {type(e).__name__}"
    meth = d.get("supportedGenerationMethods") or []
    if "generateContent" not in meth:
        return False, f"'{name}' 은 있지만 generateContent 를 안 받는다({', '.join(meth) or '없음'})"
    return True, f"API 확인: {d.get('name')} · {d.get('displayName', '')} · 입력 {d.get('inputTokenLimit')} 토큰"


HEAP_FIX_TELEMETRY = {"enabled": True, "target": "local", "outfile": os.devnull, "logPrompts": False}
# 임시방편(CMD-WUG1 S4) -- 고침이 아니다. 우리 실행기(wug.py write · cli)만 건다. 다시 나면 힙 스냅숏이 WUG_HOME/heap 에 남는다
STOPGAP_NODE_OPTIONS = "--max-old-space-size=8192 --heapsnapshot-near-heap-limit=1"


def stopgap_env(env: dict) -> dict:
    d = WUG_HOME / "heap"
    d.mkdir(parents=True, exist_ok=True)
    extra = f"{STOPGAP_NODE_OPTIONS} --diagnostic-dir={d}"
    return {**env, "NODE_OPTIONS": (env.get("NODE_OPTIONS", "") + " " + extra).strip()}


def cli(rest: list) -> int:
    """Gemini CLI 를 임시방편 힙 설정으로 띄운다(지시문은 기본 그대로). 고침은 settings.json 의 telemetry 칸이다."""
    gem = shutil.which("gemini")
    if not gem:
        return die("gemini 명령이 없다 -- Gemini CLI 가 PATH 에 있어야 한다")
    os.execvpe(gem, [gem, *rest], stopgap_env(child_env()))
    return 0


def model_cmd(rest: list) -> int:
    """Gemini CLI 가 기본 모델을 고르는 차례(0.46.0 코드): -m > 환경 변수 GEMINI_MODEL > settings.json 의 model.name > auto."""
    env = child_env()
    sp = gemini_settings_path()
    try:
        cur = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
        parse_err = None
    except (ValueError, OSError) as e:
        cur, parse_err = None, e
    if not rest:
        now = (cur or {}).get("model", {}).get("name") if isinstance((cur or {}).get("model"), dict) else None
        print(f"settings.json model.name: {now or '(없음 -> auto)'}  ({sp})")
        if os.environ.get("GEMINI_MODEL"):
            print(f"환경 변수 GEMINI_MODEL={os.environ['GEMINI_MODEL']} -- settings.json 보다 이긴다")
        ok, why = check_model(now or DEFAULT_CLI_MODEL, env)
        print(f"{'있음' if ok else '없음' if ok is False else '모름'}: {why}")
        return 0
    name = rest[0].strip()
    ok, why = check_model(name, env)
    print(f"[wug] {why}")
    if ok is not True:
        return die("확인되지 않은 이름은 쓰지 않는다 -- 모르는 것은 안 된 것으로 다룬다", 1)
    if parse_err is not None or not isinstance(cur, dict):
        return die(f"{sp} 를 JSON 으로 못 읽었다(주석이 있을 수 있다) -- 덮어쓰지 않는다. 직접 넣어라: "
                   f'"model": {{"name": "{name}"}}', 1)
    sp.parent.mkdir(parents=True, exist_ok=True)
    if sp.is_file():
        bak = sp.with_name(f"settings.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(sp, bak)
        print(f"[wug] 옛 설정을 남겼다: {bak}")
    m = cur.get("model") if isinstance(cur.get("model"), dict) else {}
    cur["model"] = {**m, "name": name}
    # 폴백 없음: Gemini CLI 0.62.0 은 Gemini 3 모델이 막히면 같은 집안의 다른 모델(3.1-pro-preview)을 내민다.
    # 사슬을 이 모델 하나로 묶는다(experimental.dynamicModelConfiguration 이 켜져야 modelChains 를 읽는다)
    chains = {k: [{"model": name, "isLastResort": True}] for k in NO_FALLBACK_CHAINS}
    mc = cur.get("modelConfigs") if isinstance(cur.get("modelConfigs"), dict) else {}
    cur["modelConfigs"] = {**mc, "modelChains": {**(mc.get("modelChains") or {}), **chains}}
    ex = cur.get("experimental") if isinstance(cur.get("experimental"), dict) else {}
    cur["experimental"] = {**ex, "dynamicModelConfiguration": True}
    # 힙 고침(CMD-WUG1 S3): 0.62.0 은 텔레메트리가 꺼져 있으면 모델 요청마다 대화 전체를 JSON 으로 한 벌씩
    # telemetryBuffer 에 붙들고 영영 안 비운다(실측: 1174 -> 30 KB/turn). 켜 두되 파일은 버리고 프롬프트는 안 적는다.
    tel = cur.get("telemetry") if isinstance(cur.get("telemetry"), dict) else {}
    if not tel.get("enabled"):
        cur["telemetry"] = {**tel, **HEAP_FIX_TELEMETRY}
    sp.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[wug] {sp} 의 model.name = {name} · 폴백 사슬 = [{name}] 하나 -- Gemini CLI 를 다시 띄우면 적용된다")
    if os.environ.get("GEMINI_MODEL"):
        print(f"[wug] 주의: 환경 변수 GEMINI_MODEL={os.environ['GEMINI_MODEL']} 가 이것보다 이긴다")
    return 0


def write(rest: list) -> int:
    """Gemini CLI 의 기본 지시문("software engineering" · "fewer than 3 lines")을 글쓰기 지시문으로 바꿔 띄운다.
    Gemini CLI 0.46.0 의 GEMINI_SYSTEM_MD(파일 경로)를 쓴다. GEMINI.md 와 확장 도구는 그대로 붙는다."""
    gem = shutil.which("gemini")
    if not gem:
        return die("gemini 명령이 없다 -- Gemini CLI 가 PATH 에 있어야 한다")
    sysmd = HERE / "writing" / "system.md"
    env = stopgap_env({**child_env(), "GEMINI_SYSTEM_MD": str(sysmd), "WUG_MODE": "write"})
    print(f"[wug] 글쓰기 모드: GEMINI_SYSTEM_MD={sysmd}", file=sys.stderr)
    os.execvpe(gem, [gem, *rest], env)
    return 0


GA_RPM = 5   # ga 와 같은 가정: gemini-3-flash-preview 무료 등급의 분당 한도를 모른다. 429 의 retryDelay 가 이긴다


def ga_config(cli: "list | None" = None) -> dict:
    """ga gemini(CMD-GA21)의 설정 -- 모델 고정 · 폴백 없음 · 우리 MCP 도구 가운데 **도구 걸음만**(steps.json 의 kind tool).
    모델을 스스로 부르는 도구(agentic_run · media_ask · image_generate · essay_write)는 넣지 않는다 -- 지킴이를 비켜 가는 길이 된다."""
    import wug_mcp
    kinds = {x["id"]: x["kind"] for x in json.loads((HERE / "steps.json").read_text(encoding="utf-8"))["steps"]}
    tools = {}
    for t in wug_mcp.TOOLS:
        if kinds.get(f"mcp.{t['name']}") == "tool" and t["name"] not in ("agentic_setup", "agentic_doctor"):
            tools[f"wug.{t['name']}"] = {"mcp": "wug", "tool": t["name"], "about": " ".join(t["description"].split())[:200]}
    return {"schema": "ga-gemini/1", "model": DEFAULT_CLI_MODEL, "cli": cli or ["gemini"], "budget": {"rpm": GA_RPM},
            "mcp_servers": {"wug": {"command": [str(venv_python()), str(HERE / "wug_mcp.py")], "cwd": str(HERE)}},
            "tools": tools, "state_dir": str(WUG_HOME / "ga" / "state")}


def ga(rest: list) -> int:
    """ga gemini 로 돈다(CMD-WUG1 S10): 턴마다 짧게 사는 headless CLI(--resume) -- 힙이 쌓이지 않는다.
    Gemini 는 닫힌 걸음 목록으로 지휘만 하고, 도구 걸음은 우리 MCP 도구가 rlo Scheduler 아래에서 한다."""
    if not venv_python().exists():
        return die("가상환경이 없다 -- python3 wug.py setup")
    bad = ensure_deps()
    if bad:
        return die(bad)
    d = WUG_HOME / "ga"
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / "ga-gemini.json"
    cli = json.loads(os.environ["WUG_GA_CLI"]) if os.environ.get("WUG_GA_CLI") else None   # 시험용: 다른 gemini 명령
    cfg.write_text(json.dumps(ga_config(cli), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return subprocess.run([str(venv_python()), "-m", "ga", "gemini", "--config", str(cfg), *rest], cwd=str(d),
                          env=child_env()).returncode


def essay(rest: list) -> int:
    if not venv_python().exists():
        return die("가상환경이 없다 -- python3 wug.py setup")
    bad = ensure_deps()
    if bad:
        return die(bad)
    return subprocess.run([str(venv_python()), str(HERE / "wug_essay.py"), *rest], env=child_env()).returncode


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
    if cmd == "cli":
        return cli(rest)
    if cmd == "model":
        return model_cmd(rest)
    if cmd == "write":
        return write(rest)
    if cmd == "ga":
        return ga(rest)
    if cmd == "essay":
        return essay(rest)
    if cmd == "bench":
        return bench(rest)
    if cmd == "media":
        return media(rest)
    if cmd == "key":
        return key_cmd(rest)
    if cmd == "inspect":
        return inspect(rest)
    return die(f"모르는 명령: {cmd} (setup · doctor · run · versions · key · model · cli · write · ga · essay · bench · media · inspect)", 2)


if __name__ == "__main__":
    sys.exit(main())

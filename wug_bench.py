#!/usr/bin/env python3
"""글쓰기 품질 차이를 **원인별로 가르는** 실험. wug.py bench 가 가상환경 파이썬으로 부른다.

같은 요청 · 같은 사진으로 네 조건을 N 번씩 돌린다:

    a  Gemini CLI 그대로          (기본 지시문: "software engineering" · "Minimal Output: fewer than 3 lines")
    b  Gemini CLI + 글쓰기 모드    (GEMINI_SYSTEM_MD=writing/system.md)
    c  API 직접 · 같은 작은 모델   (글쓰기 지시문 + 사진을 inline 으로 · CLI 의 도구 · GEMINI.md 없음)
    d  API 직접 · 큰 모델          (c 와 같고 모델만 다르다)

    a - b  = 지시문의 몫      b - c = CLI 배관(사진 붙이기 · 도구 · GEMINI.md)의 몫      c - d = 모델 크기의 몫

a · b 는 `-m` 으로 c 와 같은 모델을 쓴다. 그래야 차이가 모델에서 오지 않는다.

## 재는 것 -- 코드로 세는 것과 사람이 보는 것을 갈라 둔다

**코드로 센다(LLM 안 씀).** 다 대리 지표다 -- 글의 질 자체가 아니라 오늘 본 차이의 **증상**을 센다.
  · 글자 수(공백 뺀 한글·영문)
  · 사진 사실: spec 의 facts 중 몇 개를 글에 적었나(사람이 사진을 보고 적은 목록이 기준이다)
  · 메모체: 문장 끝이 ~함 · ~임 · ~음 · ~됨 인 비율
  · 추상어: spec 의 abstract 목록이 몇 번 나왔나
  · 검토: '주의할 점' · '출처 미확인' 같은 자기 검토 표지가 있나
**사람이 본다.** blind.md 에 출처를 가린 채 섞어 둔다. 순위를 매긴 뒤 key.json 으로 푼다. 글의 질은 이것이 판정이다.

모델 이름은 **응답이 밝힌 것**을 적는다(CLI 는 stats.models 의 키 · API 는 modelVersion). 못 받으면 '미보고'.
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYSTEM_MD = HERE / "writing" / "system.md"
API = os.environ.get("WUG_GEMINI_API", "https://generativelanguage.googleapis.com/v1beta")
SMALL = "gemini-3.1-flash-lite"
CONDS = {"a": "CLI 그대로", "b": "CLI + 글쓰기 모드", "c": "API · 작은 모델", "d": "API · 큰 모델"}
MEMO = re.compile(r"(함|임|음|됨)\s*[.。]?\s*$")
REVIEW = ("주의할 점", "출처 미확인", "확인하지 않았", "확인 안 한")
DEFAULT_ABSTRACT = ["밀도", "호흡", "접점", "필터", "정교한", "완벽히", "즉각적", "스며드"]


# ---------------------------------------------------------------- 재기(코드만)
def sentences(text: str) -> list:
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*([*\-•>#]+|\d+\.)\s*", "", line).strip()
        if not line or not re.search(r"[가-힣]", line):
            continue
        out += [s.strip() for s in re.split(r"(?<=[.!?。])\s+", line) if s.strip()]
    return out


def measure(text: str, facts: list, abstract: list) -> dict:
    """대리 지표. facts 의 한 항목은 '상점 창|쇼윈도|shop window' 처럼 | 로 동의어를 묶는다."""
    low = text.lower()
    hit = [f for f in facts if any(w.strip().lower() in low for w in f.split("|") if w.strip())]
    ss = [s for s in sentences(text) if re.search(r"[가-힣]", s)]
    memo = [s for s in ss if MEMO.search(s)]
    return {
        "chars": len(re.sub(r"\s", "", text)),
        "photo_facts": len(hit), "photo_facts_of": len(facts), "facts_hit": hit,
        "memo_ratio": round(len(memo) / len(ss), 3) if ss else None, "sentences": len(ss),
        "abstract": sum(low.count(w.lower()) for w in abstract),
        "review": any(r in text for r in REVIEW),
    }


# ---------------------------------------------------------------- 조건
def build_prompt(spec: dict, photo_names: list, cli: bool) -> str:
    p = spec.get("prompt") or (spec.get("context", "") + "\n\n" + "\n".join(f"Q{i + 1}. {q}" for i, q in
                                                                          enumerate(spec.get("questions", []))))
    if photo_names:
        refs = " ".join(f"@{n}" for n in photo_names) if cli else f"(사진 {len(photo_names)}장을 함께 보낸다)"
        p += f"\n\n첨부 사진: {refs}"
    return p.strip()


def run_cli(spec: dict, photos: list, model: str, writing: bool, timeout: int = 420) -> dict:
    """gemini -p 를 빈 임시 폴더에서. 사진은 그 폴더로 복사해 @이름 으로 붙인다(작업 공간 밖 경로는 거절될 수 있다)."""
    gem = shutil.which("gemini")
    if not gem:
        return {"error": "gemini_not_found"}
    with tempfile.TemporaryDirectory(prefix="wugbench-") as d:
        names = []
        for i, p in enumerate(photos):
            n = f"photo{i + 1}{Path(p).suffix.lower()}"
            shutil.copy(p, Path(d) / n)
            names.append(n)
        env = dict(os.environ)
        env.pop("GEMINI_SYSTEM_MD", None)
        if writing:
            env["GEMINI_SYSTEM_MD"] = str(SYSTEM_MD)
        argv = [gem, "-p", build_prompt(spec, names, True), "-m", model, "-o", "json", "--skip-trust"]
        t = time.time()
        try:
            r = subprocess.run(argv, cwd=d, env=env, capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return {"error": f"timeout_{timeout}s"}
        secs = round(time.time() - t, 1)
    try:
        out = json.loads(r.stdout[r.stdout.find("{"):])
    except ValueError:
        return {"error": f"cli_exit_{r.returncode}:{(r.stderr or r.stdout).strip()[-300:]}", "seconds": secs}
    models = sorted(((out.get("stats") or {}).get("models") or {}).keys())
    return {"text": out.get("response") or "", "models": models or ["미보고"], "seconds": secs,
            "error": (json.dumps(out["error"], ensure_ascii=False)[:300] if out.get("error") else None)}


def _key() -> str:
    k = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not k:
        raise SystemExit("[bench] GEMINI_API_KEY 가 없다 -- python3 wug.py key")
    return k


def system_text() -> str:
    t = SYSTEM_MD.read_text(encoding="utf-8")
    return t.replace("${AvailableTools}", "(none in this run)")


MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf"}


def run_api(spec: dict, photos: list, model: str, poster=None, timeout: int = 300) -> dict:
    parts = [{"inline_data": {"mime_type": MIME.get(Path(p).suffix.lower(), "image/jpeg"),
                              "data": base64.b64encode(Path(p).read_bytes()).decode()}} for p in photos]
    body = {"system_instruction": {"parts": [{"text": system_text()}]},
            "contents": [{"role": "user", "parts": parts + [{"text": build_prompt(spec, photos, False)}]}]}
    url = f"{API}/models/{model}:generateContent"
    t = time.time()
    if poster:
        data = poster(url, body)
    else:
        import requests
        try:
            r = requests.post(url, headers={"x-goog-api-key": _key()}, json=body, timeout=timeout)
        except requests.RequestException as e:
            return {"error": f"network:{type(e).__name__}"}
        if r.status_code != 200:
            msg, k = f"http_{r.status_code}:{r.text[:300]}", os.environ.get("GEMINI_API_KEY", "")
            return {"error": msg.replace(k, "<키 가림>") if k else msg}
        data = r.json()
    text = "\n".join(p.get("text", "") for c in data.get("candidates") or []
                     for p in (c.get("content") or {}).get("parts") or [] if not p.get("thought"))
    return {"text": text, "models": [data.get("modelVersion") or "미보고"], "seconds": round(time.time() - t, 1),
            "error": None if text.strip() else "empty_response"}


def pick_big(lister=None) -> str:
    """WUG_BENCH_BIG > 목록에서 generateContent 를 받는 'pro' 모델(미리보기가 아닌 것 · 번호가 큰 것 먼저)."""
    if os.environ.get("WUG_BENCH_BIG"):
        return os.environ["WUG_BENCH_BIG"]
    if lister:
        models = lister()
    else:
        import requests
        r = requests.get(f"{API}/models", params={"pageSize": 200}, headers={"x-goog-api-key": _key()}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"[bench] 모델 목록 http_{r.status_code} -- --big 으로 직접 줘라")
        models = r.json().get("models") or []
    cands = [m["name"].split("/", 1)[-1] for m in models
             if re.search(r"gemini-[\d.]+-pro", m.get("name", "")) and "image" not in m.get("name", "")
             and "tts" not in m.get("name", "") and "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if not cands:
        raise SystemExit("[bench] 목록에 pro 모델이 없다 -- --big 으로 직접 줘라")
    return sorted(cands, key=lambda n: ("preview" not in n, [int(x) for x in re.findall(r"\d+", n)]), reverse=True)[0]


# ---------------------------------------------------------------- 보고
def summarize(rows: list) -> str:
    out = ["| 조건 | 돈 횟수 | 글자 | 사진 사실 | 메모체 비율 | 추상어 | 검토 있음 | 응답이 밝힌 모델 |",
           "|---|---|---|---|---|---|---|---|"]
    for c in CONDS:
        rs = [r for r in rows if r["cond"] == c and not r.get("error")]
        n_all = len([r for r in rows if r["cond"] == c])
        if not n_all:
            continue
        if not rs:
            out.append(f"| {c} {CONDS[c]} | 0/{n_all} | — | — | — | — | — | (전부 실패) |")
            continue

        def span(k):
            v = [r["m"][k] for r in rs if r["m"][k] is not None]
            if not v:
                return "—"
            med = statistics.median(v)
            return f"{med:g} ({min(v):g}–{max(v):g})" if len(v) > 1 else f"{med:g}"
        fo = rs[0]["m"]["photo_facts_of"]
        models = sorted({m for r in rs for m in r["models"]})
        out.append(f"| {c} {CONDS[c]} | {len(rs)}/{n_all} | {span('chars')} | {span('photo_facts')} / {fo} | "
                   f"{span('memo_ratio')} | {span('abstract')} | {sum(r['m']['review'] for r in rs)}/{len(rs)} | "
                   f"{', '.join(models)} |")
    out.append("\n가운데 값(최소–최대). **대리 지표다** -- 글의 질은 blind.md 를 사람이 보고 정한다.")
    out.append("가르는 법: a−b = 지시문 · b−c = CLI 배관(사진 붙이기 · 도구 · GEMINI.md) · c−d = 모델 크기.")
    errs = [r for r in rows if r.get("error")]
    if errs:
        out.append("\n실패한 실행:")
        out += [f"- {r['cond']}#{r['run']}: {r['error']}" for r in errs]
    return "\n".join(out)


def blind(rows: list, out_dir: Path, seed=None) -> None:
    ok = [r for r in rows if not r.get("error")]
    rng = random.Random(seed)
    rng.shuffle(ok)
    key, lines = {}, ["# 블라인드 평가", "", "출처(조건 · 모델)를 가렸다. 읽고 순위를 매긴 **뒤에** key.json 을 열어라.", ""]
    for i, r in enumerate(ok):
        tag = f"X{i + 1:02d}"
        key[tag] = {"cond": r["cond"], "run": r["run"], "models": r["models"]}
        lines += [f"## {tag}", "", r["text"].strip(), "", "---", ""]
    (out_dir / "blind.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="글쓰기 품질 차이를 원인별로 가르는 실험")
    ap.add_argument("spec")
    ap.add_argument("--runs", type=int, default=None)
    ap.add_argument("--only", default="abcd", help="돌릴 조건(예: ab)")
    ap.add_argument("--small", default=None, help=f"a·b·c 의 모델(기본 {SMALL})")
    ap.add_argument("--big", default=None, help="d 의 모델(기본: 목록에서 pro)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--measure", nargs="+", metavar="TXT", help="실험 없이 이 글 파일들만 잰다(지표가 가르는지 먼저 보기)")
    a = ap.parse_args(argv)
    spec = json.loads(Path(os.path.expanduser(a.spec)).read_text(encoding="utf-8"))
    facts, abstract = spec.get("facts") or [], spec.get("abstract") or DEFAULT_ABSTRACT
    if a.measure:
        for f in a.measure:
            m = measure(Path(os.path.expanduser(f)).read_text(encoding="utf-8"), facts, abstract)
            print(f"{f}: 글자 {m['chars']} · 사진 사실 {m['photo_facts']}/{m['photo_facts_of']} {m['facts_hit']} · "
                  f"메모체 {m['memo_ratio']} ({m['sentences']}문장) · 추상어 {m['abstract']} · 검토 {m['review']}")
        return 0
    photos = [str(Path(os.path.expanduser(p)).resolve()) for p in spec.get("photos") or []]
    missing = [p for p in photos if not Path(p).is_file()]
    if missing:
        print(f"[bench] 사진이 없다: {missing}", file=sys.stderr)
        return 2
    runs = a.runs or int(spec.get("runs", 3))
    small = a.small or spec.get("small") or SMALL
    big = None
    if "d" in a.only:
        big = a.big or spec.get("big") or pick_big()
    out = Path(os.path.expanduser(a.out or spec.get("out") or
                                  f"~/well_used_gemini_bench/{time.strftime('%Y%m%d-%H%M%S')}"))
    (out / "raw").mkdir(parents=True, exist_ok=True)
    print(f"[bench] 조건 {a.only} · 각 {runs}번 · 작은 모델 {small}" + (f" · 큰 모델 {big}" if big else "")
          + f"\n[bench] 결과: {out}", flush=True)
    rows = []
    for i in range(runs):
        for c in a.only:
            if c not in CONDS:
                continue
            if c in "ab":
                r = run_cli(spec, photos, small, writing=(c == "b"))
            else:
                r = run_api(spec, photos, small if c == "c" else big)
            r.update({"cond": c, "run": i + 1})
            r.setdefault("models", [])
            if not r.get("error"):
                r["m"] = measure(r["text"], facts, abstract)
                (out / "raw" / f"{c}-{i + 1}.md").write_text(r["text"], encoding="utf-8")
            print(f"  {c}#{i + 1} {CONDS[c]}: " + (f"실패 {r['error']}" if r.get("error") else
                  f"글자 {r['m']['chars']} · 사진 사실 {r['m']['photo_facts']}/{len(facts)} · "
                  f"메모체 {r['m']['memo_ratio']} · {', '.join(r['models'])} · {r.get('seconds')}초"), flush=True)
            rows.append(r)
            with open(out / "rows.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({k: v for k, v in r.items() if k != "text"}, ensure_ascii=False) + "\n")
    rep = summarize(rows)
    (out / "report.md").write_text(f"# 글쓰기 실험 {out.name}\n\n{rep}\n", encoding="utf-8")
    blind(rows, out)
    print("\n" + rep + f"\n\n[bench] 사람이 볼 것: {out / 'blind.md'} (다 읽고 나서 {out / 'key.json'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

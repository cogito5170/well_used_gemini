#!/usr/bin/env python3
"""글쓰기 파이프라인 -- 모델 하나(wug_model.MODEL) 바깥에 **비계**를 친다. 판정은 코드가 한다.

    사진 ─> ① 사실 뽑기(보이는 것만, JSON) ─┐
    문항 ─> ② 역할 나누기(코드: 정의 · 내 이유 · 기준) ─┤
           ③ 논지 후보 5개 -> 하나 고르기 ─────────────┼─> ④ 초안 N벌 ─> ⑤ 관문(코드) ─> ⑥ 위반만 돌려보내 한 번 고침
                                                          │                                 └─> 고친 것이 덜 나쁠 때만 바꾼다
    사용자 재료(있으면) ───────────────────────────────────┘
    ─> 최종 글 + 보고서(벌마다 관문 결과) + 사용자만 줄 수 있는 것에 대한 물음

**관문은 대리 지표다.** 오늘 본 실패(사진 무시 · 같은 말 되풀이 · 메모체 · 추상어 · 확인 안 한 인용 · 검토 없음)를
세는 것이지 글이 좋다는 판정이 아니다. 고르는 순서: hard 위반 수 -> soft 위반 수 -> 사진 근거 수.

    python3 wug.py essay spec.json             (spec: prompt · questions · photos · [limit] · [material] · [n])

모델은 하나(wug_model.MODEL · 폴백 없음 · 환경 변수로 안 바뀐다). 부를 때마다 응답이 밝힌 모델을 원장에 적는다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wug_media as WM  # noqa: E402

from wug_model import MODEL  # noqa: E402
MEMO = re.compile(r"(함|임|음|됨)\s*[.。]?\s*$")
ABSTRACT = ["밀도", "호흡", "접점", "필터", "정교한", "완벽히", "즉각적", "스며드", "본질", "비로소", "결합"]
FIRST_PERSON = re.compile(r"(^|[\s\"'(])(나는|내가|나의|나에게|나를|저는|제가|저의|저에게)")
QUOTE_CLAIM = re.compile(r"(말했|라는 말|의 말|라고 했|이라 했|인용|명언)")
UNVERIFIED_MARK = ("출처 미확인", "출처:", "확인하지 않", "확인 안 한")
ROLE_TEXT = {"define": "정의 -- 이 답이 글 전체의 논지를 처음 세운다",
             "personal": "내 이유 -- 1인칭으로, 쓰는 사람 자신의 까닭을 말한다(논지를 내 쪽으로 끌어온다)",
             "criterion": "기준 -- 무엇이 좋은지 판별할 기준을 세우고 논지로 닫는다",
             "general": "앞 답이 말하지 않은 것을 더한다"}


# ---------------------------------------------------------------- 텍스트 다루기(코드만)
def sentences(text: str) -> list:
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*([*\-•>]+|\d+\.)\s*", "", line).strip()
        if not line or line.startswith("#") or not re.search(r"[가-힣]", line):
            continue
        out += [s.strip() for s in re.split(r"(?<=[.!?。])\s+", line) if s.strip()]
    return out


def split_answers(text: str, n: int) -> "tuple[list, str]":
    """'## Q1 ...' 머리로 나눈다. (문항별 본문 n개, 주의할 점 칸). 못 찾은 문항은 ''."""
    parts = re.split(r"(?m)^#{1,3}\s*", text)
    answers, review = [""] * n, ""
    for p in parts:
        head, _, body = p.partition("\n")
        m = re.match(r"\s*Q\s*(\d+)", head, re.I)
        if m and 1 <= int(m.group(1)) <= n:
            answers[int(m.group(1)) - 1] = body.strip()
        elif "주의할 점" in head:
            review = body.strip()
    return answers, review


def assign_roles(questions: list, given=None) -> list:
    if given:
        return list(given)
    roles = []
    for q in questions:
        if re.search(r"(나는|당신은|본인은|너는|제가|내가).*왜|왜.*(나는|당신|본인)", q):
            roles.append("personal")
        elif re.search(r"(좋은|바람직한|훌륭한).*(란|이란|무엇)|무엇이라고 생각|기준", q):
            roles.append("criterion")
        elif re.search(r"왜 중요|무엇인가|란 무엇", q) and "define" not in roles:
            roles.append("define")
        else:
            roles.append("general")
    return roles


# ---------------------------------------------------------------- 관문(코드만 · LLM 안 씀)
def gate(text: str, spec: dict, facts: list, roles: list, points=None) -> dict:
    """{"hard": [...], "soft": [...], "photo_cover": 사진 몇 장을 근거로 썼나, "answers": [...]}."""
    qs = spec["questions"]
    answers, review = split_answers(text, len(qs))
    hard, soft = [], []
    limit = spec.get("limit")
    for i, a in enumerate(answers):
        n = len(a)
        if not a:
            hard.append(f"Q{i + 1}: 답이 없다(머리 '## Q{i + 1}' 를 못 찾았다)")
            continue
        if limit and n > limit:
            hard.append(f"Q{i + 1}: {n}자 > 상한 {limit}자")
        elif limit and n < 0.8 * limit:
            soft.append(f"Q{i + 1}: {n}자 -- 상한 {limit}자의 {n * 100 // limit}%")
        elif not limit and n < 150:
            soft.append(f"Q{i + 1}: {n}자 -- 너무 짧다(상한이 없을 때 150자 아래)")
        ss = sentences(a)
        memo = [s for s in ss if MEMO.search(s)]
        if memo:
            hard.append(f"Q{i + 1}: 메모체 {len(memo)}문장 -- 예: '{memo[0][-24:]}'")
        ab = [w for w in ABSTRACT if w in a]
        if ab:
            soft.append(f"Q{i + 1}: 추상어 {', '.join(ab)}")
        if roles[i] == "personal" and not FIRST_PERSON.search(a):
            hard.append(f"Q{i + 1}: '내 이유' 문항인데 1인칭 주어가 없다")
        for s in ss:
            if ('"' in s or '“' in s or "‘" in s or "'" in s) and QUOTE_CLAIM.search(s) and \
                    not any(m in s for m in UNVERIFIED_MARK):
                hard.append(f"Q{i + 1}: 인용에 출처 표시가 없다 -- '{s[:40]}'")
    # 되풀이: 계획 단계가 문항마다 **서로 다른** 새 요점을 정했다. 답마다 제 요점의 낱말이 있어야 한다.
    # (글자쌍 겹침으로 재 보았더니 오늘의 Gemini 답 -- 같은 생각을 다른 말로 세 번 -- 을 못 잡았다. 그래서 뺐다)
    for i, a in enumerate(answers):
        pt = points[i] if points and i < len(points) else None
        if a and pt and pt.get("words") and not any(w in a for w in pt["words"]):
            hard.append(f"Q{i + 1}: 이 문항의 새 요점({pt.get('point', '')[:30]})이 답에 없다")
    # 사진 근거: 사진마다 그 사진의 사실 낱말이 하나라도 글에 있나
    body = "\n".join(answers) + "\n" + text
    cover = 0
    for f in facts:
        words = [w for w in f.get("words", []) if w]
        if any(w.lower() in body.lower() for w in words):
            cover += 1
        else:
            soft.append(f"사진 {f.get('photo')}: 보이는 것을 하나도 안 썼다({', '.join(words[:4])})")
    if facts and cover == 0:
        hard.append("사진을 하나도 근거로 쓰지 않았다")
    if not review:
        hard.append("'주의할 점' 칸이 없다")
    return {"hard": hard, "soft": soft, "photo_cover": cover, "answers": [len(a) for a in answers]}


def rank_key(g: dict) -> tuple:
    return (len(g["hard"]), len(g["soft"]), -g["photo_cover"])


# ---------------------------------------------------------------- 모델 단계
class Run:
    def __init__(self, out: Path, poster=None):
        self.out, self.poster, self.calls = out, poster, []
        out.mkdir(parents=True, exist_ok=True)

    def log(self, kind: str, data: dict) -> None:
        with open(self.out / "ledger.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "kind": kind, **data}, ensure_ascii=False) + "\n")

    def call(self, step: str, parts: list, text: str, as_json=False, temperature=None) -> str:
        gen = {}
        if as_json:
            gen["responseMimeType"] = "application/json"
        if temperature is not None:
            gen["temperature"] = temperature
        body = {"contents": [{"role": "user", "parts": parts + [{"text": text}]}]}
        if gen:
            body["generationConfig"] = gen
        resp = WM._post(MODEL, body, self.poster)
        out = "\n".join(WM._texts(resp)).strip()
        self.calls.append(resp.get("modelVersion") or "미보고")
        self.log("MODEL_CALL", {"step": step, "asked": MODEL, "reported": resp.get("modelVersion") or "미보고",
                                "chars": len(out)})
        return out


def _json(text: str, default):
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    try:
        return json.loads(m.group(1) if m else text)
    except (ValueError, AttributeError):
        return default


FACTS_ASK = ("List only what is visible in this photo, for a fashion/space essay. Return JSON: "
             '{"facts": ["...", ...], "words": ["short Korean nouns that name those things", '
             '"and their English words"]}. 4-8 facts: garment, colour, material, place, light, time of day, posture. '
             "Do not guess anything you cannot see. Answer in Korean for facts.")


def step_facts(R: Run, spec: dict) -> list:
    out = []
    for i, p in enumerate(spec.get("photos") or []):
        given = (spec.get("facts") or {}).get(str(i + 1)) if isinstance(spec.get("facts"), dict) else None
        if given:                         # 사람이 적은 사실이 이긴다
            out.append({"photo": i + 1, "facts": given, "words": [w for f in given for w in f.split("|")],
                        "by": "사람"})
            continue
        d = _json(R.call("facts", WM._parts_for([p]), FACTS_ASK, as_json=True), {})
        facts = [str(x) for x in (d.get("facts") or [])][:8] if isinstance(d, dict) else []
        words = [str(x) for x in (d.get("words") or [])][:16] if isinstance(d, dict) else []
        out.append({"photo": i + 1, "facts": facts, "words": words, "by": "모델(확인 안 됨)"})
    R.log("FACTS", {"facts": out})
    return out


def step_thesis(R: Run, spec: dict, facts: list) -> "tuple[str, list]":
    ask = (f"요청:\n{spec['prompt']}\n\n문항:\n" + "\n".join(f"Q{i + 1}. {q}" for i, q in enumerate(spec["questions"]))
           + "\n\n사진에서 보이는 것:\n" + "\n".join(f"- 사진{f['photo']}: {', '.join(f['facts'])}" for f in facts)
           + ("\n\n쓰는 사람의 실제 재료:\n" + spec["material"] if spec.get("material") else "")
           + "\n\n이 글 전체가 섬길 논지 후보 5개를 만들어라. 각 후보는 한 문장 주장이다(구호가 아니라 펼칠 수 있는 주장). "
             "흔한 비유(예: '옷은 건축이다')에 기대면 그 사실을 적어라. 그다음 가장 구체적이고 사진과 재료로 뒷받침되는 것을 골라라. "
             "마지막으로 고른 논지로 문항마다 **앞 문항이 말하지 않은 새 요점** 하나씩을 정하고, 그 요점을 가리키는 "
             "짧은 한국어 낱말 2~3개를 붙여라(문항끼리 낱말이 겹치면 안 된다). "
             'JSON: {"candidates": ["..."], "pick": 0부터 센 번호, "why": "...", '
             '"points": [{"q": 1, "point": "...", "words": ["...", "..."]}, ...]}')
    d = _json(R.call("thesis", [], ask, as_json=True), {})
    cands = [str(c) for c in (d.get("candidates") or [])] if isinstance(d, dict) else []
    pick = d.get("pick", 0) if isinstance(d, dict) else 0
    pick = pick if isinstance(pick, int) and 0 <= pick < len(cands) else 0
    thesis = cands[pick] if cands else ""
    points = clean_points(d.get("points") if isinstance(d, dict) else None, len(spec["questions"]))
    R.log("THESIS", {"candidates": cands, "pick": pick, "why": (d.get("why") if isinstance(d, dict) else ""),
                     "points": points})
    return thesis, cands, points


def clean_points(raw, n: int) -> list:
    """문항 순서대로 n 개. 낱말이 다른 문항과 겹치면 그 낱말은 버린다(겹치는 낱말로는 '새 요점' 을 못 가린다)."""
    pts = [{"point": "", "words": []} for _ in range(n)]
    for x in raw or []:
        if isinstance(x, dict) and isinstance(x.get("q"), int) and 1 <= x["q"] <= n:
            pts[x["q"] - 1] = {"point": str(x.get("point", "")),
                               "words": [str(w).strip() for w in (x.get("words") or []) if str(w).strip()][:4]}
    orig = [list(p["words"]) for p in pts]          # 먼저 다 보고 나서 지운다(앞에서 지운 것이 뒤의 판정을 바꾸지 않게)
    for i, p in enumerate(pts):
        others = {w for j, ws in enumerate(orig) if j != i for w in ws}
        p["words"] = [w for w in orig[i] if w not in others]
    return pts


def draft_prompt(spec: dict, facts: list, thesis: str, roles: list, points=None) -> str:
    lim = spec.get("limit")
    pts = points or [{}] * len(spec["questions"])
    qs = "\n".join(f"## Q{i + 1}. {q}\n(역할: {ROLE_TEXT[roles[i]]}"
                   + (f" · 이 답의 새 요점: {pts[i]['point']}" if pts[i].get("point") else "") + ")"
                   for i, q in enumerate(spec["questions"]))
    return (f"요청:\n{spec['prompt']}\n\n논지(글 전체가 이것을 섬긴다): {thesis}\n\n"
            "사진에서 보이는 것(이것만 쓴다 -- 보이지 않는 것을 지어내지 마라):\n"
            + "\n".join(f"- 사진{f['photo']}: {', '.join(f['facts'])}" for f in facts)
            + ("\n\n쓰는 사람의 실제 재료(이것 밖의 경험을 지어내지 마라):\n" + spec["material"] if spec.get("material") else
               "\n\n쓰는 사람의 경험은 주어지지 않았다 -- 지어내지 마라. 필요하면 '주의할 점' 에서 물어라.")
            + f"\n\n아래 꼴 그대로 써라. 머리는 '## Q번호' 로 시작한다.\n{qs}\n"
            + ("## 사진 캡션\n(사진마다 한 줄: 옷 설명이 아니라 장소와 옷의 관계)\n" if facts else "")
            + "## 주의할 점\n\n"
            "규칙: 1인칭 평서문(~다). 메모체(~함 · ~임) 금지. 구체적인 명사와 동사. 문장 길이를 섞는다. "
            "각 답은 앞 답이 말하지 않은 것을 더한다. "
            + (f"각 답은 {int(lim * 0.8)}~{lim}자. " if lim else "각 답은 250~450자. ")
            + "사진의 구체적인 것을 적어도 하나씩 쓴다. 이름이 붙은 인용을 쓰면 옆에 '(출처 미확인)'. "
              "'주의할 점' 에는 상투적인 데 · 확인 안 한 인용 · 쓰는 사람만 줄 수 있는 것과 그것을 끌어낼 물음 하나.")


def step_drafts(R: Run, spec: dict, facts: list, thesis: str, roles: list, n: int, points=None) -> list:
    parts = WM._parts_for(spec.get("photos") or [])
    base = draft_prompt(spec, facts, thesis, roles, points)
    temps = [0.7, 0.9, 1.0, 1.1, 0.8, 1.2][:n] + [1.0] * max(0, n - 6)
    drafts = []
    for i, t in enumerate(temps):
        txt = R.call(f"draft{i + 1}", parts, base, temperature=t)
        drafts.append(txt)
        (R.out / f"draft{i + 1}.md").write_text(txt, encoding="utf-8")
    return drafts


def step_revise(R: Run, spec: dict, text: str, g: dict) -> str:
    """위반 목록만 돌려보낸다(어떻게 재는지는 안 알려 준다 -- 알려 주면 검사가 사양서가 된다)."""
    issues = g["hard"] + g["soft"]
    ask = ("아래 글을 고쳐라. 지적된 곳만 고치고, 논지와 꼴('## Q번호' · '## 주의할 점')은 그대로 둔다.\n\n"
           "지적:\n" + "\n".join(f"- {x}" for x in issues) + "\n\n글:\n" + text)
    return R.call("revise", WM._parts_for(spec.get("photos") or []), ask, temperature=0.4)


def run(spec: dict, out: Path, poster=None) -> dict:
    if not spec.get("questions") or not spec.get("prompt"):
        raise WM.MediaError("spec 에 prompt 와 questions 가 있어야 한다")
    R = Run(out, poster)
    roles = assign_roles(spec["questions"], spec.get("roles"))
    R.log("START", {"model": MODEL, "questions": spec["questions"], "roles": roles,
                    "photos": len(spec.get("photos") or []), "material": bool(spec.get("material"))})
    facts = step_facts(R, spec)
    thesis, cands, points = step_thesis(R, spec, facts)
    drafts = step_drafts(R, spec, facts, thesis, roles, int(spec.get("n", 4)), points)
    gates = [gate(d, spec, facts, roles, points) for d in drafts]
    for i, g in enumerate(gates):
        R.log("GATE", {"draft": i + 1, **g})
    best = min(range(len(drafts)), key=lambda i: rank_key(gates[i]))
    final, fg, revised = drafts[best], gates[best], False
    if fg["hard"] or fg["soft"]:
        rv = step_revise(R, spec, final, fg)
        rg = gate(rv, spec, facts, roles, points)
        R.log("GATE", {"draft": "revised", **rg})
        (out / "revised.md").write_text(rv, encoding="utf-8")
        if rank_key(rg) < rank_key(fg):          # 덜 나쁠 때만 바꾼다
            final, fg, revised = rv, rg, True
    (out / "final.md").write_text(final, encoding="utf-8")
    rep = report(spec, facts, thesis, cands, roles, gates, best, fg, revised, R.calls, points)
    (out / "report.md").write_text(rep, encoding="utf-8")
    R.log("END", {"best": best + 1, "revised": revised, "hard": len(fg["hard"]), "soft": len(fg["soft"])})
    return {"final": final, "report": rep, "out": str(out), "gate": fg}


def report(spec, facts, thesis, cands, roles, gates, best, fg, revised, calls, points=None) -> str:
    lines = [f"# 글쓰기 보고 -- 모델 {MODEL} · 응답이 밝힌 모델: {', '.join(sorted(set(calls))) or '미보고'} · 호출 {len(calls)}번",
             "", "**관문은 대리 지표다** -- 오늘 본 실패를 센 것이지 글이 좋다는 판정이 아니다. 고르는 순서: hard -> soft -> 사진 근거.",
             "", "## 사진에서 본 것"]
    lines += [f"- 사진{f['photo']} ({f['by']}): {', '.join(f['facts']) or '(못 뽑음)'}" for f in facts] or ["- (사진 없음)"]
    lines += ["", "## 논지", f"고른 것: **{thesis or '(못 뽑음)'}**", "후보:"] + [f"- {c}" for c in cands]
    pts = points or [{}] * len(spec["questions"])
    lines += ["", "## 문항 역할 · 새 요점"] + [
        f"- Q{i + 1} {q} -> {roles[i]}" + (f" · {pts[i].get('point')} ({', '.join(pts[i].get('words', []))})"
                                            if pts[i].get("point") else "")
        for i, q in enumerate(spec["questions"])]
    lines += ["", "## 초안별 관문", "| 초안 | hard | soft | 사진 근거 | 문항별 글자 |", "|---|---|---|---|---|"]
    lines += [f"| {i + 1}{' ← 고름' if i == best else ''} | {len(g['hard'])} | {len(g['soft'])} | {g['photo_cover']} | "
              f"{' · '.join(map(str, g['answers']))} |" for i, g in enumerate(gates)]
    lines += ["", f"## 최종 ({'고친 판' if revised else '고르기만 함'}) -- hard {len(fg['hard'])} · soft {len(fg['soft'])}"]
    lines += [f"- [hard] {x}" for x in fg["hard"]] + [f"- [soft] {x}" for x in fg["soft"]]
    if fg["hard"]:
        lines += ["", "**hard 가 남았다 -- 이 글은 관문을 통과하지 못했다.** 그대로 내지 마라."]
    lines += ["", "## 사용자만 줄 수 있는 것",
              "글의 '주의할 점' 칸을 본다. 실제 장면 · 옷 · 장소 한 문장을 주면 spec 의 material 에 넣고 다시 돌린다."]
    return "\n".join(lines) + "\n"


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    spec = json.loads(Path(os.path.expanduser(argv[0])).read_text(encoding="utf-8"))
    spec["photos"] = [str(Path(os.path.expanduser(p)).resolve()) for p in spec.get("photos") or []]
    out = Path(os.path.expanduser(spec.get("out") or f"~/well_used_gemini_essays/{time.strftime('%Y%m%d-%H%M%S')}"))
    try:
        r = run(spec, out)
    except WM.MediaError as e:
        print(f"[essay] {WM._hide(str(e))}", file=sys.stderr)
        return 1
    print(r["final"])
    print(f"\n[essay] 관문: hard {len(r['gate']['hard'])} · soft {len(r['gate']['soft'])} · 보고서 {out / 'report.md'}")
    return 0 if not r["gate"]["hard"] else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

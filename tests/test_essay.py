"""글쓰기 파이프라인(wug_essay.py) 시험 -- 가짜 모델로 단계 · 관문 · 고르기 · 고치기를 끝까지 돌린다. 진짜 모델은 안 부른다.

    python3 tests/test_essay.py        (Pillow · requests 가 있는 파이썬 -- setup 의 가상환경)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import wug_essay as E  # noqa: E402

fails = []


def ok(cond, label):
    print(f"    {'OK  ' if cond else '실패'} {label}")
    if not cond:
        fails.append(label)


Q = ["패션은 왜 중요한가?", "나는 왜 패션을 중요하게 생각하는가?", "좋은 패션이란 무엇인가?"]

print("[역할] 문항을 코드로 나눈다")
ok(E.assign_roles(Q) == ["define", "personal", "criterion"], f"정의 · 내 이유 · 기준 ({E.assign_roles(Q)})")
ok(E.assign_roles(Q, ["general"] * 3) == ["general"] * 3, "spec 의 roles 가 이긴다")

print("[요점] 문항끼리 겹치는 낱말은 버린다")
pts = E.clean_points([{"q": 1, "point": "a", "words": ["공간", "층"]}, {"q": 2, "point": "b", "words": ["멈춤", "공간"]},
                      {"q": 3, "point": "c", "words": ["기억"]}, {"q": 9, "point": "x", "words": ["y"]}], 3)
ok([p["words"] for p in pts] == [["층"], ["멈춤"], ["기억"]], f"겹친 '공간' 은 양쪽에서 빠진다 · 범위 밖 q 는 버린다 ({pts})")

FACTS = [{"photo": 1, "words": ["상점 창", "코트"]}, {"photo": 2, "words": ["강가", "파카"]}]
SPEC = {"prompt": "매거진 지원 글", "questions": Q}
POINTS = [{"point": "옷은 첫 공간", "words": ["첫 번째 층"]}, {"point": "멈춤", "words": ["멈춘다"]},
          {"point": "기억", "words": ["기억"]}]


def doc(q1, q2, q3, review="- 샤넬 인용은 확인하지 않았다", caption="불 켜진 상점 창 앞의 코트 · 밤 강가의 파카"):
    return (f"## Q1. x\n{q1}\n\n## Q2. y\n{q2}\n\n## Q3. z\n{q3}\n\n## 사진 캡션\n{caption}\n\n"
            + (f"## 주의할 점\n{review}\n" if review is not None else ""))


GOOD1 = "사람이 가장 먼저 머무는 공간은 옷이다. 옷은 몸과 세상 사이의 첫 번째 층이다. " * 5
GOOD2 = "나는 스타일을 가진 사람 앞에서 멈춘다. 그 사람은 말없이 이야기를 들려준다. " * 5
GOOD3 = "좋은 패션은 기억에 남는다. 그 사람을 떠올리면 함께 떠오른다. " * 6

print("[관문] 오늘 본 실패를 하나씩")
g = E.gate(doc(GOOD1, GOOD2, GOOD3), SPEC, FACTS, E.assign_roles(Q), POINTS)
ok(g["hard"] == [] and g["soft"] == [] and g["photo_cover"] == 2, f"성한 글은 깨끗하다 ({g['hard'] + g['soft']})")
cases = [
    (doc(GOOD1, GOOD2, "좋은 패션을 정의함. 장소와의 접점임." * 8), "메모체", "hard"),
    (doc(GOOD1, "스타일을 가진 사람 앞에서 멈춘다. " * 8, GOOD3), "1인칭 주어가 없다", "hard"),
    (doc(GOOD1, GOOD2, GOOD3, review=None), "'주의할 점' 칸이 없다", "hard"),
    (doc(GOOD1, GOOD2, GOOD3, caption="흑백 사진"), "사진을 하나도", "hard"),
    (doc(GOOD1, GOOD2, '샤넬은 "패션은 건축이다"라고 말했다. ' + GOOD3), "인용에 출처 표시가 없다", "hard"),
    (doc(GOOD1, GOOD2, "좋은 패션은 오래 남는다. 떠올리면 같이 떠오른다. " * 6), "새 요점", "hard"),
    (doc("짧다.", GOOD2, GOOD3), "너무 짧다", "soft"),
    (doc(GOOD1, GOOD2, GOOD3 + " 공기의 밀도와 완벽히 호흡한다."), "추상어", "soft"),
    ("## Q1\n" + GOOD1 + "\n## 주의할 점\nx", "Q2: 답이 없다", "hard"),
]
for text, want, lvl in cases:
    gg = E.gate(text, SPEC, FACTS, E.assign_roles(Q), POINTS)
    ok(any(want in x for x in gg[lvl]), f"{lvl}: {want}")
gq = E.gate(doc(GOOD1, GOOD2, '샤넬은 "패션은 건축이다"라고 말했다(출처 미확인). ' + GOOD3), SPEC, FACTS,
            E.assign_roles(Q), POINTS)
ok(not any("인용" in x for x in gq["hard"]), "'(출처 미확인)' 을 달면 인용은 통과")
gl = E.gate(doc(GOOD1, GOOD2, GOOD3), {**SPEC, "limit": 100}, FACTS, E.assign_roles(Q), POINTS)
ok(any("상한 100자" in x for x in gl["hard"]), "글자 수 상한을 넘으면 hard")

print("[파이프라인] 가짜 모델로 끝까지")
calls = []
BAD = doc("패션은 필터임. 접점임.", "공간의 분위기와 조화.", "정교한 접점.", review=None, caption="사진들처럼")
DRAFTS = {"draft1": BAD, "draft2": doc(GOOD1, GOOD2, GOOD3 + " 공기의 밀도."), "draft3": BAD, "draft4": BAD}


def poster(url, body):
    parts = body["contents"][0]["parts"]
    text = parts[-1]["text"]
    imgs = sum(1 for p in parts if "inline_data" in p)
    if "List only what is visible" in text:
        step, out = "facts", json.dumps({"facts": ["불 켜진 상점 창", "긴 코트"] if len(calls) == 0 else ["밤 강가", "파카"],
                                         "words": ["상점 창", "코트"] if len(calls) == 0 else ["강가", "파카"]})
    elif "논지 후보 5개" in text:
        step, out = "thesis", json.dumps({"candidates": ["옷은 첫 공간이다", "옷은 건축이다(흔한 비유)"], "pick": 0,
                                          "why": "구체적", "points": [{"q": i + 1, **{"point": p["point"], "words": p["words"]}}
                                                                     for i, p in enumerate(POINTS)]})
    elif "아래 글을 고쳐라" in text:
        step, out = "revise", doc(GOOD1, GOOD2, GOOD3)
    else:
        n = sum(1 for c in calls if c["step"].startswith("draft")) + 1
        step, out = f"draft{n}", DRAFTS[f"draft{n}"]
    calls.append({"step": step, "url": url, "imgs": imgs, "text": text, "gen": body.get("generationConfig")})
    return {"modelVersion": "gemini-3-flash-preview-001", "candidates": [{"content": {"parts": [{"text": out}]}}]}


with tempfile.TemporaryDirectory() as tmp:
    T = Path(tmp)
    from PIL import Image
    for i in (1, 2):
        Image.new("RGB", (20, 20), (i * 60, 0, 0)).save(T / f"p{i}.jpg", "JPEG")
    spec = {**SPEC, "photos": [str(T / "p1.jpg"), str(T / "p2.jpg")], "n": 4}
    r = E.run(spec, T / "out", poster, rpm=1000)
    steps = [c["step"] for c in calls]
    ok(steps == ["facts", "facts", "thesis", "draft1", "draft2", "draft3", "draft4", "revise"],
       f"단계 순서: 사실 · 논지 · 초안 4 · 고침 ({steps})")
    ok(all("gemini-3-flash-preview:generateContent" in c["url"] for c in calls), "모든 호출이 모델 하나")
    ok([c["imgs"] for c in calls if c["step"] == "facts"] == [1, 1], "사실은 사진 한 장씩")
    ok(all(c["imgs"] == 2 for c in calls if c["step"].startswith("draft")), "초안에는 사진 두 장이 다 간다")
    ok(calls[0]["gen"] == {"responseMimeType": "application/json"}, "사실 · 논지는 JSON 으로 받는다")
    ok(len({json.dumps(c["gen"]) for c in calls if c["step"].startswith("draft")}) == 4, "초안 넷은 온도가 다르다")
    dp = next(c["text"] for c in calls if c["step"] == "draft1")
    ok("옷은 첫 공간이다" in dp and "새 요점: 멈춤" in dp and "불 켜진 상점 창" in dp and "## 사진 캡션" in dp,
       "초안 지시에 논지 · 문항별 새 요점 · 사진 사실 · 캡션 칸")
    ok("지어내지 마라" in dp, "경험이 없으면 지어내지 말라고 한다")
    ok(not any(w in dp for w in ("hard", "soft", "ABSTRACT", "밀도", "새 글자쌍")), "초안 지시에 관문의 재는 법이 안 실린다")
    rv = next(c["text"] for c in calls if c["step"] == "revise")
    ok("추상어 밀도" in rv and "draft" not in rv, "고침에는 고른 초안의 위반 목록만 간다")
    ok(r["gate"]["hard"] == [] and r["gate"]["soft"] == [], f"고친 판이 덜 나빠서 바꿨다 ({r['gate']})")
    rep = (T / "out" / "report.md").read_text()
    ok("| 2 ← 고름 |" in rep and "고친 판" in rep, "보고서: 초안 2 를 골랐고 고친 판이 최종")
    ok("응답이 밝힌 모델: gemini-3-flash-preview-001" in rep and "호출 8번" in rep, "보고서: 응답이 밝힌 모델 · 호출 수")
    ok("모델(확인 안 됨)" in rep, "모델이 뽑은 사진 사실은 '확인 안 됨' 으로 적는다")
    led = [json.loads(l) for l in (T / "out" / "ledger.jsonl").read_text().splitlines()]
    ok(sum(1 for l in led if l["kind"] == "GATE") == 5, "원장: 초안 넷 + 고친 판의 관문")
    rows = [json.loads(l) for l in (T / "out" / "sched.jsonl").read_text().splitlines()]
    ok(sum(1 for x in rows if x.get("kind") == "done" and x.get("step_kind") == "model") == 8
       and not any(x.get("kind") == "failed" for x in rows), "rlo 원장: 모델 걸음 여덟이 끝나고 실패 0")
    ok((T / "out" / "final.md").read_text().strip() == doc(GOOD1, GOOD2, GOOD3).strip(), "final.md 가 최종 글")

    print("[파이프라인] 고친 판이 더 나쁘면 안 바꾼다 · 사람이 적은 사실이 이긴다")
    calls.clear()
    DRAFTS["draft2"] = doc(GOOD1, GOOD2, GOOD3 + " 공기의 밀도.")

    def worse(url, body):
        out = poster(url, body)
        if calls[-1]["step"] == "revise":
            out["candidates"][0]["content"]["parts"][0]["text"] = BAD
        return out
    spec2 = {**spec, "facts": {"1": ["상점 창|쇼윈도", "코트"], "2": ["강가", "파카"]}}
    r2 = E.run(spec2, T / "out2", worse, rpm=1000)
    ok([c["step"] for c in calls][:2] == ["thesis", "draft1"], "사람이 사실을 적었으면 사실 뽑기 호출이 없다")
    ok(any("밀도" in x for x in r2["gate"]["soft"]) and (T / "out2" / "final.md").read_text().strip() == DRAFTS["draft2"].strip(),
       "고친 판이 더 나쁘면 고른 초안을 그대로 낸다")
    ok("(사람)" in (T / "out2" / "report.md").read_text(), "보고서에 사람이 적은 사실이라고 적는다")

    print("[파이프라인] hard 가 남으면 끝값 3")
    calls.clear()
    for k in DRAFTS:
        DRAFTS[k] = BAD

    def stuck(url, body):
        out = poster(url, body)
        if calls[-1]["step"] == "revise":
            out["candidates"][0]["content"]["parts"][0]["text"] = BAD
        return out
    r3 = E.run(spec2, T / "out3", stuck, rpm=1000)
    ok(r3["gate"]["hard"] and "통과하지 못했다" in (T / "out3" / "report.md").read_text(),
       "hard 가 남으면 보고서가 '통과하지 못했다' 고 적는다")

print("[한도] quota wait 는 실패가 아니다 -- 다시 부르면 끝난 단계는 건너뛰고 이어 한다 (CMD-WUG1 S7)")
import wug_media as WM  # noqa: E402
q = WM.classify_429({"error": {"code": 429, "details": [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}}, "m")
ok(q.scope == "minute" and q.seconds == 37 and "quota wait 37 s" in str(q), f"분당 한도 · retryDelay 37s ({q})")
q = WM.classify_429({"error": {"details": [{"@type": "x/google.rpc.QuotaFailure",
                                            "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}, "m")
ok(q.scope == "day" and q.seconds is None and "하루" in str(q), "하루 한도는 day")
print("[D2] rlo Scheduler: 429 retryDelay 에서 실패 0 · 기다리는 동안 도구 걸음 · 창 뒤에 모델 걸음 (CMD-WUG1 S6)")
from rlo.governor import gemini_429  # noqa: E402


class Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def quota_poster(fail_at: set, delay="30s"):
    """n 번째 모델 호출(1부터)에서 429 -- 같은 걸음을 다시 보내면 통과한다."""
    seen = {"n": 0}

    def p(url, body):
        seen["n"] += 1
        if seen["n"] in fail_at:
            raise WM.classify_429(gemini_429(delay), "gemini-3-flash-preview")
        return poster(url, body)
    return p, seen


with tempfile.TemporaryDirectory() as tmp:
    T = Path(tmp)
    for k in DRAFTS:
        DRAFTS[k] = doc(GOOD1, GOOD2, GOOD3 + " 공기의 밀도.")
    calls.clear()
    clk = Clock()
    qp, seen = quota_poster({3})                          # thesis · draft1 다음, draft2 에서 429
    spec3 = {**SPEC, "n": 4}
    r = E.run(spec3, T / "d2", qp, clock=clk, sleep=clk.sleep, rpm=1000)
    rep_ = r["sched"]
    ok(not rep_.failed and not rep_.skipped and not rep_.parked and r["final"], "실패 0 · 건너뜀 0 · 끝까지 갔다")
    ok(clk.slept and abs(sum(clk.slept) - 30.0) < 1e-6, f"서버가 말한 30 s 만큼 잤다 -- 바쁘게 되풀이하지 않았다 ({clk.slept})")
    rows = [json.loads(l) for l in (T / "d2" / "sched.jsonl").read_text().splitlines()]
    ev = [(x.get("kind"), x.get("step")) for x in rows]
    i_rl = ev.index(("rate_limit", "draft2"))
    i_gate1 = ev.index(("done", "gate1"))
    i_resend = max(i for i, e in enumerate(ev) if e == ("dispatch", "draft2"))
    ok(i_rl < i_gate1 < i_resend, f"draft2 를 세운 동안 gate1(도구)이 돌고, 창 뒤에 draft2 를 다시 보냈다 ({ev[i_rl:i_resend + 1]})")
    ok(seen["n"] == 4 + 2 + 1, f"모델 호출 = 논지 1 + 초안 4 + 다시 보냄 1 + 고침 1 ({seen['n']})")
    disp = [x for x in rows if x.get("kind") == "dispatch"]
    ok(all(x.get("step") in ("thesis", "draft1", "draft2", "draft3", "draft4", "revise") for x in disp),
       "모델 걸음만 dispatch 된다(도구 걸음은 공급자를 안 부른다)")
    ok(all(E.kinds_table()["steps"][x["name"]] in ("model", "tool") for x in rows if x.get("name")),
       "원장의 걸음 이름이 다 단계표에 있다(분류 안 된 걸음 없음)")

    print("[D2] 기다리지 않는 판: 세울 때 상태를 저장하고 quota wait 로 돌아온다 -- 다시 부르면 이어 간다")
    calls.clear()
    clk = Clock()
    qp, seen = quota_poster({3}, delay="45s")
    try:
        E.run(spec3, T / "nw", qp, wait=False, clock=clk, sleep=clk.sleep, rpm=1000)
        ok(False, "QuotaParked 가 나야 한다")
    except E.QuotaParked as q:
        ok("quota wait 45 s" in str(q) and (T / "nw" / "state.json").is_file(), f"quota wait 45 s · 상태 저장 ({str(q)[:60]})")
    ok(clk.slept == [], "기다리지 않는 판은 자지 않는다")
    first = seen["n"]
    clk.t += 45
    qp2, seen2 = quota_poster(set())
    r = E.run(spec3, T / "nw", qp2, wait=False, clock=clk, sleep=clk.sleep, rpm=1000)
    ok(r["final"] and first == 3 and seen2["n"] == 4, f"다시 띄운 프로세스가 남은 걸음만 보낸다(처음 {first} · 이어서 {seen2['n']})")
    ok("QUOTA_PARKED" in (T / "nw" / "ledger.jsonl").read_text(), "원장에 QUOTA_PARKED")

    print("[D2] 지킴이: 예산이 비면 모델 걸음은 보내지 않는다(분당 2) -- 그동안 도구 걸음은 돈다")
    calls.clear()
    clk = Clock()
    qp, seen = quota_poster(set())
    r = E.run(spec3, T / "rpm", qp, clock=clk, sleep=clk.sleep, rpm=2)
    rows = [json.loads(l) for l in (T / "rpm" / "sched.jsonl").read_text().splitlines()]
    ts = sorted(x["at_ms"] / 1000 for x in rows if x.get("kind") == "dispatch")
    worst = max(sum(1 for u in ts if t <= u < t + 60) for t in ts)
    ok(r["final"] and len(ts) == 6 and worst <= 2, f"모델 호출 6번, 어느 60 초 창에도 2번 이하 ({worst}) · 실패 0")
    ok(not r["sched"].failed and clk.slept and all(x > 0 for x in clk.slept), f"기다림은 잠으로(바쁜 되풀이 없음) · {len(clk.slept)}번 잤다")
    ev = [(x.get("kind"), x.get("step")) for x in rows]
    first_park = next(i for i, e in enumerate(ev) if e[0] == "park")
    ok(any(e[0] == "done" and e[1].startswith("gate") for e in ev[first_park:]), "세운 뒤에도 도구 걸음(gate)이 돈다")

    print("[D2] 하루 한도: 무한 대기는 기다리지 않고 세워 둔 채 돌아온다")
    clk = Clock()
    def day(url, body):
        raise WM.classify_429(gemini_429(None, per="Day"), "gemini-3-flash-preview")
    try:
        E.run(spec3, T / "day", day, wait=False, clock=clk, sleep=clk.sleep, rpm=1000)
        ok(False, "QuotaParked")
    except E.QuotaParked as q:
        ok("다음 날" in str(q), f"하루 한도 -> 다음 날까지 ({str(q)[:50]})")

ok(E.spec_key({"prompt": "a", "questions": ["q"]}) == E.spec_key({"questions": ["q"], "prompt": "a", "out": "x"})
   and E.spec_key({"prompt": "a", "questions": ["q"]}) != E.spec_key({"prompt": "a", "questions": ["q"], "fresh": 1}),
   "같은 요청이면 같은 자리 · fresh 로 새 자리")

print()
if fails:
    print(f"essay: {len(fails)}개 실패 -- {fails}")
    sys.exit(1)
print("essay: 역할 · 요점 · 관문 아홉 · 단계 순서 · 고르기 · 고치기(덜 나쁠 때만) · 원장 -- 통과")

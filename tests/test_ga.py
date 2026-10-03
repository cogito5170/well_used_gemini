"""ga · rlo 연결 시험(CMD-WUG1 S6 · S10) -- ga-sdk 가 깔린 가상환경 파이썬으로 돌린다.

    ~/.cache/well_used_gemini/venv/bin/python tests/test_ga.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
fails = []


def ok(cond, label):
    print(f"    {'OK  ' if cond else '실패'} {label}")
    if not cond:
        fails.append(label)


import wug  # noqa: E402
import wug_essay as E  # noqa: E402
import wug_mcp  # noqa: E402
from ga import gemini as G  # noqa: E402
from rlo.scheduler import load_step_kinds  # noqa: E402

print("[S6] steps.json 은 rlo 의 닫힌 걸음 표로 실린다")
k = load_step_kinds(E.kinds_table())
ok(set(k.values()) == {"model", "tool"} and k["essay.draft"] == "model" and k["essay.gate"] == "tool", "rlo-step-kinds/1 · model | tool")

print("[S10] ga gemini 설정: 모델 고정 · 도구 걸음만 · ga 의 검사를 통과")
c = wug.ga_config()
ok(G.config_problems(c) == [], f"ga config_problems 없음 ({G.config_problems(c)})")
ok(c["model"] == "gemini-3-flash-preview" and c["budget"] == {"rpm": wug.GA_RPM}, "모델 하나 · 지킴이 예산")
names = {t["tool"] for t in c["tools"].values()}
model_tools = {x["id"][4:] for x in json.loads((ROOT / "steps.json").read_text())["steps"]
               if x["id"].startswith("mcp.") and x["kind"] == "model"}
ok(names and not (names & model_tools), f"모델을 스스로 부르는 도구는 도구 걸음에 없다 ({sorted(names & model_tools)})")
ok(names <= {t["name"] for t in wug_mcp.TOOLS}, "도구 표의 이름이 다 우리 MCP 도구다")
ok(c["mcp_servers"]["wug"]["command"][-1].endswith("wug_mcp.py"), "MCP 서버는 우리 것")

print()
if fails:
    print(f"ga: {len(fails)}개 실패 -- {fails}")
    sys.exit(1)
print("ga: 걸음 표 · ga gemini 설정 -- 통과")

# well_used_gemini

Gemini 를 **런타임이 판정하는 게이트 뒤에서** 돌리는 얇은 진입점이다. 실제 일은
[`cogito5170/se_new`](https://github.com/cogito5170/se_new) 의 `agentic/` 이 한다. 여기서는 그것을
**고정된 커밋**(`se_new.lock`)으로 받아 와서 부르기만 한다.

| 무엇 | 어디서 |
|---|---|
| 모델 하나(`gemini-3.1-flash-lite`) · 폴백 없음 · 응답이 밝힌 모델 대조 | se_new `agentic/model.py` |
| 상태·루프·Gate01·MCP 칸은 **원장에서만** 그림. 모델이 쓴 깃발은 위조로 거절 | `agentic/render.py` · `agentic/forgery.py` |
| WALP 앞단(잡담은 모델 호출 0) → 제어부(등록 도구, LLM 없는 라우팅) → 사고부(ReAct · 루프 탐지기) | `agentic/front.py` · `controller.py` · `thinker.py` |
| 도구는 sandbox(HEAD 워크트리)에서만 · 회로 차단기 · 수리 요청 | `agentic/tools.py` · `breaker.py` |
| MCP 버전 세 갈래(protocol · sdk · server) · RAG/Graph 기억 | `agentic/mcp_client.py` · `memory.py` |

> 처음 받은 답의 "MCP version: 0.46.0" 은 **Gemini CLI 의 버전**이었다(CLI 업데이트 알림: 0.46.0 → 0.62.0).
> MCP 의 프로토콜·SDK·서버 버전이 아니다. 이 저장소는 그 셋을 서버가 실제로 말한 대로 따로 적는다.

## 0. 파이썬 3.10 이상

se_new 의 WALP 코드가 `int.bit_count()`(3.10 부터)를 쓴다. macOS 기본 `python3` 는 3.9 다.

```bash
brew install python@3.12        # 'brew install python 3.10' 은 안 된다 -- 버전은 이름에 붙인다
```

깔기만 하면 된다. `wug.py` 는 3.9 로 띄워도 **3.10 이상 파이썬을 스스로 찾아 갈아탄다**(PATH 의 python3.1x,
`/opt/homebrew/bin`, `/usr/local/bin`). setup 뒤에는 가상환경의 파이썬으로 갈아탄다 -- Gemini CLI 가 훅과 MCP 서버를
기본 `python3`(3.9)로 띄워도 그렇다.

## 1. Gemini CLI 확장으로 설치

```bash
gemini extensions install https://github.com/cogito5170/well_used_gemini --ref claude/ecstatic-edison-oortg1
```

- "Do you trust the files in this folder?" 가 나오면 `y` (확장의 MCP 서버·훅을 돌리려면 필요하다)
- "Gemini API Key" 를 물으면 넣는다(시스템 키체인에 저장). 건너뛰었으면:
  `gemini extensions config well-used-gemini "Gemini API Key"`
- 처음 한 번 준비(se_new 를 고정 커밋으로 받고 가상환경에 `requests`):

```bash
python3 ~/.gemini/extensions/well-used-gemini/wug.py setup
python3 ~/.gemini/extensions/well-used-gemini/wug.py doctor     # 점검을 실제로 돌린다
```

그다음 Gemini CLI 를 다시 띄우면 이것들이 붙는다:

| 무엇 | 하는 일 |
|---|---|
| MCP 도구 `agentic_run(question)` | 물음을 파이프라인으로 끝까지. **런타임 보고서**를 돌려준다 |
| `agentic_setup` · `agentic_doctor` · `agentic_versions` | 준비 · 점검 · 고정 커밋/모델/MCP 버전 |
| 훅 `BeforeAgent` (WALP 앞단) | 인사·감사 같은 잡담은 모델에 안 보내고 WALP 가 답한다. 일이 담긴 말이었다면 앞에 `//` |
| 훅 `AfterAgent` (깃발 게이트) | CLI 의 답에 상태·게이트·루프·버전 주장이 있으면 버리고 다시 쓰게 한다. 다시 써도 남으면 경고 |
| `GEMINI.md` | "일은 agentic_run 으로, 상태·버전은 쓰지 마라" |

## 2. 터미널에서 바로

```bash
git clone -b claude/ecstatic-edison-oortg1 https://github.com/cogito5170/well_used_gemini
cd well_used_gemini
python3 wug.py setup
export GEMINI_API_KEY=...            # 또는 이 폴더의 .env 에 GEMINI_API_KEY=... (git 에 안 올라간다)
python3 wug.py doctor
python3 wug.py run "//안녕"           # '//' = 잡담 앞단을 건너뛰고 Gemini 를 진짜로 부른다
python3 wug.py run "CTLE 가 뭐야"
python3 wug.py versions
```

`run` 의 끝값: 0 = DONE, 그 밖 = 그 상태(BLOCKED · NEEDS_REVIEW · LOOP_LIMIT_REACHED · …).

## 확인한 것 · 못 한 것

**확인함**(이 저장소를 만든 세션에서 실제로 돌림):
- `setup` -- 진짜 se_new 를 고정 커밋으로 받고 가상환경을 만듦(약 8초). `doctor` 4/4
- 확장 MCP 서버 -- MCP 클라이언트로 붙어 도구 넷 · `agentic_run` 이 런타임 보고서를 돌려줌
- **Gemini CLI 0.46.0 에 실제로 설치** -- `gemini extensions list` 에 MCP 서버·컨텍스트·키 설정이 잡힘
- **Gemini CLI 0.46.0 안에서 `BeforeAgent` 훅이 발동** -- `gemini -p "고마워"` 에 WALP 가 답했고 모델 호출 0
- `tests/test_wug.py` -- 가짜 상류를 지어 끝까지 돌림 · 일곱 가지 코드 변이 모두 빨간불

**못 함:**
- **진짜 Gemini 호출은 0 건** -- 키가 없는 자리에서 만들었다. 첫 실행의 `모델:` 줄(확인됨 / 미확인 / 불일치)이 처음 확인이다
- `AfterAgent` 훅을 **Gemini CLI 안에서** 발동시켜 보지 못했다(모델의 진짜 답이 있어야 발동한다). 훅 단독으로만 확인
- macOS 에서 돌려 보지 않았다. sandbox 의 메모리 상한은 macOS 에서 걸리지 않을 수 있다(설정 실패를 넘어가게 짜여 있다)
- Gemini CLI 가 MCP 도구 결과를 화면에 얼마나 보여 주는지 확인하지 않았다

**알려진 약점:** WALP 앞단은 일이 섞인 말("고마워요 이제 머지해줘")을 잡담으로 삼킨다(WALP 저장소가 잰 것: 60 문장 중 9~10).
그래서 잡담으로 답할 때마다 `//` 로 건너뛰는 법을 보인다. 끄려면 `WUG_FRONT=0`.

## se_new 버전 올리기

`se_new.lock` 의 `commit` 을 바꾸는 커밋을 낸다. `setup` 이 새 커밋을 새 자리(`~/.cache/well_used_gemini/se_new-<커밋>`)에
받는다 -- 옛 자리는 안 건드린다. 받아 온 se_new 에 커밋 안 된 변경이 있으면 `setup` 이 멈춘다(덮어쓰지 않는다).

```bash
python3 tests/test_wug.py
```

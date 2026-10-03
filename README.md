# well_used_gemini

Gemini 를 **런타임이 판정하는 게이트 뒤에서** 돌리는 얇은 진입점이다. 실제 일은
[`cogito5170/se_new`](https://github.com/cogito5170/se_new) 의 `agentic/` 이 한다. 여기서는 그것을
**고정된 커밋**(`se_new.lock`)으로 받아 와서 부르기만 한다.

| 무엇 | 어디서 |
|---|---|
| 모델 하나(`gemini-3-flash-preview`) · 폴백 없음 · 응답이 밝힌 모델 대조 | se_new `agentic/model.py` · 이 저장소 `wug_model.py` |
| 상태·루프·Gate01·MCP 칸은 **원장에서만** 그림. 모델이 쓴 깃발은 위조로 거절 | `agentic/render.py` · `agentic/forgery.py` |
| 제어부(등록 도구, LLM 없는 라우팅) → 사고부(ReAct · 루프 탐지기). WALP 앞단은 2026-10-02 에 뺐다 | `controller.py` · `thinker.py` |
| 도구는 sandbox(HEAD 워크트리)에서만 · 회로 차단기 · 수리 요청 | `agentic/tools.py` · `breaker.py` |
| MCP 버전 세 갈래(protocol · sdk · server) · RAG/Graph 기억 | `agentic/mcp_client.py` · `memory.py` |

> 처음 받은 답의 "MCP version: 0.46.0" 은 **Gemini CLI 의 버전**이었다(CLI 업데이트 알림: 0.46.0 → 0.62.0).
> MCP 의 프로토콜·SDK·서버 버전이 아니다. 이 저장소는 그 셋을 서버가 실제로 말한 대로 따로 적는다.

## 0. 파이썬 3.10 이상

se_new 의 `walp/grownet.py` 가 `int.bit_count()`(3.10 부터)를 쓴다. macOS 기본 `python3` 는 3.9 다.

```bash
brew install python@3.12
```

(`brew install python 3.10` 은 안 된다 -- 버전은 이름에 붙인다.)

깔기만 하면 된다. `wug.py` 는 3.9 로 띄워도 **3.10 이상 파이썬을 스스로 찾아 갈아탄다**(PATH 의 python3.1x,
`/opt/homebrew/bin`, `/usr/local/bin`). setup 뒤에는 가상환경의 파이썬으로 갈아탄다 -- Gemini CLI 가 훅과 MCP 서버를
기본 `python3`(3.9)로 띄워도 그렇다.

**처음 한 번은 느리다.** 도구를 sandbox 안에서 돌리려고 se_new 의 의존성(21개)을 `~/.cache/se-sandbox-deps` 에
파이썬 버전마다 따로 깐다(여기서 잰 것: 약 2분 30초). 그 뒤로는 캐시를 쓴다. 예전 판이 깐 캐시(이름에
`cpython-3xx` 가 없는 자리)는 쓰이지 않는다 -- 지워도 된다: `rm -rf ~/.cache/se-sandbox-deps`

## 1. Gemini CLI 확장으로 설치

```bash
gemini extensions install https://github.com/cogito5170/well_used_gemini --ref claude/ecstatic-edison-oortg1
```

- "Do you trust the files in this folder?" 가 나오면 `y` (확장의 MCP 서버·훅을 돌리려면 필요하다)
- **설치 때 키를 묻지 않는다**(0.3.0 부터). 키는 이 차례로 찾는다:
  1. 환경 변수  2. `~/.cache/well_used_gemini/keys.env` (`wug.py key` 가 쓴다 · 권한 600 · **재설치해도 남는다**)
  3. 확장 폴더의 `.env`  4. `~/.gemini/.env` (Gemini CLI 가 읽는 그 파일)  5. GitHub 토큰만: `gh auth token`
- 키를 한 번만 저장한다(입력이 화면에 안 보인다):

```bash
python3 ~/.gemini/extensions/well-used-gemini/wug.py key
python3 ~/.gemini/extensions/well-used-gemini/wug.py key github
```

첫 줄은 Gemini API 키, 둘째 줄은 선택(비공개 저장소 · `gh_search`). **명령 줄에 `# 설명` 을 붙여 붙여넣지 마라** --
zsh 는 기본으로 `#` 를 주석으로 안 읽어서 `(…)` 가 든 설명이 `unknown file attribute` 로 터진다(실측 2026-10-02).

  GitHub 토큰은 fine-grained(저장소 cogito5170/*, Contents: Read-only · Metadata: Read-only)면 된다. 없으면 공개 저장소만.
- 처음 한 번 준비(se_new 를 고정 커밋으로 받고 가상환경에 `requests`):

```bash
python3 ~/.gemini/extensions/well-used-gemini/wug.py setup
python3 ~/.gemini/extensions/well-used-gemini/wug.py doctor
```

그다음 Gemini CLI 를 다시 띄우면 이것들이 붙는다:

| 무엇 | 하는 일 |
|---|---|
| MCP 도구 `agentic_run(question)` | 물음을 파이프라인으로 끝까지. **런타임 보고서**를 돌려준다 |
| `agentic_setup` · `agentic_doctor` · `agentic_versions` | 준비 · 점검 · 고정 커밋/모델/MCP 버전 |
| `agentic_tools` · `agentic_runs(limit)` · `agentic_report(run_id)` | 등록 도구 · 최근 실행(원장의 끝 상태) · 한 실행의 보고서 |
| `agentic_memory(query)` · `agentic_repairs` | RAG 기억에서 꺼낸 메모(신뢰 안 함) · 수리 요청 대기열 |
| `media_info` · `media_ask(paths, question)` | **사진·PDF 받기**: 경로를 주면(터미널에 파일을 끌어다 놓으면 경로가 들어간다) 꼴·해상도·쪽 수, 그리고 Gemini 가 그 파일을 읽고 답한다 |
| `image_generate(prompt, references, formats, aspect_ratio)` | **그림 만들기**: 이미지 모델로 만들어 jpg · jpeg · png · webp · pdf 로 저장하고 macOS 면 연다. 참고 사진을 같이 줄 수 있다 |
| `media_convert(paths, format, combine)` | 사진 -> jpg/png/pdf · 여러 장을 PDF 한 권으로 · PDF -> 쪽마다 사진 |
| `gh_repos` · `gh_tree` · `gh_read` · `gh_commits` · `gh_search` | **cogito5170 저장소 읽기만**. 다른 소유자 · `..` 경로는 요청 전에 거절. 결과 머리에 '신뢰 안 함' |
| 훅 `AfterAgent` (깃발 게이트) | CLI 의 답에 상태·게이트·루프·버전 주장이 있으면 버리고 다시 쓰게 한다. 다시 써도 남으면 경고 |
| `GEMINI.md` | "일은 agentic_run 으로, 상태·버전은 쓰지 마라" |

### 사진·PDF

- 저장 자리: `~/Pictures/well_used_gemini/` (`WUG_OUT` 으로 바꾼다). 같은 이름이 있으면 `-2` 를 붙인다 -- 덮어쓰지 않는다
- 이미지 모델 이름은 **적어 두지 않았다.** 키로 API 의 모델 목록을 읽어 `generateContent` 를 받는 `image` 모델을 고른다
  (미리보기가 아닌 것 먼저). 직접 정하려면 `WUG_IMAGE_MODEL`. 보고서에는 **응답이 밝힌 모델**을 적는다
- 그림도 **같은 모델 하나**(`wug_model.MODEL`)로 만든다 -- 목록에서 이미지 모델을 고르지 않는다(폴백 없음). 그 모델이 그림을 못 내면
  `no_image_returned` 로 그대로 실패한다. 진짜 호출로는 아직 확인하지 못했다
- 처음 쓸 때 Pillow · pypdfium2 를 가상환경에 스스로 깐다(사람이 깔 것 없음)
- 한 요청에 싣는 원본은 18MB 까지(넘으면 보내기 전에 막는다). HEIC 는 읽기(`media_ask`)만 되고 변환은 안 된다

### 글쓰기 파이프라인 (`essay_write` · `wug.py essay`)

모델 하나(`gemini-3-flash-preview`)의 바깥에 단계를 친다. 판정은 코드가 한다.

1. **사진 사실** -- 사진마다 보이는 것만 JSON 으로(spec 에 사람이 `facts` 를 적으면 그것이 이긴다)
2. **문항 역할** -- 코드가 나눈다: "왜 중요한가" -> 정의 · "나는 왜" -> 내 이유 · "좋은 ~란" -> 기준
3. **논지** -- 후보 5개 중 하나, 그리고 문항마다 **서로 다른 새 요점**과 그 낱말
4. **초안 N벌**(기본 4, 온도를 달리) -- 초안 지시에는 관문이 재는 법을 싣지 않는다
5. **관문(코드)** -- hard: 답 없음 · 글자 수 상한 · 메모체 · '내 이유' 에 1인칭 없음 · 출처 표시 없는 인용 ·
   새 요점 낱말 없음 · 사진을 하나도 안 씀 · '주의할 점' 없음 / soft: 짧음 · 추상어 · 사진 한 장을 안 씀
6. **한 번 고침** -- 고른 초안의 위반 목록만 돌려보내고, 고친 판이 **덜 나쁠 때만** 바꾼다

결과: `~/well_used_gemini_essays/<시각>/` 에 `final.md` · `report.md`(초안별 관문 표) · `ledger.jsonl`(호출마다 응답이
밝힌 모델) · 초안들. hard 가 남으면 끝값 3 이고 보고서가 "통과하지 못했다" 고 적는다. 호출은 사진 수 + 1 + N + 1 번.

- 사용자의 경험은 **지어내지 않는다.** `material` 에 실제 경험을 주면 그 안에서만 쓰고, 없으면 '주의할 점' 에서 묻는다
- 관문은 대리 지표다. 오늘의 두 답(Opus · flash-lite 본문)에 돌려 보니 **가른 것**: 글자 수 · 추상어(목록 일부가 그 답에서
  나와 순환이다) · 검토 칸. **못 가른 것**: 글자쌍 겹침으로 잰 되풀이(같은 생각을 다른 말로 쓴 것을 못 잡았다 -- 그래서
  빼고 '문항별 새 요점' 으로 바꿨다) · 메모체(두 본문 다 ~다 였다. 메모체는 Gemini 의 머리말에만 있었다)

### 모델 -- 하나, 폴백 없음 · Gemini CLI 0.62.0 (사용자 결정 2026-10-03)

모든 부분(agentic · 묻기 · 그림 · 글쓰기 · 실험 · CLI 기본값)이 `gemini-3-flash-preview` 하나다. 이름은 `wug_model.py`
한 곳에 있고, 환경 변수로 바꾸는 길은 없다. se_new 의 `agentic/config.json` 도 같은 이름이다(`doctor` 가 맞춰 본다).

```bash
npm install -g @google/gemini-cli@0.62.0
python3 ~/.gemini/extensions/well-used-gemini/wug.py model gemini-3-flash-preview
python3 ~/.gemini/extensions/well-used-gemini/wug.py doctor
```

`wug.py model` 은 키로 API 에 그 이름이 있고 generateContent 를 받는지 확인한 뒤에만 `~/.gemini/settings.json` 을 바꾼다
(옛 파일은 `.bak-<시각>`). 바꾸는 것: `model.name` · 그리고 **폴백 사슬을 이 모델 하나로 묶는 칸**
(`experimental.dynamicModelConfiguration: true` · `modelConfigs.modelChains`).

Gemini CLI 0.62.0 코드와 진짜 번들로 확인한 것:
- `gemini-3-flash-preview` 는 바꿔 치지 않는다. (0.61 부터 `gemini-3.1-flash-lite` 는 API 키 인증에서 늘
  `gemini-3.5-flash-lite` 로 바뀐다 -- 그래서 이 이름을 안 쓴다)
- 그런데 Gemini 3 모델의 폴백 사슬은 돌아 감긴다: flash-preview 가 막히면 `gemini-3.1-pro-preview` 를 내민다
  (코드 주석: "fallback to Pro if Flash is exhausted"). 위의 사슬 칸이 그것을 막는다
- 헤드리스(`-p`)에서 하루 한도 429 를 가짜 API 로 일으켜 보았다: 기본 설정 · 묶은 설정 둘 다 **flash-preview 한 번만 부르고 멈췄다**
- **대화형 모드에서 사슬 칸이 '다른 모델로 바꿀까요' 를 정말 없애는지는 못 돌려 봤다**(대화형은 여기서 못 띄운다)
- 0.62.0 은 API 키를 쓰려면 `settings.json` 에 `"security": {"auth": {"selectedType": "gemini-api-key"}}` 가 있어야 했다
  (없으면 "Invalid auth method selected." · 끝값 41). 구글 계정으로 로그인해 쓰고 있다면 해당 없다

### 글쓰기 모드 · 글쓰기 실험

Gemini CLI 의 기본 지시문은 코딩용이다(0.46.0 · 0.62.0 `prompts/snippets.js`: "an interactive CLI agent specializing in
software engineering tasks" · "Minimal Output: Aim for fewer than 3 lines"). 지원서 · 매거진 글이 짧은 메모체로
나오는 까닭 하나가 이것이다. 글을 쓸 때는 이렇게 띄운다:

```bash
python3 ~/.gemini/extensions/well-used-gemini/wug.py write
```

`GEMINI_SYSTEM_MD=writing/system.md` 로 기본 지시문만 바꾸고, 확장 도구 · GEMINI.md 는 그대로 붙는다. 지시문이 하는 일:
사진에서 실제로 보이는 것을 쓴다 · 논지 하나 · 문항마다 다른 역할 · 1인칭 평서문(메모체 없음) · 끝에 '주의할 점'
(상투구 · 출처 미확인 인용 · 사용자만 줄 수 있는 것). 사용자의 삶을 지어내지 않는다.

**실험**(`wug.py bench`) -- 같은 요청 · 같은 사진 · **같은 모델**로 세 조건을 N 번씩 돌려 차이가 어디서 오는지 가른다:

| 조건 | 무엇 | 가르는 것 |
|---|---|---|
| a | Gemini CLI 그대로(`-m gemini-3-flash-preview`) | a−b = 지시문의 몫 |
| b | Gemini CLI + 글쓰기 모드 | b−c = CLI 배관(사진 붙이기 · 도구 · GEMINI.md)의 몫 |
| c | API 직접 · 같은 글쓰기 지시문 · 사진 inline | |

```bash
cp ~/.gemini/extensions/well-used-gemini/bench/example.json ~/Desktop/spec.json
python3 ~/.gemini/extensions/well-used-gemini/wug.py bench ~/Desktop/spec.json
```

`spec.json` 에는 실제로 보냈던 요청 원문(`prompt`), 사진 경로, 그리고 **사람이 사진을 보고 적은** `facts` 를 넣는다.
결과는 `~/well_used_gemini_bench/<시각>/` 에 `report.md`(코드로 센 대리 지표) · `blind.md`(출처를 가린 글) ·
`key.json`(열쇠) · `raw/`. 기본 3번 × 4조건 = API 호출 12번 남짓이다.

- 대리 지표(글자 · 사진 사실 · 메모체 비율 · 추상어 · 검토 표지)는 **증상을 센 것이지 글의 질이 아니다.** 질은
  blind.md 를 읽고 순위를 매긴 뒤 key.json 으로 푼다
- `facts` 와 추상어 목록은 사람이 정한다. 오늘의 두 답에서 뽑은 목록으로 그 두 답을 재면 갈리는 것이 당연하다
  (순환) -- 새 실험의 글에 대해서만 뜻이 있다
- a·b 는 설치된 확장을 그대로 쓴다(깃발 게이트 · GEMINI.md 가 같이 돈다). 그것이 '지금 쓰는 그대로' 다

## 2. 터미널에서 바로

```bash
git clone -b claude/ecstatic-edison-oortg1 https://github.com/cogito5170/well_used_gemini
cd well_used_gemini
python3 wug.py setup
export GEMINI_API_KEY=...
python3 wug.py doctor
python3 wug.py run "안녕"
python3 wug.py run "CTLE 가 뭐야"
python3 wug.py versions
python3 wug.py media generate '{"prompt": "...", "formats": ["jpg","pdf"]}'
python3 wug.py inspect runs 5
```

키는 `export` 대신 이 폴더의 `.env` 에 `GEMINI_API_KEY=...` 로 둬도 된다
(git 에 안 올라간다). `inspect` 는 `runs` · `tools` · `report <id>` · `memory "물음"` · `repairs`.

`run` 의 끝값: 0 = DONE, 그 밖 = 그 상태(BLOCKED · NEEDS_REVIEW · LOOP_LIMIT_REACHED · …).

## 확인한 것 · 못 한 것

**확인함**(이 저장소를 만든 세션에서 실제로 돌림):
- `setup` -- 진짜 se_new 를 고정 커밋으로 받고 가상환경을 만듦(약 8초). `doctor` 4/4
- 확장 MCP 서버 -- MCP 클라이언트로 붙어 도구 넷 · `agentic_run` 이 런타임 보고서를 돌려줌
- **Gemini CLI 0.46.0 에 실제로 설치** -- `gemini extensions list` 에 MCP 서버·컨텍스트·키 설정이 잡힘
- `tests/test_wug.py` -- 가짜 상류를 지어 끝까지 돌림 · 일곱 가지 코드 변이 모두 빨간불

- 사진·PDF 도구(`tests/test_media.py`) -- 가짜 Gemini 서버를 띄워 진짜 HTTP 길로 받기·내보내기·형식 넷을 돌림.
  파일은 바이트로 확인(jpg 머리 · `%PDF` · 쪽 수). 코드 변이 여섯 모두 빨간불

- 글쓰기 모드 · 실험(`tests/test_bench.py`) -- 가짜 `gemini` · 가짜 API 로 조건 끝까지, 코드 변이 여섯 모두 빨간불.
  그리고 **진짜 Gemini CLI 0.46.0 번들**을 가짜 응답(`--fake-responses-non-strict`)으로 돌려: 기본 지시문에는
  "fewer than 3 lines" 가 있고 글쓰기 모드에서는 사라진다(`GEMINI_WRITE_SYSTEM_MD` 로 뽑아 봄) · `-p` 에서
  `@photo1.jpg` 가 `inlineData image/jpeg` 로 실린다 · `-o json` 의 `stats.models` 키가 응답이 밝힌 모델이다

**못 함:**
- **진짜 이미지 모델 호출은 0 건**(여기에 키가 없다). 모델 목록에 image 모델이 실제로 뜨는지, `imageConfig.aspectRatio` 를
  받는지, 응답이 `inlineData` 로 오는지는 첫 실행이 처음 확인이다. 실패하면 `http_400:...` 처럼 API 의 말을 그대로 보인다
- **진짜 Gemini 호출은 0 건** -- 키가 없는 자리에서 만들었다. 첫 실행의 `모델:` 줄(확인됨 / 미확인 / 불일치)이 처음 확인이다
- `AfterAgent` 훅을 **Gemini CLI 안에서** 발동시켜 보지 못했다(모델의 진짜 답이 있어야 발동한다). 훅 단독으로만 확인
- macOS 에서 돌려 보지 않았다. sandbox 의 메모리 상한은 macOS 에서 걸리지 않을 수 있다(설정 실패를 넘어가게 짜여 있다)
- Gemini CLI 가 MCP 도구 결과를 화면에 얼마나 보여 주는지 확인하지 않았다

**WALP 앞단(잡담 가로채기)은 2026-10-02 사용자 요청으로 뺐다** -- 훅 · se_new 의 agentic/front.py 둘 다.

## 확장 올리기

```bash
gemini extensions uninstall well-used-gemini
gemini extensions install https://github.com/cogito5170/well_used_gemini --ref claude/ecstatic-edison-oortg1
```

(`gemini extensions update` 는 "already up to date" 를 애매하게 낸 적이 있어 지우고 다시 까는 길을 적는다.
받아 온 se_new 와 가상환경은 확장 폴더 밖이라 그대로 남는다.)

## se_new 버전 올리기

`se_new.lock` 의 `commit` 을 바꾸는 커밋을 낸다. `setup` 이 새 커밋을 새 자리(`~/.cache/well_used_gemini/se_new-<커밋>`)에
받는다 -- 옛 자리는 안 건드린다. 받아 온 se_new 에 커밋 안 된 변경이 있으면 `setup` 이 멈춘다(덮어쓰지 않는다).

```bash
python3 tests/test_wug.py
```

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
| 훅 `BeforeAgent` (WALP 앞단) | 인사·감사 같은 잡담은 모델에 안 보내고 WALP 가 답한다. 일이 담긴 말이었다면 앞에 `//` |
| 훅 `AfterAgent` (깃발 게이트) | CLI 의 답에 상태·게이트·루프·버전 주장이 있으면 버리고 다시 쓰게 한다. 다시 써도 남으면 경고 |
| `GEMINI.md` | "일은 agentic_run 으로, 상태·버전은 쓰지 마라" |

### 사진·PDF

- 저장 자리: `~/Pictures/well_used_gemini/` (`WUG_OUT` 으로 바꾼다). 같은 이름이 있으면 `-2` 를 붙인다 -- 덮어쓰지 않는다
- 이미지 모델 이름은 **적어 두지 않았다.** 키로 API 의 모델 목록을 읽어 `generateContent` 를 받는 `image` 모델을 고른다
  (미리보기가 아닌 것 먼저). 직접 정하려면 `WUG_IMAGE_MODEL`. 보고서에는 **응답이 밝힌 모델**을 적는다
- 이 그림 생성은 se_new 의 게이트 파이프라인 **밖**이다 -- 고정 모델(flash-lite) 정책과 다른 모델을 쓴다. 그래서 보고에 모델을 따로 적는다
- 처음 쓸 때 Pillow · pypdfium2 를 가상환경에 스스로 깐다(사람이 깔 것 없음)
- 한 요청에 싣는 원본은 18MB 까지(넘으면 보내기 전에 막는다). HEIC 는 읽기(`media_ask`)만 되고 변환은 안 된다

## 2. 터미널에서 바로

```bash
git clone -b claude/ecstatic-edison-oortg1 https://github.com/cogito5170/well_used_gemini
cd well_used_gemini
python3 wug.py setup
export GEMINI_API_KEY=...
python3 wug.py doctor
python3 wug.py run "//안녕"
python3 wug.py run "CTLE 가 뭐야"
python3 wug.py versions
python3 wug.py media generate '{"prompt": "...", "formats": ["jpg","pdf"]}'
python3 wug.py inspect runs 5
```

`//` 는 잡담 앞단을 건너뛰고 Gemini 를 진짜로 부른다. 키는 `export` 대신 이 폴더의 `.env` 에 `GEMINI_API_KEY=...` 로 둬도 된다
(git 에 안 올라간다). `inspect` 는 `runs` · `tools` · `report <id>` · `memory "물음"` · `repairs`.

`run` 의 끝값: 0 = DONE, 그 밖 = 그 상태(BLOCKED · NEEDS_REVIEW · LOOP_LIMIT_REACHED · …).

## 확인한 것 · 못 한 것

**확인함**(이 저장소를 만든 세션에서 실제로 돌림):
- `setup` -- 진짜 se_new 를 고정 커밋으로 받고 가상환경을 만듦(약 8초). `doctor` 4/4
- 확장 MCP 서버 -- MCP 클라이언트로 붙어 도구 넷 · `agentic_run` 이 런타임 보고서를 돌려줌
- **Gemini CLI 0.46.0 에 실제로 설치** -- `gemini extensions list` 에 MCP 서버·컨텍스트·키 설정이 잡힘
- **Gemini CLI 0.46.0 안에서 `BeforeAgent` 훅이 발동** -- `gemini -p "고마워"` 에 WALP 가 답했고 모델 호출 0
- `tests/test_wug.py` -- 가짜 상류를 지어 끝까지 돌림 · 일곱 가지 코드 변이 모두 빨간불

- 사진·PDF 도구(`tests/test_media.py`) -- 가짜 Gemini 서버를 띄워 진짜 HTTP 길로 받기·내보내기·형식 넷을 돌림.
  파일은 바이트로 확인(jpg 머리 · `%PDF` · 쪽 수). 코드 변이 여섯 모두 빨간불

**못 함:**
- **진짜 이미지 모델 호출은 0 건**(여기에 키가 없다). 모델 목록에 image 모델이 실제로 뜨는지, `imageConfig.aspectRatio` 를
  받는지, 응답이 `inlineData` 로 오는지는 첫 실행이 처음 확인이다. 실패하면 `http_400:...` 처럼 API 의 말을 그대로 보인다
- **진짜 Gemini 호출은 0 건** -- 키가 없는 자리에서 만들었다. 첫 실행의 `모델:` 줄(확인됨 / 미확인 / 불일치)이 처음 확인이다
- `AfterAgent` 훅을 **Gemini CLI 안에서** 발동시켜 보지 못했다(모델의 진짜 답이 있어야 발동한다). 훅 단독으로만 확인
- macOS 에서 돌려 보지 않았다. sandbox 의 메모리 상한은 macOS 에서 걸리지 않을 수 있다(설정 실패를 넘어가게 짜여 있다)
- Gemini CLI 가 MCP 도구 결과를 화면에 얼마나 보여 주는지 확인하지 않았다

**알려진 약점:** WALP 앞단은 일이 섞인 말("고마워요 이제 머지해줘")을 잡담으로 삼킨다(WALP 저장소가 잰 것: 60 문장 중 9~10).
그래서 잡담으로 답할 때마다 `//` 로 건너뛰는 법을 보인다. 끄려면 `WUG_FRONT=0`.

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

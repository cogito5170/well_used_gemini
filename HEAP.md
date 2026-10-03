# Gemini CLI 힙 OOM — 원인과 고침 (CMD-WUG1 rev 3 · A)

사용자 보고(BD-215): `FATAL ERROR: Reached heap limit / JavaScript heap out of memory`, Scavenge ~4082 MB,
Mark-Compact 4094 → 4093 MB, 약 2,220,175 ms(37분) 뒤.

## 결론 한 줄

**Gemini CLI 0.62.0 안의 것이다.** 텔레메트리가 꺼져 있으면(기본값) CLI 는 모델 요청을 보낼 때마다
그 요청의 대화 기록 전체를 `JSON.stringify` 한 문자열을 `telemetryBuffer` 에 붙들고, **그 버퍼를 영영 비우지 않는다.**
대화가 길수록 요청 하나가 크고, 그것이 요청마다 한 벌씩 쌓이므로 힙은 **턴 수의 제곱**으로 자란다.
우리 도구의 결과가 클수록(대화 기록이 클수록) 빨리 자란다 — 우리 결과는 **곱해지는 쪽**이지 붙드는 쪽이 아니다.

## 4 GB 라는 수

Gemini CLI 는 스스로를 다시 띄우면서 `--max-old-space-size = 전체 메모리의 50%` 를 준다
(`bundle/gemini.js` getNodeMemoryArgs: `Math.floor(totalMemoryMB * 0.5)`). 8 GB 맥이면 4096 MB —
보고된 4094 MB 한계와 맞는다.

## 붙드는 길 (S2 — 힙 스냅숏에서 이름 붙인 것)

150 MB 에서 뜬 스냅숏(0.62.0 번들 · 우리 확장의 MCP 서버 · `gh_read` 결과 ~21 KB 를 도는 가짜 모델):
도구 결과 표지가 든 문자열 203 개 · 41.1 MB, 결과 하나가 **최대 70 벌**. 모든 복사본의 붙든 길이 같다:

    string (요청 하나의 JSON 전체, 131 KB ~ 773 KB)
      <- ApiRequestEvent.request_text
      <- system / Context.event            (logApiRequest 가 만든 클로저)
      <- (array) telemetryBuffer[k]
      <- system / Context.telemetryBuffer  (telemetry/sdk.js 모듈 변수)

코드(0.62.0 `@google/gemini-cli-core` dist):

- `core/loggingContentGenerator.js` — `logApiRequest(contents, …)`: `const requestText = JSON.stringify(contents)` 를
  `new ApiRequestEvent(model, {… contents …}, requestText)` 에 싣는다 (요청마다 대화 전체)
- `telemetry/loggers.js` — `logApiRequest`: `bufferTelemetryEvent(() => { … event.toLogRecord(config) … })`
- `telemetry/sdk.js` — `bufferTelemetryEvent`: `telemetryInitialized` 가 거짓이면 `telemetryBuffer.push(fn)`.
  비우는 곳은 `flushTelemetryBuffer` 하나뿐이고, 그것은 `initializeTelemetry` 가 끝날 때만 불린다
- `config/config.js` — `if (this.telemetrySettings.enabled) initializeTelemetry(this)`.
  **꺼져 있으면 초기화가 없고, 버퍼는 프로세스가 끝날 때까지 자란다**

## 잰 것 (S1 · S9 — 같은 가짜 모델 · 같은 도구 · 300 턴 · 매 초 강제 GC 뒤의 남은 힙)

| 판 | 도구 결과 (중앙값) | 남은 힙 기울기 | 300 턴 뒤 |
|---|---|---|---|
| 기본 설정 | 21,391 자 (`gh_read`) | **1174 KB/턴** (늘어나는 기울기) | 422 MB |
| 기본 설정 | 233 자 (`media_info`) | 240 KB/턴 | 166 MB |
| 우리 결과 상한 4000 자만 | 4,524 자 | 1030 KB/턴 | 370 MB |
| `telemetry.enabled` (local · outfile 버림 · logPrompts 끔)만 | 21,363 자 | **30 KB/턴** | 117 MB |
| 둘 다 | 4,524 자 | **30 KB/턴** | 117 MB |
| 둘 다, outfile `/dev/null` | 4,524 자 | 29 KB/턴 | 115 MB |

- 기울기는 처음 1/5 를 뺀 뒤의 선형 맞춤이다. 기본 설정의 곡선은 위로 휜다(제곱) — 300 턴 근방의 값이다
- 우리 결과의 몫: 같은 기본 설정에서 결과가 233 자 → 21 KB 일 때 240 → 1174 KB/턴. **늘어난 80% 가 우리 결과가 키운
  요청 크기**다. 그러나 상한만으로는 1174 → 1030 (12%). 원인을 끄지 않으면 무엇을 넣든 제곱으로 쌓인다
- 텔레메트리를 켜면 버퍼가 비워지고 기울기는 대화 기록 자체의 몫(≈30 KB/턴)만 남는다 — 그것은 CLI 의 대화 압축이 다룬다

LONG_RUN_TABLE

재현 도구: `heapbench/` — `run.sh`(진짜 Gemini CLI + 진짜 MCP 서버 + 가짜 모델), `fakeloop.py`(턴마다 도구를 부르는 가짜 API),
`heaplog.cjs`(매 초 강제 GC 뒤 남은 힙 · 프로세스별 · 지정한 크기에서 스냅숏 한 번), `analyze.py`(턴별 힙 · 기울기), `snap.py`
(스냅숏에서 도구 결과 문자열의 복사본 수와 붙든 길). 예:

    GEMINI_JS=$(python3 -c "import os,shutil;print(os.path.realpath(shutil.which('gemini')))") \
    TURNS=300 MODE=tool TOOL=mcp_agentic_gh_read ARGS_LIST='[{"repo":"se_new","path":"bot_tools.py"}]' \
      heapbench/run.sh big 18961 && python3 heapbench/analyze.py heapbench-out/big

(`analyze.py` 는 OUT 아래에서 이름으로 부른다.)

## 고침

1. **설정(지원되는 것만 — CLI 를 고치지 않는다).** `python3 wug.py model gemini-3-flash-preview` 가 `~/.gemini/settings.json` 에
   텔레메트리가 꺼져 있을 때만 이것을 넣는다(이미 켜 둔 사람의 설정은 안 건드린다):

       "telemetry": {"enabled": true, "target": "local", "outfile": "/dev/null", "logPrompts": false}

   `target: local` 이라 밖으로 보내지 않고, `outfile` 이 버리는 자리라 디스크도 안 는다(파일로 두면 300 턴에 46 MB),
   `logPrompts: false` 라 프롬프트 · 도구 결과는 기록에 안 들어간다(파일을 열어 확인: 도구 결과 표지 0 회).
   `wug.py doctor` 가 이 칸을 본다.
2. **우리 것(S3).** MCP 도구 결과는 4000 자에서 자르고 `result_id` 를 단다. 전체는 `WUG_HOME/results/<id>.txt`, 이어 읽기는
   `result_read`. 그림 바이트는 결과에 안 싣는다(파일 경로만). 알림(notifications)은 보내지 않는다. 훅은 표준 입력의
   한 번 읽기뿐이다(대화 기록 파일을 다시 읽지 않는다). MCP 서버는 CLI 가 세션마다 하나 띄운다.
3. **임시방편(S4) — 고침이 아니다.** `wug.py cli` · `wug.py write` 가 `NODE_OPTIONS=--max-old-space-size=8192
   --heapsnapshot-near-heap-limit=1 --diagnostic-dir=WUG_HOME/heap` 로 띄운다. CLI 의 재실행은 50% 가 지금 한계보다
   클 때만 한계를 올리므로 이 값이 남는다. 다시 나면 스냅숏이 남는다.
4. **구조(S9 · S10).** 턴마다 짧게 사는 headless CLI(`--resume`)는 이 버퍼를 프로세스와 함께 버린다 — ga 의 `ga gemini`.
   이 저장소에 들이려면 ga-SDK 를 설치해야 하고, 그것은 사용자 확인을 기다린다.

## 다시 띄우는 규칙

설정 1 을 넣기 전의 세션은 길수록 위험하다(제곱). 넣은 뒤에도 대화 기록 자체는 턴마다 ≈30 KB 씩 늘고 압축이 줄인다.
한 세션이 몇 시간을 넘거나 `/stats` 의 요청 크기가 수 MB 면 `/quit` 하고 `--resume` 으로 다시 띄운다.

## 위로 보낼 글 (upstream issue)

> **Title:** Unbounded heap growth: `telemetryBuffer` retains every API request (full history JSON) when telemetry is disabled
>
> **Version:** @google/gemini-cli 0.62.0 (also present in -core 0.62.0 dist)
>
> **What happens:** With telemetry disabled (the default), each model request calls `logApiRequest`, which builds
> `new ApiRequestEvent(model, {contents, …}, JSON.stringify(contents))` and passes a closure over it to
> `bufferTelemetryEvent`. Because `telemetryInitialized` is false, the closure is pushed onto the module-level
> `telemetryBuffer`. The buffer is drained only by `flushTelemetryBuffer`, which runs only at the end of
> `initializeTelemetry` — and that is only called when telemetry is enabled. So the buffer grows for the life of
> the process, and each entry holds the whole conversation serialized at that turn: memory is O(turns²).
>
> **Evidence:** headless run, fake model calling one ~21 KB tool per turn, retained heap after forced GC:
> 1174 KB/turn and rising (422 MB at 300 turns). Heap snapshot: the large strings are retained via
> `ApiRequestEvent.request_text <- Context.event <- telemetryBuffer[k]`. Enabling telemetry with
> `{"target":"local","outfile":"/dev/null","logPrompts":false}` drops the slope to 30 KB/turn.
> Interactive sessions reach the relaunch limit (50% of RAM, 4096 MB on an 8 GB machine) after ~30–40 minutes
> of tool-heavy work: `FATAL ERROR: Reached heap limit`.
>
> **Suggested fix:** do not buffer events when telemetry is disabled (drop them, or only buffer until the
> enabled/disabled decision is known and then clear); or cap the buffer; and avoid serializing `contents` into
> `request_text` unless `logPrompts` is on.

## gentleMonster_gemini 에 옮길 것 (S8)

- **설정 1 이 핵심이다** — 확장과 무관하게 CLI 프로세스의 문제다. GMG 의 설치 안내 · 점검에 같은 `telemetry` 칸을 넣는다
  (이미 켜 둔 사용자 것은 두기). 이 저장소의 `wug.py` `HEAP_FIX_TELEMETRY` · `model_cmd` · `cli_check` 를 그대로 옮기면 된다
- MCP 결과 상한 + `result_read`(`wug_mcp.py` `cap_result` · `read_result`) — 결과가 큰 도구(그림 · 문서)가 있으면 꼭
- 임시방편 실행기(`stopgap_env`) — 다시 나면 증거가 남게
- 측정 도구(`fakeloop.py` · `heaplog.cjs` · `snap.py`)로 GMG 도구를 같은 표로 잰다 — 무료 한도를 안 쓴다

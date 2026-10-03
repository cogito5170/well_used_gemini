"""well_used_gemini 의 모델 -- **하나, 폴백 없음.** 모든 부분(묻기 · 그림 · 글쓰기 · 실험 · Gemini CLI 기본값)이 이것만 쓴다.

사용자 결정 2026-10-03: gemini-3-flash-preview. 환경 변수로 바꾸는 길을 두지 않는다 -- 바꾸려면 이 줄을 바꾸는 커밋을 낸다.
se_new agentic/config.json 의 "model" 과 같아야 한다(tests/test_wug.py 가 고정 커밋의 것과 맞춰 본다).

Gemini CLI 0.62.0 에서 확인한 것(코드 · 진짜 번들):
  · 이 이름은 바꿔 치지 않는다 -- getBackendModelMappings 는 3.5-flash · 3-flash · 3.1-flash-lite 만 바꾼다.
    resolveModel 은 명시한 PREVIEW_GEMINI_FLASH_MODEL 을 올리지 않는다(API 키 인증이면 미리보기 접근이 참)
  · 그런데 Gemini 3 모델의 폴백 사슬은 **돌아 감긴다**: flash-preview 가 막히면 3.1-pro-preview 를 내민다
    ("We always wrap around for Gemini 3 chains ... fallback to Pro if Flash is exhausted").
    그래서 wug.py model 이 settings.json 에 이 모델 하나만 든 사슬(NO_FALLBACK_CHAINS)을 같이 쓴다
"""
MODEL = "gemini-3-flash-preview"
CLI_VERSION = "0.62.0"
NO_FALLBACK_CHAINS = {k: [{"model": MODEL, "isLastResort": True}]
                      for k in ("preview", "default", "auto-preview", "auto-default")}

"""사진·PDF 받기/내보내기(wug_media.py) 시험 -- **가짜 Gemini 서버를 띄워** 진짜 HTTP 길(requests · 키 머리 ·
오류 가림)까지 돌린다. 진짜 Gemini 는 부르지 않는다(이것으로 진짜 모델이 그림을 준다는 것은 확인되지 않는다).

Pillow · pypdfium2 · requests 가 있는 파이썬으로 돌린다(setup 이 만든 가상환경):

    ~/.cache/well_used_gemini/venv/bin/python tests/test_media.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PIL import Image
    import pypdfium2  # noqa: F401
    import requests  # noqa: F401
except ImportError as e:
    print(f"건너뜀이 아니라 실패: 이 파이썬에 {e.name} 가 없다 -- 가상환경 파이썬으로 돌려라")
    sys.exit(1)

fails = []


def ok(cond, label):
    print(f"    {'OK  ' if cond else '실패'} {label}")
    if not cond:
        fails.append(label)


def png_bytes(color=(200, 30, 30), size=(64, 80)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


KEY = "AIza" + "SyMEDIATEST" * 3
seen = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        seen.append(("GET", self.path, self.headers.get("x-goog-api-key")))
        self._send(200, {"models": [
            {"name": "models/gemini-3-flash-preview", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-9.0-flash-image-preview", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-9.0-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/imagen-9.0", "supportedGenerationMethods": ["predict"]}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append(("POST", self.path, self.headers.get("x-goog-api-key"), body))
        if "broken" in json.dumps(body):
            return self._send(400, {"error": {"message": f"bad key {KEY} rejected"}})
        if "IMAGE" in json.dumps(body.get("generationConfig") or {}):
            if "refuse" in json.dumps(body):
                return self._send(200, {"candidates": [{"finishReason": "IMAGE_SAFETY",
                                                        "content": {"parts": [{"text": "못 그린다"}]}}]})
            return self._send(200, {"modelVersion": "gemini-3-flash-preview", "candidates": [{"content": {"parts": [
                {"text": "그렸다"},
                {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png_bytes()).decode()}}]}}]})
        n = len([p for p in body["contents"][0]["parts"] if "inline_data" in p])
        return self._send(200, {"candidates": [{"content": {"parts": [{"text": f"파일 {n}개를 봤다"}]}}]})


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()

with tempfile.TemporaryDirectory() as tmp:
    T = Path(tmp)
    os.environ.update({"WUG_GEMINI_API": f"http://127.0.0.1:{srv.server_port}/v1beta", "WUG_OUT": str(T / "out"),
                       "WUG_OPEN": "0", "GEMINI_API_KEY": KEY, "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
    os.environ.pop("WUG_IMAGE_MODEL", None)
    import wug_media as M

    (T / "a.jpeg").write_bytes(b"")
    Image.new("RGB", (40, 30), (1, 2, 3)).save(T / "a.jpeg", "JPEG")
    (T / "b.png").write_bytes(png_bytes())
    (T / "fake.jpg").write_text("이건 그림이 아니다")

    print("[받기] 꼴은 확장자가 아니라 바이트로")
    out = M.info([str(T / "a.jpeg"), str(T / "b.png"), str(T / "fake.jpg"), str(T / "none.png")])
    ok("jpg · " in out and "40×30 px" in out, "jpeg -> jpg · 해상도")
    ok("64×80 px" in out, "png 해상도")
    ok("fake.jpg: unsupported" in out and "not_found" in out, "가짜 jpg · 없는 파일은 사유를 단다")

    print("[내보내기] 변환: 사진 -> pdf 한 권 · pdf -> 쪽마다 사진 · jpg/jpeg")
    out = M.convert([str(T / "a.jpeg"), str(T / "b.png")], "pdf", True, "board")
    pdf = T / "out" / "board.pdf"
    ok(pdf.is_file() and pdf.read_bytes()[:4] == b"%PDF", "두 장 -> board.pdf")
    ok("2쪽" in M.info([str(pdf)]), "그 PDF 가 2쪽이다(다시 읽어서 잰다)")
    out = M.convert([str(pdf)], "jpeg", name="page")
    pages = sorted((T / "out").glob("page-p*.jpeg"))
    ok(len(pages) == 2 and all(p.read_bytes()[:3] == b"\xff\xd8\xff" for p in pages), "PDF -> 쪽마다 jpeg 2장(바이트로 확인)")
    M.convert([str(T / "b.png")], "jpg", name="board")
    ok((T / "out" / "board.jpg").is_file() and (T / "out" / "board.pdf").is_file(), "이름이 겹쳐도 다른 확장자는 따로")
    M.convert([str(T / "a.jpeg"), str(T / "b.png")], "pdf", True, "board")
    ok((T / "out" / "board-2.pdf").is_file(), "같은 이름이 있으면 덮어쓰지 않고 -2")
    for bad, want in ((lambda: M.convert([str(T / "b.png")], "bmp"), "format_unsupported"),
                      (lambda: M.convert([str(pdf)], "pdf"), "already_pdf")):
        try:
            bad()
            ok(False, want)
        except M.MediaError as e:
            ok(want in str(e), f"거절: {want}")

    print("[받기] 사진·PDF 를 모델에 보낸다(진짜 HTTP · 가짜 서버)")
    out = M.ask([str(T / "a.jpeg"), str(pdf)], "무엇이 보이나")
    post = seen[-1]
    ok("파일 2개를 봤다" in out and post[2] == KEY, "inline_data 두 개 · 키는 x-goog-api-key 머리로")
    mimes = [p["inline_data"]["mime_type"] for p in post[3]["contents"][0]["parts"] if "inline_data" in p]
    ok(mimes == ["image/jpeg", "application/pdf"], f"mime 은 바이트로 정한 것 ({mimes})")
    ok("/models/gemini-3-flash-preview:" in post[1] and "미보고" in out, "묻기는 설정 모델 · 응답이 모델을 안 밝히면 '미보고'")
    ok(KEY not in out and "key=" not in post[1], "키가 주소 · 출력에 없다")

    print("[내보내기] 그림 생성 -- 모델은 하나(목록을 안 본다), 쓴 모델은 응답이 밝힌 것으로")
    out = M.generate("빨간 사각형", [str(T / "b.png")], ["jpg", "pdf", "png"], "4:5", "red")
    gen = seen[-1]
    ok("/models/gemini-3-flash-preview:generateContent" in gen[1], f"그림도 같은 모델 하나 ({gen[1]})")
    ok(not any(x[0] == "GET" for x in seen), "모델 목록을 읽지 않는다(다른 모델을 고를 길이 없다)")
    ok(gen[3]["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
       and gen[3]["generationConfig"]["imageConfig"] == {"aspectRatio": "4:5"}, "응답 꼴 · 비율")
    ok(any("inline_data" in p for p in gen[3]["contents"][0]["parts"]), "참고 사진이 같이 간다")
    files = {p.suffix: p for p in (T / "out").glob("red.*")}
    ok(set(files) == {".jpg", ".pdf", ".png"} and files[".jpg"].read_bytes()[:3] == b"\xff\xd8\xff"
       and files[".pdf"].read_bytes()[:4] == b"%PDF", "jpg · pdf · png 세 파일(바이트로 확인)")
    ok("응답이 밝힌 모델 gemini-3-flash-preview" in out and "그렸다" in out, "보고에 응답이 밝힌 모델 · 모델의 말")
    os.environ["WUG_IMAGE_MODEL"] = "my-image-model"
    M.generate("x", formats=["png"])
    ok("/models/gemini-3-flash-preview:" in seen[-1][1], "WUG_IMAGE_MODEL 같은 환경 변수로도 모델이 안 바뀐다")
    os.environ.pop("WUG_IMAGE_MODEL")
    for bad, want in ((lambda: M.generate("refuse image"), "no_image_returned"),
                      (lambda: M.generate("broken"), "http_400"),
                      (lambda: M.generate("x", aspect_ratio="wide"), "aspect_ratio_invalid"),
                      (lambda: M.generate(""), "prompt_required")):
        try:
            bad()
            ok(False, want)
        except M.MediaError as e:
            ok(want in str(e) and KEY not in str(e), f"거절: {want} (키는 가림)")
    big = T / "big.png"
    Image.frombytes("RGB", (3000, 3000), os.urandom(3000 * 3000 * 3)).save(big, "PNG", compress_level=0)
    try:
        M.ask([str(big)] * 2, "q")
        ok(False, "too_large")
    except M.MediaError as e:
        ok("too_large" in str(e), "인라인 상한을 넘으면 보내기 전에 막는다")
    os.environ.pop("GEMINI_API_KEY")
    try:
        M.ask([str(T / "b.png")], "q")
        ok(False, "no_api_key")
    except M.MediaError as e:
        ok("no_api_key" in str(e) and "wug.py key" in str(e), "키가 없으면 저장하는 법을 말한다")

srv.shutdown()
print()
if fails:
    print(f"media: {len(fails)}개 실패 -- {fails}")
    sys.exit(1)
print("media: 받기(info · ask) · 내보내기(convert · generate) · 형식 jpg/jpeg/png/pdf · 키 가림 -- 통과")

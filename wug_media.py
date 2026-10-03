#!/usr/bin/env python3
"""사진 · PDF 를 **받고**(읽기 · 물어보기) **내보내는**(생성 · 변환) 도구. wug.py 가 가상환경 파이썬으로 부른다.

    info    {"paths": [...]}                                   파일 꼴 · 크기 · 해상도 · PDF 쪽 수
    ask     {"paths": [...], "question": "..."}                사진/PDF 를 Gemini 에 보내 묻는다(설정 모델 하나)
    generate {"prompt": "...", "references": [...], "formats": ["jpg","pdf"], "aspect_ratio": "4:5", "name": "..."}
                                                               이미지 모델로 그림을 만들어 파일로 저장(참고 사진을 같이 줄 수 있다)
    convert {"paths": [...], "format": "jpg|jpeg|png|webp|pdf", "combine": true, "name": "..."}
                                                               사진 -> jpg/png/pdf(여러 장을 PDF 한 권으로) · PDF -> 쪽마다 사진

규칙:
  · **결과는 파일이다.** 터미널은 그림을 못 보인다. 저장한 경로를 돌려주고, macOS 면 미리보기로 연다(WUG_OPEN=0 이면 안 연다)
  · 저장 자리: WUG_OUT, 없으면 ~/Pictures/well_used_gemini (없으면 ~/well_used_gemini_out). 남의 파일을 덮어쓰지 않는다
  · **모델은 wug_model.MODEL 하나**(묻기 · 그림 둘 다). 목록에서 다른 모델을 고르지 않는다 -- 폴백 없음.
    그 모델이 그림을 못 내면 no_image_returned 로 그대로 실패한다. 쓴 모델은 **응답이 밝힌 것**(modelVersion)으로 적는다
  · 키는 GEMINI_API_KEY(wug.child_env 가 keys.env · ~/.gemini/.env 에서 찾는다). 화면 · 오류에 안 싣는다
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

API = os.environ.get("WUG_GEMINI_API", "https://generativelanguage.googleapis.com/v1beta")
from wug_model import MODEL  # noqa: E402  -- 하나, 폴백 없음
INLINE_CAP = 18 * 1024 * 1024                    # 요청 하나에 실을 원본 바이트 상한(인라인 요청 20MB 아래로)
FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "pdf": "PDF"}
MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif", "pdf": "application/pdf",
        "heic": "image/heic", "heif": "image/heif"}


class MediaError(RuntimeError):
    pass


def _key() -> str:
    k = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not k:
        raise MediaError("no_api_key -- 한 번만: python3 ~/.gemini/extensions/well-used-gemini/wug.py key")
    return k


def _hide(text: str) -> str:
    k = (os.environ.get("GEMINI_API_KEY") or "").strip()
    return text.replace(k, "<키 가림>") if k else text


def kind_of(data: bytes) -> "str | None":
    """확장자가 아니라 **바이트로** 꼴을 정한다."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"heif", b"hevc"):
        return "heic"
    return None


def _load(path: str) -> "tuple[Path, bytes, str]":
    p = Path(os.path.expanduser(str(path).strip().strip("'\""))).resolve()
    if not p.is_file():
        raise MediaError(f"not_found:{p}")
    data = p.read_bytes()
    k = kind_of(data)
    if k is None:
        raise MediaError(f"unsupported:{p.name} (jpg · jpeg · png · webp · gif · heic · pdf)")
    return p, data, k


def out_dir() -> Path:
    if os.environ.get("WUG_OUT"):
        d = Path(os.path.expanduser(os.environ["WUG_OUT"]))
    elif (Path.home() / "Pictures").is_dir():
        d = Path.home() / "Pictures" / "well_used_gemini"
    else:
        d = Path.home() / "well_used_gemini_out"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fresh(stem: str, ext: str) -> Path:
    stem = re.sub(r"[^\w\-가-힣]+", "_", stem).strip("_")[:60] or "image"
    d = out_dir()
    p = d / f"{stem}.{ext}"
    i = 2
    while p.exists():                      # 덮어쓰지 않는다
        p = d / f"{stem}-{i}.{ext}"
        i += 1
    return p


def _open(paths: list) -> None:
    if os.environ.get("WUG_OPEN", "1") == "0" or sys.platform != "darwin" or not paths:
        return
    try:
        subprocess.run(["open", *[str(p) for p in paths]], timeout=10, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------- 받기
def info(paths: list) -> str:
    rows = []
    for raw in paths:
        try:
            p, data, k = _load(raw)
        except MediaError as e:
            rows.append(f"- {raw}: {e}")
            continue
        extra = ""
        if k == "pdf":
            try:
                import pypdfium2 as pdfium
                doc = pdfium.PdfDocument(data)
                w, h = doc[0].get_size()
                extra = f" · {len(doc)}쪽 · 첫 쪽 {w / 72 * 25.4:.0f}×{h / 72 * 25.4:.0f} mm"
            except Exception as e:  # noqa: BLE001
                extra = f" · 쪽 수를 못 읽음({type(e).__name__})"
        elif k != "heic":
            try:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as im:
                    extra = f" · {im.width}×{im.height} px · {im.mode}"
            except Exception as e:  # noqa: BLE001
                extra = f" · 해상도를 못 읽음({type(e).__name__})"
        rows.append(f"- {p} · {k} · {len(data) / 1024:.0f} KB{extra}")
    return "\n".join(rows) or "(파일 없음)"


def _parts_for(paths: list) -> list:
    parts, total = [], 0
    for raw in paths or []:
        p, data, k = _load(raw)
        total += len(data)
        if total > INLINE_CAP:
            raise MediaError(f"too_large: 합계 {total / 1e6:.1f} MB > {INLINE_CAP / 1e6:.0f} MB -- 파일을 줄이거나 나눠라")
        parts.append({"inline_data": {"mime_type": MIME[k], "data": base64.b64encode(data).decode()}})
    return parts


def _post(model: str, body: dict, poster=None) -> dict:
    url = f"{API}/models/{model}:generateContent"
    if poster:
        return poster(url, body)
    import requests
    try:
        r = requests.post(url, headers={"x-goog-api-key": _key(), "Content-Type": "application/json"},
                          json=body, timeout=300)
    except requests.RequestException as e:
        raise MediaError(_hide(f"network:{type(e).__name__}")) from None
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = r.text[:200]
        raise MediaError(_hide(f"http_{r.status_code}:{model}:{msg[:240]}"))
    return r.json()


def _model_line(resp: dict, asked: str) -> str:
    mv = resp.get("modelVersion")
    if not mv:
        return f"모델: 요청 {asked} · 응답이 밝힌 모델 미보고"
    return f"모델: 요청 {asked} · 응답이 밝힌 모델 {mv}" + ("" if asked in mv or mv in asked else " (요청과 다르다)")


def _texts(resp: dict) -> list:
    out = []
    for c in resp.get("candidates") or []:
        for part in (c.get("content") or {}).get("parts") or []:
            if isinstance(part.get("text"), str) and not part.get("thought"):
                out.append(part["text"])
    return out


def ask(paths: list, question: str, poster=None) -> str:
    if not paths:
        raise MediaError("paths_required")
    if not (question or "").strip():
        question = "Describe this file in detail."
    model = MODEL
    resp = _post(model, {"contents": [{"role": "user", "parts": _parts_for(paths) + [{"text": question}]}]}, poster)
    text = "\n".join(_texts(resp)).strip()
    fb = (resp.get("promptFeedback") or {}).get("blockReason")
    return (f"[사진·PDF 읽기 · {_model_line(resp, model)}]\n" + (text or f"(글 없음{' · 막힘 ' + fb if fb else ''})"))


# ---------------------------------------------------------------- 내보내기
def pick_image_model(lister=None) -> str:
    """모델은 하나다(wug_model.MODEL). 목록을 보고 다른 것을 고르지 않는다 -- 폴백 없음."""
    return MODEL


def _save(img_bytes: bytes, stem: str, formats: list) -> list:
    from PIL import Image
    saved = []
    with Image.open(io.BytesIO(img_bytes)) as im:
        im.load()
        for f in formats:
            f = f.lower().lstrip(".")
            if f not in FORMATS:
                raise MediaError(f"format_unsupported:{f} (jpg · jpeg · png · webp · pdf)")
            p = _fresh(stem, f)
            src = im.convert("RGB") if FORMATS[f] in ("JPEG", "PDF") and im.mode not in ("RGB", "L") else im
            kw = {"quality": 95} if FORMATS[f] == "JPEG" else ({"resolution": 150.0} if f == "pdf" else {})
            src.save(p, FORMATS[f], **kw)
            saved.append(p)
    return saved


def generate(prompt: str, references=None, formats=None, aspect_ratio: str = "", name: str = "",
             poster=None, lister=None) -> str:
    if not (prompt or "").strip():
        raise MediaError("prompt_required")
    formats = formats or ["png"]
    model = pick_image_model(lister)
    gen = {"responseModalities": ["TEXT", "IMAGE"]}
    if aspect_ratio:
        if not re.match(r"^\d{1,2}:\d{1,2}$", aspect_ratio):
            raise MediaError(f"aspect_ratio_invalid:{aspect_ratio} (예 1:1 · 4:5 · 16:9)")
        gen["imageConfig"] = {"aspectRatio": aspect_ratio}
    body = {"contents": [{"role": "user", "parts": _parts_for(references) + [{"text": prompt}]}],
            "generationConfig": gen}
    resp = _post(model, body, poster)
    imgs = []
    for c in resp.get("candidates") or []:
        for part in (c.get("content") or {}).get("parts") or []:
            d = part.get("inlineData") or part.get("inline_data")
            if d and str(d.get("mimeType") or d.get("mime_type", "")).startswith("image/") and not part.get("thought"):
                imgs.append(base64.b64decode(d["data"]))
    text = "\n".join(_texts(resp)).strip()
    if not imgs:
        fb = (resp.get("promptFeedback") or {}).get("blockReason") or \
            ",".join(str(c.get("finishReason")) for c in resp.get("candidates") or [])
        raise MediaError(f"no_image_returned:{model}:{fb or '사유 없음'}" + (f" · 모델의 말: {text[:200]}" if text else ""))
    stem = name or (time.strftime("%Y%m%d-%H%M%S") + "-" + prompt[:30])
    saved = []
    for i, b in enumerate(imgs):
        saved += _save(b, stem if len(imgs) == 1 else f"{stem}-{i + 1}", formats)
    _open(saved)
    return (f"[그림 생성 · {_model_line(resp, model)} · 참고 사진 {len(references or [])}장]\n"
            + "\n".join(f"저장: {p}" for p in saved) + (f"\n모델의 말: {text[:600]}" if text else ""))


def convert(paths: list, fmt: str, combine: bool = True, name: str = "") -> str:
    fmt = (fmt or "").lower().lstrip(".")
    if fmt not in FORMATS:
        raise MediaError(f"format_unsupported:{fmt} (jpg · jpeg · png · webp · pdf)")
    if not paths:
        raise MediaError("paths_required")
    from PIL import Image
    loaded = [_load(p) for p in paths]
    saved = []
    if fmt == "pdf":
        pages = []
        for p, data, k in loaded:
            if k == "pdf":
                raise MediaError(f"already_pdf:{p.name}")
            if k == "heic":
                raise MediaError(f"heic_unsupported:{p.name} -- 미리보기에서 jpg 로 내보낸 뒤 다시")
            im = Image.open(io.BytesIO(data))
            pages.append(im.convert("RGB"))
        groups = [pages] if combine else [[pg] for pg in pages]
        for gi, g in enumerate(groups):
            stem = name or (loaded[0][0].stem if combine or len(groups) == 1 else loaded[gi][0].stem)
            out = _fresh(stem, "pdf")
            g[0].save(out, "PDF", resolution=150.0, save_all=True, append_images=g[1:])
            saved.append(out)
    else:
        for p, data, k in loaded:
            if k == "pdf":
                import pypdfium2 as pdfium
                doc = pdfium.PdfDocument(data)
                for i in range(len(doc)):
                    img = doc[i].render(scale=2).to_pil()
                    saved += _save_pil(img, f"{name or p.stem}-p{i + 1}", fmt)
            elif k == "heic":
                raise MediaError(f"heic_unsupported:{p.name} -- 미리보기에서 jpg 로 내보낸 뒤 다시")
            else:
                saved += _save_pil(Image.open(io.BytesIO(data)), name or p.stem, fmt)
    _open(saved)
    return "[변환]\n" + "\n".join(f"저장: {p}" for p in saved)


def _save_pil(im, stem: str, fmt: str) -> list:
    p = _fresh(stem, fmt)
    src = im.convert("RGB") if FORMATS[fmt] == "JPEG" and im.mode not in ("RGB", "L") else im
    src.save(p, FORMATS[fmt], **({"quality": 95} if FORMATS[fmt] == "JPEG" else {}))
    return [p]


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    cmd, a = argv[0], json.loads(argv[1])
    try:
        if cmd == "info":
            print(info(a.get("paths") or []))
        elif cmd == "ask":
            print(ask(a.get("paths") or [], a.get("question", "")))
        elif cmd == "generate":
            print(generate(a.get("prompt", ""), a.get("references") or [], a.get("formats") or [],
                           a.get("aspect_ratio", ""), a.get("name", "")))
        elif cmd == "convert":
            print(convert(a.get("paths") or [], a.get("format", ""), bool(a.get("combine", True)), a.get("name", "")))
        else:
            print(f"모르는 명령: {cmd}", file=sys.stderr)
            return 2
    except MediaError as e:
        print(f"[media] {_hide(str(e))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

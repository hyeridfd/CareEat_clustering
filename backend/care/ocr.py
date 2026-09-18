# -*- coding: utf-8 -*-
"""
약봉투·처방전 사진에서 약 이름 읽기 (OCR)

솔루션과 같은 LLM 키(OPENAI_API_KEY / ANTHROPIC_API_KEY)를 그대로 쓴다.
읽은 결과는 저장하지 않고 화면에 후보로만 띄우며, 담당자가 확인하고 저장한다.
사진 자체는 서버에 남기지 않는다.
"""
from __future__ import annotations
import base64
import json
import os

import httpx

from .solution import TIMEOUT, _extract_json, _key

# 사진 판독은 솔루션 생성보다 좋은 모델을 쓰는 편이 정확하다.
# .env 에서 따로 지정할 수 있고, 지정하지 않으면 아래 기본값을 쓴다.
#   OCR_PROVIDER = openai | anthropic     (없으면 LLM_PROVIDER, 그것도 없으면 키가 있는 쪽)
#   OCR_MODEL    = 모델 이름              (없으면 아래 기본값)
DEFAULT_OCR_MODEL = {"openai": "gpt-4o", "anthropic": "claude-sonnet-4-5"}


def ocr_model(provider: str) -> str:
    return _key("OCR_MODEL") or DEFAULT_OCR_MODEL.get(provider, "gpt-4o")


def ocr_status() -> dict:
    provider = (_key("OCR_PROVIDER") or os.getenv("LLM_PROVIDER", "") or "").lower()
    if provider not in ("openai", "anthropic"):
        provider = "openai" if _key("OPENAI_API_KEY") else ("anthropic" if _key("ANTHROPIC_API_KEY") else "none")
    return {"provider": provider, "model": ocr_model(provider) if provider != "none" else None,
            "openai_key": bool(_key("OPENAI_API_KEY")), "anthropic_key": bool(_key("ANTHROPIC_API_KEY"))}

MAX_BYTES = 8 * 1024 * 1024
OK_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif")

PROMPT = """약봉투·처방전·약 목록 사진에서 복용 약물을 읽어 JSON 으로만 답합니다.

규칙:
1. 사진에 적힌 글자만 씁니다. 안 보이거나 확실하지 않으면 그 항목을 빼거나 confidence 를 low 로 둡니다.
2. 약 이름은 상품명 그대로 적습니다(예: 아모잘탄정, 메트포르민서방정).
3. dose 는 사진에 적힌 표기 그대로(예: "1정", "0.5정", "5mL"). 없으면 null.
4. schedule 은 ["아침","점심","저녁","취침 전","필요시"] 중에서만 고릅니다. 모르면 [].
5. 효능·부작용·복용 지도를 만들어 내지 않습니다. 사진에 없는 내용은 쓰지 않습니다.

{"items": [{"name": "약 이름", "dose": "1정", "schedule": ["아침"], "confidence": "high|low"}],
 "note": "사진이 흐리거나 일부만 보이면 여기에 한 문장"}"""


def read_medication_image(data: bytes, content_type: str, provider: str | None = None) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("사진이 너무 큽니다 (8MB 이하).")
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct not in OK_TYPES:
        raise ValueError("JPG·PNG·WEBP 사진만 읽을 수 있습니다.")
    b64 = base64.b64encode(data).decode()
    provider = (provider or _key("OCR_PROVIDER") or os.getenv("LLM_PROVIDER", "none")).lower()
    if provider not in ("openai", "anthropic"):
        provider = "openai" if _key("OPENAI_API_KEY") else "anthropic"

    if provider == "openai":
        key = _key("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY 가 설정되어 있지 않습니다.")
        model = ocr_model("openai")
        r = httpx.post("https://api.openai.com/v1/chat/completions",
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "temperature": 0,
                             "response_format": {"type": "json_object"},
                             "messages": [{"role": "user", "content": [
                                 {"type": "text", "text": PROMPT},
                                 {"type": "image_url", "image_url": {"url": f"data:{ct};base64,{b64}"}}]}]},
                       timeout=TIMEOUT)
        r.raise_for_status()
        out = _extract_json(r.json()["choices"][0]["message"]["content"])
        gen = f"openai:{model}"
    else:
        key = _key("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY 가 설정되어 있지 않습니다.")
        model = ocr_model("anthropic")
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                       json={"model": model, "max_tokens": 1500, "temperature": 0,
                             "messages": [{"role": "user", "content": [
                                 {"type": "image", "source": {"type": "base64", "media_type": ct, "data": b64}},
                                 {"type": "text", "text": PROMPT}]}]},
                       timeout=TIMEOUT)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        out = _extract_json(text)
        gen = f"anthropic:{model}"

    items = []
    for x in (out.get("items") or [])[:20]:
        name = str(x.get("name") or "").strip()
        if not name:
            continue
        sched = [s for s in (x.get("schedule") or []) if s in ("아침", "점심", "저녁", "취침 전", "필요시")]
        items.append({"name": name[:80],
                      "dose": (str(x.get("dose")).strip()[:40] if x.get("dose") else None),
                      "schedule": sched,
                      "confidence": "low" if str(x.get("confidence", "")).lower() == "low" else "high"})
    return {"items": items, "note": (str(out.get("note") or "").strip()[:200] or None), "generator": gen}

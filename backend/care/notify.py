# -*- coding: utf-8 -*-
"""
보호자 카카오 알림톡 발송
  - 알림톡은 사전 승인된 템플릿 + 변수 치환만 가능 → 자세한 내용은 '보호자 리포트 링크'로 전달
  - KAKAO_MODE=dry_run(기본): 실제 발송 없이 렌더링 결과·로그만 저장
  - KAKAO_MODE=live + KAKAO_PROVIDER=solapi: 솔라피 API 로 알림톡 실제 발송
  - KAKAO_MODE=sms: 알림톡 대신 솔라피 문자(LMS)로 같은 내용 + 리포트 링크 발송
    (카카오 비즈니스 심사·템플릿 승인 전 임시 운영용, 발신번호 등록 필요)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _env(name: str, default: str | None = None) -> str | None:
    """backend/.env 를 호출할 때마다 다시 읽어 우선 사용 (서버 재시작 없이 수정 반영).
    .env 가 없거나 값이 없으면 시스템 환경변수(배포 서버 설정)를 사용."""
    v = None
    if ENV_FILE.exists():
        try:
            from dotenv import dotenv_values
            v = (dotenv_values(ENV_FILE).get(name) or "").strip() or None
        except Exception:
            v = None
    if v is None:
        v = os.getenv(name)
    return v if v not in (None, "") else default


def report_base_url() -> str:
    return (_env("REPORT_BASE_URL") or _env("FRONTEND_URL") or "http://localhost:5173").rstrip("/")


def report_ttl_days() -> int:
    return int(_env("REPORT_TTL_DAYS", "30"))


# 카카오(솔라피)에 등록·승인받을 템플릿 원문과 '글자 하나까지' 같아야 함
TEMPLATES = {
    "CARE_REPORT_V1": {
        "text": ("[#{시설명}] #{어르신} 어르신 건강·식사 돌봄 안내\n\n"
                 "#{보호자}님, 안녕하세요.\n"
                 "#{평가일} 실시한 건강·식사 평가 결과와 돌봄 계획을 안내드립니다.\n\n"
                 "■ 관리 구분: #{관리구분}\n"
                 "■ 돌봄 중점: #{돌봄중점}\n\n"
                 "자세한 내용은 아래 버튼에서 확인하실 수 있습니다. (#{만료일}까지)"),
        # 버튼 링크는 도메인을 고정하고 경로 끝만 변수로 둔다 (카카오 템플릿 정책)
        "button": {"name": "돌봄 리포트 보기", "type": "WL", "path": "/report/#{토큰}"},
        "max_var_len": 40,
    },
}


def template_for_registration(code: str = "CARE_REPORT_V1") -> dict:
    """솔라피 템플릿 등록 화면에 그대로 입력할 내용."""
    t = TEMPLATES[code]
    url = report_base_url() + t["button"]["path"]
    return {"content": t["text"], "button_name": t["button"]["name"], "button_type": "웹링크(WL)",
            "mobile_url": url, "pc_url": url}


def mask_phone(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    return d[:3] + "****" + d[-4:] if len(d) >= 10 else "***"


def normalize_phone(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    if not re.fullmatch(r"01[016789]\d{7,8}", d):
        raise ValueError("휴대폰 번호 형식이 올바르지 않습니다.")
    return d


def template_vars(template_code: str) -> list[str]:
    t = TEMPLATES[template_code]
    return sorted(set(re.findall(r"#\{([^}]+)\}", t["text"] + t["button"]["path"])))


def render(template_code: str, variables: dict) -> tuple[str, dict]:
    """템플릿 렌더링 → (본문, {button, kakao_variables})"""
    t = TEMPLATES[template_code]
    lim = t["max_var_len"]
    names = template_vars(template_code)
    missing = [n for n in names if n not in variables]
    if missing:
        raise ValueError(f"템플릿 변수 누락: {missing}")
    vals = {n: (str(variables[n]) if n == "토큰" else str(variables[n])[:lim]) for n in names}
    text = t["text"]
    for k, v in vals.items():
        text = text.replace("#{" + k + "}", v)
    url = report_base_url() + t["button"]["path"].replace("#{토큰}", vals.get("토큰", ""))
    button = {"name": t["button"]["name"], "type": t["button"]["type"], "url": url}
    return text, {"button": button, "kakao_variables": {"#{" + k + "}": v for k, v in vals.items()}}


def new_report_token():
    token = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(days=report_ttl_days())
    return token, expires, f"{report_base_url()}/report/{token}"


# ─────────────────────────── 발송기 ───────────────────────────

class DryRunSender:
    name = "dryrun"

    def send(self, phone: str, template_code: str, text: str, extra: dict) -> dict:
        return {"status": "previewed", "response": {"note": "테스트 모드 — 실제 발송하지 않음",
                                                    "to": mask_phone(phone)}}


class SolapiSender:
    """솔라피 알림톡 (https://api.solapi.com/messages/v4/send-many/detail)"""
    name = "solapi"
    URL = "https://api.solapi.com/messages/v4/send-many/detail"

    def __init__(self):
        self.api_key = _env("SOLAPI_API_KEY")
        self.api_secret = _env("SOLAPI_API_SECRET")
        self.pf_id = _env("SOLAPI_PFID")
        self.template_id = _env("SOLAPI_TEMPLATE_ID")
        self.sender_no = _env("SOLAPI_FROM")  # 발신번호(선택): 있으면 알림톡 실패 시 문자로 대체발송
        missing = [k for k, v in {"SOLAPI_API_KEY": self.api_key, "SOLAPI_API_SECRET": self.api_secret,
                                  "SOLAPI_PFID": self.pf_id, "SOLAPI_TEMPLATE_ID": self.template_id}.items() if not v]
        if missing:
            raise RuntimeError(f".env 설정 필요: {', '.join(missing)}")

    def _auth(self) -> str:
        date = datetime.now(timezone.utc).isoformat()
        salt = secrets.token_hex(32)
        sig = hmac.new(self.api_secret.encode(), (date + salt).encode(), hashlib.sha256).hexdigest()
        return f"HMAC-SHA256 apiKey={self.api_key}, date={date}, salt={salt}, signature={sig}"

    def send(self, phone: str, template_code: str, text: str, extra: dict) -> dict:
        msg = {"to": phone,
               "kakaoOptions": {"pfId": self.pf_id, "templateId": self.template_id,
                                "variables": extra["kakao_variables"], "disableSms": not self.sender_no}}
        if self.sender_no:
            msg["from"] = re.sub(r"\D", "", self.sender_no)
        r = httpx.post(self.URL, json={"messages": [msg]},
                       headers={"Authorization": self._auth(), "Content-Type": "application/json"}, timeout=20)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:500]}
        if r.status_code >= 400:
            return {"status": "failed", "response": {"http": r.status_code, **(body if isinstance(body, dict) else {}),
                                                     "reason": (body.get("errorMessage") if isinstance(body, dict) else None)}}
        failed = body.get("failedMessageList") or []
        if failed:
            f = failed[0]
            return {"status": "failed", "response": {"reason": f.get("statusMessage") or f.get("statusCode"),
                                                     "detail": f, "group": body.get("groupInfo", {}).get("groupId")}}
        return {"status": "sent", "response": {"group": body.get("groupInfo", {}).get("groupId"),
                                               "note": "솔라피 접수 완료 (실제 도착 여부는 솔라피 콘솔 발송내역에서 확인)"}}


class SolapiSmsSender(SolapiSender):
    """솔라피 문자(LMS) — 알림톡 템플릿과 같은 본문 + 리포트 링크"""
    name = "solapi_sms"

    def __init__(self):
        self.api_key = _env("SOLAPI_API_KEY")
        self.api_secret = _env("SOLAPI_API_SECRET")
        self.sender_no = _env("SOLAPI_FROM")
        missing = [k for k, v in {"SOLAPI_API_KEY": self.api_key, "SOLAPI_API_SECRET": self.api_secret,
                                  "SOLAPI_FROM": self.sender_no}.items() if not v]
        if missing:
            raise RuntimeError(f".env 설정 필요: {', '.join(missing)} (문자는 솔라피에 등록한 발신번호가 필요합니다)")

    @staticmethod
    def sms_text(text: str, extra: dict) -> str:
        body = text.replace("아래 버튼에서", "아래 링크에서")
        return f"{body}\n\n▶ {extra['button']['name']}\n{extra['button']['url']}"

    def send(self, phone: str, template_code: str, text: str, extra: dict) -> dict:
        msg = {"to": phone, "from": re.sub(r"\D", "", self.sender_no), "type": "LMS",
               "subject": "건강·식사 돌봄 안내", "text": self.sms_text(text, extra)}
        r = httpx.post(self.URL, json={"messages": [msg]},
                       headers={"Authorization": self._auth(), "Content-Type": "application/json"}, timeout=20)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:500]}
        if r.status_code >= 400:
            return {"status": "failed", "response": {"http": r.status_code, **(body if isinstance(body, dict) else {}),
                                                     "reason": (body.get("errorMessage") if isinstance(body, dict) else None)}}
        failed = body.get("failedMessageList") or []
        if failed:
            f = failed[0]
            return {"status": "failed", "response": {"reason": f.get("statusMessage") or f.get("statusCode"), "detail": f}}
        return {"status": "sent", "response": {"group": body.get("groupInfo", {}).get("groupId"),
                                               "note": "솔라피 문자 접수 완료 (도착 여부는 솔라피 콘솔 발송내역에서 확인)"}}


class NhnSender:
    name = "nhn"

    def send(self, phone, template_code, text, extra):
        raise NotImplementedError("NHN Cloud 비즈메시지 연동은 appKey·senderKey·templateCode 발급 후 구현하세요.")


def get_sender():
    """호출 시점의 .env 를 따른다 (서버 재시작 없이 모드 전환 가능)."""
    mode = (_env("KAKAO_MODE", "dry_run") or "dry_run").lower()
    if mode == "sms":
        return SolapiSmsSender(), "sms"
    if mode != "live":
        return DryRunSender(), "dry_run"
    provider = (_env("KAKAO_PROVIDER", "solapi") or "solapi").lower()
    cls = {"solapi": SolapiSender, "nhn": NhnSender}.get(provider, DryRunSender)
    return cls(), "live"

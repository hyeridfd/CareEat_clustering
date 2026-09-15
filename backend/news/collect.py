# -*- coding: utf-8 -*-
"""
고령·돌봄 뉴스 수집 (NAVER API HUB 검색 API)

  · 카테고리별 키워드로 최근 N시간 기사를 모은다
  · URL·제목 기준 중복 제거, 광고·단신성 제목 제외
  · 시설별 데이터가 아니라 전 시설 공통이므로 nursing_home_id 를 갖지 않는다

※ 검색 API 는 developers.naver.com 에서 NAVER API HUB 로 이관되었다.
   인증 헤더가 X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY 로 바뀌었다.
"""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

KST = ZoneInfo("Asia/Seoul")
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
TIMEOUT = float(os.getenv("NEWS_TIMEOUT", "15"))
log = logging.getLogger("uvicorn.error")

# 이관 후 엔드포인트. 환경에 따라 경로가 다를 수 있어 후보를 순서대로 시도한다.
API_CANDIDATES = [
    "https://naverapihub.apigw.ntruss.com/search/v1/news",
    "https://naveropenapi.apigw.ntruss.com/v1/search/news.json",
]
_resolved_api: str | None = None

# 순서가 곧 우선순위 — 한 기사가 여러 그룹에 걸리면 위쪽으로 분류된다.
KEYWORD_GROUPS: dict[str, list[str]] = {
    "돌봄·요양": ["요양원", "요양병원", "장기요양", "노인돌봄", "방문요양",
              "노인복지시설", "치매 돌봄"],
    "고령자 식품·영양": ["고령친화식품", "케어푸드", "노인 영양", "노인 급식",
                   "연하곤란", "삼킴장애"],
    "정책·제도": ["노인 정책", "기초연금", "노인장기요양보험", "노인 일자리",
              "보건복지부 노인", "노인복지법"],
    "노인 전반": ["노인", "고령자", "어르신", "초고령사회"],
}
CATEGORIES = list(KEYWORD_GROUPS.keys())

DISPLAY_PER_KEYWORD = 30

# 제목에 걸리면 버린다 (증권·연예·단신 노이즈)
NOISE = re.compile(r"코스닥|코스피|주가|상한가|오늘의 운세|부고|\[포토\]|\[인사\]|\[영상\]")

PRESS_BY_DOMAIN = {
    "yna.co.kr": "연합뉴스", "yonhapnews.co.kr": "연합뉴스", "chosun.com": "조선일보",
    "donga.com": "동아일보", "joongang.co.kr": "중앙일보", "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문", "hankookilbo.com": "한국일보", "mk.co.kr": "매일경제",
    "hankyung.com": "한국경제", "seoul.co.kr": "서울신문", "kmib.co.kr": "국민일보",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "kbs.co.kr": "KBS",
    "imbc.com": "MBC", "sbs.co.kr": "SBS", "ytn.co.kr": "YTN",
    "newsis.com": "뉴시스", "news1.kr": "뉴스1", "edaily.co.kr": "이데일리",
    "mt.co.kr": "머니투데이", "dailymedi.com": "데일리메디", "docdocdoc.co.kr": "청년의사",
    "welfarenews.net": "복지뉴스", "bokjinews.com": "복지뉴스",
    "foodnews.co.kr": "식품저널", "thinkfood.co.kr": "식품외식경제",
}


def _key(name: str):
    """backend/.env 를 호출할 때마다 다시 읽어 우선 사용, 없으면 시스템 환경변수."""
    v = None
    if ENV_FILE.exists():
        try:
            from dotenv import dotenv_values
            v = (dotenv_values(ENV_FILE).get(name) or "").strip() or None
        except Exception:
            v = None
    return v or os.getenv(name) or None


def api_status() -> dict:
    return {"key_id": bool(_key("NAVER_API_KEY_ID")), "key": bool(_key("NAVER_API_KEY")),
            "resolved_endpoint": _resolved_api, "env_file": str(ENV_FILE),
            "categories": CATEGORIES}


def clean_text(s: str) -> str:
    s = re.sub(r"</?b>", "", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def url_key(url: str) -> str:
    """중복 판정용 — 프로토콜·쿼리스트링·끝 슬래시를 떼어낸 형태."""
    u = (url or "").split("?")[0].split("#")[0]
    return re.sub(r"^https?://", "", u).rstrip("/").lower()


def title_key(title: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", (title or "").lower())


def press_of(url: str) -> str:
    m = re.search(r"https?://(?:www\.|news\.|m\.)?([^/]+)", url or "")
    if not m:
        return "미상"
    host = m.group(1)
    for dom, name in PRESS_BY_DOMAIN.items():
        if host.endswith(dom):
            return name
    return host


def _call(endpoint: str, query: str, display: int) -> dict:
    key_id, key = _key("NAVER_API_KEY_ID"), _key("NAVER_API_KEY")
    if not key_id or not key:
        raise RuntimeError(f"NAVER_API_KEY_ID / NAVER_API_KEY 미설정 (확인한 파일: {ENV_FILE})")
    r = httpx.get(endpoint,
                  params={"query": query, "display": min(display, 100), "sort": "date"},
                  headers={"X-NCP-APIGW-API-KEY-ID": key_id, "X-NCP-APIGW-API-KEY": key},
                  timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def search(query: str, display: int = DISPLAY_PER_KEYWORD) -> dict:
    """엔드포인트가 확정되기 전에는 후보를 순서대로 시도하고, 성공하면 고정한다."""
    global _resolved_api
    if _resolved_api:
        return _call(_resolved_api, query, display)

    last: Exception | None = None
    for ep in API_CANDIDATES:
        try:
            data = _call(ep, query, display)
            _resolved_api = ep
            return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise                      # 키 문제 — 다른 경로를 시도해도 의미 없음
            last = e
        except Exception as e:             # noqa: BLE001
            last = e
    raise last if last else RuntimeError("검색 API 호출 실패")


def collect(hours: int = 24) -> tuple[list[dict], list[str]]:
    """최근 `hours` 시간 기사를 모아 (기사 목록, 오류 메시지 목록) 로 돌려준다."""
    cutoff = datetime.now(KST) - timedelta(hours=hours)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    articles: list[dict] = []
    errors: list[str] = []

    for category, keywords in KEYWORD_GROUPS.items():
        for kw in keywords:
            try:
                data = search(kw)
            except Exception as e:                      # noqa: BLE001
                errors.append(f"{kw}: {e}")
                continue

            items = data.get("items") or data.get("result", {}).get("items") or []
            for item in items:
                title = clean_text(item.get("title", ""))
                if not title or NOISE.search(title):
                    continue

                try:
                    published = parsedate_to_datetime(item.get("pubDate", "")).astimezone(KST)
                except Exception:                       # noqa: BLE001
                    continue
                if published < cutoff:
                    continue

                link = item.get("originallink") or item.get("link") or ""
                uk, tk = url_key(link), title_key(title)
                if not uk or uk in seen_urls or tk in seen_titles:
                    continue
                seen_urls.add(uk)
                seen_titles.add(tk)

                articles.append({
                    "title": title,
                    "description": clean_text(item.get("description", "")),
                    "url": link,
                    "url_key": uk,
                    "press": press_of(link),
                    "published_at": published.isoformat(),
                    "category": category,
                })

    articles.sort(key=lambda a: a["published_at"], reverse=True)
    if errors:
        log.warning("뉴스 수집 중 오류 %d건: %s", len(errors), errors[:3])
    return articles, errors

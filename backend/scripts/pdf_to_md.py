# -*- coding: utf-8 -*-
"""
지침 PDF → 근거 문헌 마크다운 초안

    python scripts/pdf_to_md.py "C:/Users/me/Downloads/급식매뉴얼.pdf" --id LTC_MEAL_MANUAL
    python scripts/pdf_to_md.py 매뉴얼.pdf --id LTC_MEAL_MANUAL --pages 12-58

만드는 것: care/knowledge/docs/<ID>.md
    ## 3.2 저염식 제공 원칙
    <!-- p.34 -->
    국·탕은 건더기 위주로 배식하고 ...

  - '##' 은 소제목(근거 각주의 조항명), '<!-- p.34 -->' 는 쪽번호로 그대로 적재된다.
  - 자동 추출은 초안이다. 목차·머리말·표가 섞이므로 반드시 원문과 대조해 손봐야 한다.
  - 글자가 이미지로만 들어 있는 스캔 PDF 는 텍스트가 거의 안 나온다 (--check 로 먼저 확인).

준비:  pip install pypdf
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DOCS = BACKEND / "care" / "knowledge" / "docs"

# 소제목처럼 보이는 줄: "3.2 저염식 ...", "제 4 장 식사 형태", "Ⅲ. 영양관리"
HEAD = re.compile(r"^\s*(?:제?\s*\d+\s*[장절편]|\d+(?:\.\d+){0,3}\.?|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.)\s+\S.{0,60}$")
NOISE = re.compile(r"^\s*(?:-\s*\d+\s*-|\d{1,3}|[·.\s]{5,})\s*$")      # 쪽번호·점선 목차
TOC = re.compile(r"[.·]{5,}\s*\d+\s*$")                                 # "1.1 개요 ........ 12"


def page_range(spec: str | None, n: int):
    if not spec:
        return range(1, n + 1)
    lo, _, hi = spec.partition("-")
    return range(int(lo), int(hi or lo) + 1)


def clean_page(text: str) -> list[tuple[bool, str]]:
    """페이지 텍스트 → [(소제목인가, 줄)]. 줄바꿈으로 끊긴 문장은 이어 붙인다."""
    lines = [l.rstrip() for l in text.splitlines()]
    out: list[tuple[bool, str]] = []
    buf = ""
    for raw in lines:
        l = re.sub(r"[ \t]+", " ", raw).strip()
        if not l or NOISE.match(l) or TOC.search(l):
            if buf:
                out.append((False, buf)); buf = ""
            continue
        if HEAD.match(l):
            if buf:
                out.append((False, buf)); buf = ""
            out.append((True, l))
            continue
        # 문장이 끝났으면 문단을 닫고, 아니면 다음 줄과 이어 붙인다
        buf = f"{buf} {l}".strip() if buf else l
        if re.search(r"(다\.|요\.|음\.|\.|:|」|\))\s*$", buf) and len(buf) > 40:
            out.append((False, buf)); buf = ""
    if buf:
        out.append((False, buf))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--id", required=True, help="sources.json 의 문헌 id (파일 이름이 된다)")
    ap.add_argument("--pages", help="예: 12-58 (본문만 잘라내기)")
    ap.add_argument("--check", action="store_true", help="쪽별 추출 글자 수만 보고 끝낸다")
    ap.add_argument("--out", help="출력 경로 (기본: care/knowledge/docs/<ID>.md)")
    a = ap.parse_args()

    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("먼저:  pip install pypdf")

    src = Path(a.pdf).expanduser()
    if not src.exists():
        raise SystemExit(f"파일이 없습니다: {src}")
    reader = PdfReader(str(src))
    pages = list(page_range(a.pages, len(reader.pages)))

    if a.check:
        print(f"{src.name} — 총 {len(reader.pages)}쪽")
        empty = 0
        for i in pages:
            t = (reader.pages[i - 1].extract_text() or "").strip()
            if len(t) < 30:
                empty += 1
            print(f"  p.{i:>3}  {len(t):>5}자  {t[:50].replace(chr(10), ' ')}")
        if empty > len(pages) * 0.5:
            print("\n※ 글자가 거의 안 나옵니다. 스캔본(이미지) PDF 로 보입니다 — OCR 이 필요합니다.")
        return

    md: list[str] = []
    last_head = None
    for i in pages:
        text = reader.pages[i - 1].extract_text() or ""
        items = clean_page(text)
        if not items:
            continue
        md.append(f"<!-- p.{i} -->")
        for is_head, line in items:
            if is_head:
                if line != last_head:
                    md.append(f"\n## {line}\n")
                    last_head = line
            else:
                md.append(line + "\n")

    out = Path(a.out) if a.out else DOCS / f"{a.id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(md)
    out.write_text(f"<!-- {src.name} 에서 자동 추출한 초안. 원문과 대조해 손질하세요. -->\n\n{body}\n",
                   encoding="utf-8")
    heads = sum(1 for l in md if l.startswith("\n## "))
    print(f"{out}\n  쪽 {len(pages)}개 · 소제목 {heads}개 · {len(body):,}자")
    print("  → 원문과 대조해 손질한 뒤:  python scripts/ingest_guidelines.py --only " + a.id)


if __name__ == "__main__":
    main()

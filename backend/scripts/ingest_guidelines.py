# -*- coding: utf-8 -*-
"""
근거 문헌 적재 — care/knowledge/docs/*.{md,txt,pdf} → 문단 청크 → 임베딩 → Supabase

사용법 (backend 폴더에서)
    python scripts/ingest_guidelines.py                 # 전체
    python scripts/ingest_guidelines.py --only KDRI2020 # 한 문헌만
    python scripts/ingest_guidelines.py --dry-run       # 쪼개기만 보고 업로드 안 함
    python scripts/ingest_guidelines.py --replace       # 해당 문헌의 기존 청크를 지우고 새로

준비
    1) Supabase SQL 편집기에서 sql/care_schema_v6.sql 실행
    2) backend/.env 에 SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY
    3) care/knowledge/sources.json 에 문헌을 등록하고,
       같은 id 로 care/knowledge/docs/<id>.md 파일을 둔다
       (PDF 를 넣으려면  pip install pypdf)

문서 작성 요령 — 마크다운이 가장 잘 맞는다
    ## 3.2 저염식 제공 원칙
    국·탕은 건더기 위주로 배식하고 국물은 반 컵 이하로 제공한다. ...

    '##' 제목이 section 으로 저장되고, 빈 줄 단위로 문단이 나뉜다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv                                  # noqa: E402
load_dotenv(BACKEND / ".env")

from supabase import create_client                              # noqa: E402

KNOW = BACKEND / "care" / "knowledge"
DOCS = KNOW / "docs"
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
CHUNK_CHARS = int(os.getenv("RAG_CHUNK_CHARS", "700"))
OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "120"))
BATCH = 64


# ─────────────────────────── 읽기 ───────────────────────────

PAGE_MARK = re.compile(r"<!--\s*p\.?\s*(\d+)\s*-->")


def _strip_comments(t: str) -> str:
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def read_text(path: Path) -> list[tuple[str | None, int | None, str]]:
    """파일 → [(section, page, 본문)]

    마크다운에서는 <!-- p.34 --> 표시로 쪽을 구분한다 (scripts/pdf_to_md.py 가 넣어준다).
    """
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise SystemExit("PDF 를 읽으려면 먼저:  pip install pypdf")
        out = []
        for i, pg in enumerate(PdfReader(str(path)).pages, 1):
            t = (pg.extract_text() or "").strip()
            if t:
                out.append((None, i, t))
        return out
    raw = path.read_text(encoding="utf-8")
    parts = PAGE_MARK.split(raw)                              # [앞, '34', 본문, '35', 본문 ...]
    out: list[tuple[str | None, int | None, str]] = []
    head = _strip_comments(parts[0])
    if head.strip():
        out.append((None, None, head))
    for i in range(1, len(parts) - 1, 2):
        body = _strip_comments(parts[i + 1])
        if body.strip():
            out.append((None, int(parts[i]), body))
    return out or [(None, None, "")]


def split_sections(text: str):
    """마크다운 '#' 제목 단위로 나눈다."""
    parts, cur, buf = [], None, []
    for line in text.splitlines():
        m = re.match(r"^#{1,4}\s+(.*)", line)
        if m:
            if buf:
                parts.append((cur, "\n".join(buf)))
            cur, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if buf or cur is not None:          # 본문 없이 제목만 있어도 남긴다 (쪽 경계에서 이어받기 위해)
        parts.append((cur, "\n".join(buf)))
    return parts or [(None, text)]


def chunk(text: str, size=CHUNK_CHARS, overlap=OVERLAP) -> list[str]:
    """빈 줄 문단을 유지하면서 size 안팎으로 합친다. 너무 긴 문단은 잘라 쓴다."""
    paras = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    paras = [p for p in paras if len(p) > 1]
    out, cur = [], ""
    for p in paras:
        while len(p) > size * 1.6:                      # 아주 긴 문단은 문장 경계로 자른다
            cut = p.rfind(". ", 0, size) + 1 or p.rfind("다. ", 0, size) + 2 or size
            out.append(p[:cut].strip())
            p = p[max(0, cut - overlap):].strip()
        if not cur:
            cur = p
        elif len(cur) + len(p) + 1 <= size:
            cur += "\n" + p
        else:
            out.append(cur)
            cur = (cur[-overlap:] + "\n" + p) if overlap else p
    if cur:
        out.append(cur)
    return [c for c in (x.strip() for x in out) if len(c) >= 40]


# ─────────────────────────── 임베딩 ───────────────────────────

def embed(texts: list[str]) -> list[list[float]]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY 가 없습니다 (backend/.env 확인).")
    for attempt in range(4):
        r = httpx.post("https://api.openai.com/v1/embeddings",
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": EMBED_MODEL, "input": texts}, timeout=120)
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
    raise SystemExit("임베딩 호출이 계속 429 로 막힙니다. 잠시 후 다시 실행하세요.")


# ─────────────────────────── 적재 ───────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="적재할 문헌 id")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true", help="해당 문헌의 기존 청크를 지우고 다시 넣는다")
    args = ap.parse_args()

    meta = json.loads((KNOW / "sources.json").read_text(encoding="utf-8"))["sources"]
    if args.only:
        meta = [m for m in meta if m["id"] in set(args.only)]
    if not meta:
        raise SystemExit("적재할 문헌이 없습니다. care/knowledge/sources.json 을 확인하세요.")

    sb = None
    if not args.dry_run:
        url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise SystemExit("SUPABASE_URL / SUPABASE_KEY 가 없습니다 (backend/.env 확인).")
        sb = create_client(url, key)

    total = 0
    for m in meta:
        sid = m["id"]
        files = sorted(p for p in DOCS.glob(f"{sid}.*") if p.suffix.lower() in (".md", ".txt", ".pdf"))
        if not files:
            print(f"  · {sid}: 문서 파일 없음 → 건너뜀 (care/knowledge/docs/{sid}.md 를 만드세요)")
            continue

        rows, ord_ = [], 0
        for f in files:
            last_section = None
            for section, page, body in read_text(f):
                pieces = split_sections(body) if f.suffix.lower() != ".pdf" else [(section, body)]
                for sec_title, sec_body in pieces:
                    sec_title = sec_title or last_section      # 쪽 경계에서 소제목이 끊기지 않게
                    last_section = sec_title or last_section
                    for c in chunk(sec_body):
                        ord_ += 1
                        rows.append({"source_id": sid, "section": sec_title, "page": page, "ord": ord_,
                                     "text": c, "hash": hashlib.sha1(c.encode("utf-8")).hexdigest()})
        print(f"  · {sid}: {len(files)}개 파일 → 문단 {len(rows)}개")
        if args.dry_run:
            for r in rows[:2]:
                print(f"      [{r['section']}] {r['text'][:80]}…")
            total += len(rows)
            continue

        sb.table("care_sources").upsert({k: v for k, v in m.items() if k != "note"} | {"note": m.get("note")}).execute()
        if args.replace:
            sb.table("care_chunks").delete().eq("source_id", sid).execute()

        for i in range(0, len(rows), BATCH):
            part = rows[i:i + BATCH]
            vecs = embed([r["text"] for r in part])
            for r, v in zip(part, vecs):
                r["embedding"] = v
            sb.table("care_chunks").upsert(part, on_conflict="source_id,hash").execute()
            print(f"      {min(i + BATCH, len(rows))}/{len(rows)} 업로드")
        total += len(rows)

    print(f"\n완료 — 문단 {total}개" + (" (dry-run, 업로드 안 함)" if args.dry_run else ""))


if __name__ == "__main__":
    main()

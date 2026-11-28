# -*- coding: utf-8 -*-
"""규격 → 포장 중량(g) 환산과 g당 가격.

pack_grams 는 routers/prices.py 의 규칙에서 출발했고, 곱셈 표기('250g*10pk')를 괄호 뒤에서도 읽도록 고쳤다.
부피(ml/L)는 밀도, 개수 단위는 개당 중량으로 g 을 만든다. 환산값은 unit_conversions 표로 관리하고 근거를 남긴다.
환산할 수 없으면 None (그 상품은 가격 계산에서 빠진다).
"""
import re
import unicodedata
from typing import Optional

_NUM = r"(\d+(?:[.,]\d+)?)"
_W = re.compile(_NUM + r"\s*(kg|g|ml|l)(?![a-wyz])", re.I)   # 뒤에 x 는 허용 (67gX10)
_MUL = re.compile(_NUM + r"\s*(kg|g|ml|l)\s*[*xX×]\s*(\d+)", re.I)
_SLASH = re.compile(_NUM + r"\s*(kg|g|ml|l)\s*/\s*(\d+)\s*(?:개|ea|입|팩|봉|pk)", re.I)
MAX_PER_KG = 1_000_000


def _to_g(n: str, u: str) -> float:
    v = float(n.replace(",", ""))
    return v * 1000 if u.lower() in ("kg", "l") else v


def pack_grams(spec: Optional[str], unit: Optional[str]):
    """(포장 중량 g 또는 ml, 부피 여부). 읽을 수 없으면 (None, False).

    원칙: 단위가 KG 면 kg당 가격. 아니면 '첫 번째 중량 표기'를 기준으로 하고, 그 바로 뒤에 곱셈이 붙을 때만 곱한다.
      '1.56Kg(52~60g*30EA)' → 1560 g      '1KG,17G*55~59개' → 1000 g      '7Kg(500g*14EA)/500g팩' → 7000 g
      '1Kg*10EA' → 10 kg                  '(71-90)39~50미/250g*10pk/Box' → 2500 g
      '90G*16개*4EA/BOX' → 5760 g         '1BOX/(110G*5EA)*8EA' → 4400 g
      '200±20g/ea' → 200 g                '40±10g 토막, 10Kg/Box' → 10 kg (박스 단위에 붙은 더 큰 중량)
      '2.45kg/6ea'(EA) → 2450 g (6개는 상자 입수)   '100G/50개'(PK) → 5000 g   '16호'(닭) → 1600 g
    """
    spec = spec if isinstance(spec, str) else ""
    unit = unit if isinstance(unit, str) else ""
    u = unit.strip().lower()
    s = unicodedata.normalize("NFKC", spec)
    # 오차 표기 정리: '200±20g' → '200g',  '300G±30G' → '300G',  '100G±' → '100G',  '45g±3*23ea±2' → '45g*23ea'
    s = re.sub(r"(\d+(?:[.,]\d+)?)\s*±\s*\d+(?:[.,]\d+)?\s*(kg|g|ml|l)(?![a-z])", r"\1\2", s, flags=re.I)
    s = re.sub(r"±\s*\d*(?:[.,]\d+)?\s*(kg|g|ml|l)?(?![a-z])", "", s, flags=re.I)
    # 범위 뒤 쉼표는 천 단위 구분이 아니다: '300-500,850g' → '300-500 850g'
    s = re.sub(r"(\d+\s*[-~]\s*\d+)\s*,", r"\1 ", s)
    if u == "kg" or re.match(r"^\s*kg(?![a-z0-9])", s, re.I):
        return 1000.0, False

    ws = list(_W.finditer(s))
    if ws:
        first = ws[0]
        g0 = _to_g(first.group(1), first.group(2))
        vol = first.group(2).lower() in ("ml", "l")
        # 박스·팩 단위: '10Kg/Box' 처럼 포장 단위에 붙은 중량이 첫 중량보다 크면 그것 ('40g 토막, 10Kg/Box')
        if u in ("box", "pk", "bx"):
            m = re.search(_NUM + r"\s*(kg|g|ml|l)\s*/?\s*(box|박스|bx|pk|팩)(?![a-z])", s, re.I)
            if m and _to_g(m.group(1), m.group(2)) > g0:
                return _to_g(m.group(1), m.group(2)), m.group(2).lower() in ("ml", "l")
        rest = s[first.end():]
        m = re.match(r"\s*[*xX×]\s*(\d+)\s*(?:ea|개|입|pk|팩|봉|t)?\s*\)?\s*(?:[*xX×]\s*(\d+))?", rest, re.I)
        if m and m.group(1):                                  # 곱셈 (겹 포장 포함)
            g = g0 * int(m.group(1)) * (int(m.group(2)) if m.group(2) else 1)
            return (g, vol) if g > 0 else (None, False)
        m = re.match(r"\s*/\s*(\d+)\s*(?:개|ea|입|팩|봉|pk)", rest, re.I)
        if m and u not in ("ea", "개"):                        # '100G/50개' 는 묶음 단위일 때만 곱한다
            return g0 * int(m.group(1)), vol
        if g0 > 0:
            return g0, vol
    # 닭 호수: 'N호' = 약 N×100 g. 박스에 '10pk' 가 있으면 곱한다
    m = re.search(r"(?<!\d)(\d{1,2})\s*호(?!\d)", s)
    if m and 5 <= int(m.group(1)) <= 30:
        n = re.search(r"(\d+)\s*(?:pk|팩|마리|ea)\b", s, re.I)
        return int(m.group(1)) * 100.0 * (int(n.group(1)) if n and u in ("box", "bx") else 1), False
    # 숫자 없이 kg 표기만: '20~25미/kg', '수율90%내외/Kg' → kg 단위 가격
    if re.search(r"(^|[/,\s(])kg($|[/,\s)])", s, re.I):
        return 1000.0, False
    return None, False


# ─────────────────────────── 기본 환산표 (unit_conversions 초기값) ───────────────────────────
# key: 식재료 이름에 들어 있는 말 (긴 것부터 비교).  basis 는 근거.
DENSITY_SEED = [
    ("국간장", 1.18, "간장류 비중 1.15–1.2 (인계서 기준 약 1.2)"),
    ("간장", 1.2, "인계서: 간장 약 1.2"),
    ("액젓", 1.2, "어간장류 비중 약 1.2"),
    ("굴소스", 1.25, "점성 소스 비중 약 1.25"),
    ("식용유", 0.92, "인계서: 식용유 약 0.92"),
    ("콩기름", 0.92, "식물성 유지 0.92"),
    ("올리브유", 0.91, "올리브유 0.91"),
    ("참기름", 0.92, "식물성 유지 0.92"),
    ("들기름", 0.93, "식물성 유지 0.93"),
    ("포도씨유", 0.92, "식물성 유지 0.92"),
    ("우유", 1.03, "인계서: 우유 약 1.03"),
    ("두유", 1.03, "우유와 같게"),
    ("생크림", 1.0, "유지방 35–38% 크림 약 1.0"),
    ("요구르트", 1.05, "발효유 약 1.05"),
    ("식초", 1.01, "식초 약 1.01"),
    ("물엿", 1.4, "물엿 Bx75 약 1.4"),
    ("올리고당", 1.35, "올리고당 시럽 약 1.35"),
    ("꿀", 1.42, "꿀 약 1.42"),
    ("맛술", 1.05, "미림류 약 1.05"),
    ("청주", 0.98, "청주 약 0.98"),
    ("포도주", 0.99, "와인 약 0.99"),
    ("탄산수", 1.0, "물"),
    ("육수", 1.0, "시판 육수·농축액은 물 기준"),
    ("곰탕", 1.0, "물 기준"),
    ("주스", 1.04, "과즙음료 약 1.04"),
    # 종류별 기본값 (11/27 추가 — 개별 값이 위에 있으면 긴 이름이 먼저 맞는다)
    ("콜라", 1.04, "탄산음료 약 1.04"), ("사이다", 1.04, "탄산음료 약 1.04"), ("토닉워터", 1.03, "탄산음료"),
    ("에이드", 1.04, "가당 음료"), ("음료", 1.04, "가당 음료 약 1.04"), ("워터", 1.0, "물 기준"),
    ("라떼", 1.03, "우유 음료"), ("에스프레소", 1.0, "커피 추출액"), ("커피", 1.01, "액상 커피"),
    ("막걸리", 1.01, "탁주 약 1.01"), ("브리즈", 1.02, "식물성 음료"), ("요거트", 1.05, "발효유"),
    ("휘핑크림", 1.0, "크림류 약 1.0"), ("크림", 1.0, "크림류 약 1.0"),
    ("기름", 0.92, "식물성 유지 0.92"), ("오일", 0.92, "식물성 유지 0.92"),
    ("시럽", 1.32, "당 시럽 약 1.3"), ("농축액", 1.25, "농축 과즙·추출액 약 1.25"), ("즙", 1.03, "착즙액"),
    ("소스", 1.15, "액상 소스 평균 약 1.15"), ("드레싱", 1.0, "드레싱 약 1.0"), ("장", 1.2, "액상 장류 약 1.2"),
    ("아이스크림", 0.6, "아이스크림은 공기 포함 약 0.55–0.65"),
]
EACH_SEED = [                       # (식재료 이름에 들어 있는 말, 개당 g, 근거)
    ("달걀", 60.0, "인계서: 달걀 1개 약 60 g (대란 52–60 g)"),
    ("메추리알", 10.0, "메추리알 1개 약 10 g"),
    ("두부", 300.0, "두부 1모 약 300 g (제품마다 다름 — 규격에 g 이 있으면 그걸 먼저 씀)"),
]


class Converter:
    def __init__(self, rows: list[dict] | None = None):
        """rows = unit_conversions 테이블 [{key, kind: density|each, value, basis}] (없으면 초기값)"""
        self.density = [(k, v, b) for k, v, b in DENSITY_SEED]
        self.each = [(k, v, b) for k, v, b in EACH_SEED]
        for r in rows or []:
            target = self.density if r.get("kind") == "density" else self.each
            target.insert(0, (r["key"], float(r["value"]), r.get("basis") or "표"))
        self.density.sort(key=lambda x: -len(x[0]))
        self.each.sort(key=lambda x: -len(x[0]))

    def _lookup(self, table, names: list[str]):
        for k, v, b in table:
            if any(k in n for n in names):
                return v, b
        return None, None

    def grams(self, spec, unit, names: list[str], item_nm: Optional[str] = None) -> tuple[Optional[float], str]:
        """(포장 g, 근거). names = 식재료 이름들 (밀도·개당 중량 조회용).
        규격에서 못 읽으면 상품명에서 읽는다 (사조: '[키즈]우목심(…)불고기용_500G', '연세우유(1000ML)')."""
        g, is_vol = pack_grams(spec, unit)
        from_name = False
        if not g and isinstance(item_nm, str):
            g, is_vol = pack_grams(re.sub(r"^.*?[_(\s](?=\d)", "", item_nm) if re.search(r"\d", item_nm) else "", unit)
            from_name = bool(g)
        if g:
            if not is_vol:
                return g, "상품명 중량" if from_name else "규격 중량"
            d, b = self._lookup(self.density, names)
            if d is None:
                return None, "부피 단위인데 밀도 없음"
            return g * d, f"부피×밀도 {d} ({b})"
        spec = spec if isinstance(spec, str) else ""
        unit = unit if isinstance(unit, str) else ""
        s = unicodedata.normalize("NFKC", f"{spec} {unit}")
        m = re.search(r"(\d+)\s*(개|구|입|ea|모|알)", s, re.I)
        n = int(m.group(1)) if m else (1 if (unit or "").strip().lower() in ("ea", "개") else None)
        if n:
            w, b = self._lookup(self.each, names)
            if w:
                return n * w, f"{n}개×{w}g ({b})"
        return None, "규격 환산 불가"


def price_with_tax(row: dict) -> Optional[float]:
    """세금 포함 단가. 사조는 세포함가가 없어 과세면 ×1.1 (routers/prices.shape 와 같음)."""
    def num(v):
        try:
            x = float(v)
            return None if x != x else x
        except (TypeError, ValueError):
            return None
    pt = num(row.get("unit_price_tax"))
    if pt:
        return pt
    p = num(row.get("unit_price"))
    if p is None:
        return None
    return round(p * 1.1) if (row.get("tax_type") or "") == "과세" else p

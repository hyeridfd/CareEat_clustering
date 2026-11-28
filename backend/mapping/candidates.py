# -*- coding: utf-8 -*-
"""③ 후보 찾기 (빠르고 저렴하게).

두 가지를 합친다.
  1) 이름 관계: 식재료 이름 형태가 상품 핵심 이름과 같거나, 그 끝·앞에 붙어 있는가 (사전 조회, O(이름 길이²))
  2) 글자 유사도: 글자 1–3gram TF-IDF 코사인 (같은 말·띄어쓰기·오타를 잡는다)
선택적으로 3) 한국어 문장 임베딩 (sentence-transformers 가 설치돼 있고 MAPPING_EMBED_MODEL 이 있으면)
"""
import os
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from . import config as C
from .normalize import Ingredient, Product


class FormIndex:
    """이름 형태 → [(식재료 번호, 'P'|'S')]"""

    def __init__(self, ings: list[Ingredient]):
        self.ings = ings
        self.idx: dict[str, list] = defaultdict(list)
        for k, ing in enumerate(ings):
            if ing.not_product:
                continue
            for f in ing.forms_primary:
                self.idx[f].append((k, "P"))
            for f in ing.forms_secondary:
                self.idx[f].append((k, "S"))
        self.max_len = max((len(f) for f in self.idx), default=1)
        # 둘 이상의 식재료가 같은 형태를 가지면 그 형태만으로는 확정할 수 없다 ('고추' ⊂ 홍고추·풋고추)
        # 같은 형태를 대표 이름(P)으로 가진 식재료가 여럿이면 주인을 정한다:
        #   대표 원재료명(괄호 앞)이 그 형태와 같은 식재료 → 여럿이면 사용량 순위가 높은 쪽.
        #   '달걀' → 달걀 (달걀(난황)·달걀(난백)은 같은코드 이름으로 내림),  '마늘' → 마늘(다진것) (마늘(분말)보다 많이 씀)
        #   주인이 없으면 그대로 둔다 → 공유 형태('고추' ⊂ 홍고추·풋고추) = 자동 승인 안 함
        from .lexicon import EXTRA_FORMS
        from .normalize import _split_name, canon
        self.co: dict[str, set] = {}                      # 형태 → 같은 재료로 보는 공동 주인들

        def same_food(a, b):
            """괄호가 용도·설명뿐이면 같은 재료: 고추씨 / 고추씨(육수용), 가람마살라 / 가람마살라(인도향신료),
            보리새우(말린것) / 보리새우(말린것_육수용)"""
            from .normalize import _USE_QUAL, states_in

            def core(ing):
                base, quals = _split_name(ing.rep_name)
                return base, tuple(sorted(q for q in quals if not _USE_QUAL.search(q)))
            if a.animal or b.animal:
                return False
            if core(a) == core(b):
                return True
            if core(a)[0] != core(b)[0]:                     # 바탕 이름부터 달라야 다른 재료: 호박 / 호박잎
                return False
            for ing in (a, b):
                if ing.required_state or ing.animal:
                    return False
                for q in _split_name(ing.rep_name)[1]:
                    if not _USE_QUAL.search(q) and (states_in(q) - {"RAW"} or len(q) <= 3):
                        return False
            return True
        claim = {}
        for k, ing in enumerate(ings):
            base = _split_name(ing.rep_name)[0]
            claim[k] = {base, canon(ing.rep_name)} | {canon(x) for x in EXTRA_FORMS.get(ing.rep_name, [])}
        for f, v in self.idx.items():
            ps = [k for k, t in v if t == "P"]
            if len(set(ps)) < 2:
                continue
            owners = [k for k in ps if f in claim[k]]
            if not owners:                                   # 아무도 대표로 안 가진 형태: 모두 같은 재료면 공동 주인
                if len(ps) > 1 and all(same_food(ings[ps[0]], ings[k]) for k in ps[1:]):
                    self.co[f] = set(ps)
                continue

            def prio(k):
                exact = canon(ings[k].rep_name) == f                      # '꽁치' 는 꽁치가, 꽁치(통조림)보다 먼저
                return (not exact, ings[k].rank or 10 ** 6)
            owner = min(owners, key=prio)
            co = {owner} | {k for k in owners if same_food(ings[owner], ings[k])}
            self.co[f] = co
            self.idx[f] = [(k, t if (k in co or t == "S") else "S") for k, t in v]
        self.p_owners = {f: {k for k, t in v if t == "P"} for f, v in self.idx.items()}
        self.shared = {f for f, ks in self.p_owners.items() if len(ks - self.co.get(f, set())) + (1 if self.co.get(f) else 0) > 1}

    def hits(self, core: str) -> dict:
        """상품 핵심 이름 → {식재료 번호: [(관계, 형태, 'P'|'S')]}  관계 = exact | suffix | prefix"""
        out = defaultdict(list)
        n = len(core)
        if n == 0:
            return out
        for k, t in self.idx.get(core, []):
            out[k].append(("exact", core, t))
        for i in range(1, n):                       # 끝부분 = 형태
            f = core[i:]
            if len(f) < 1 or f not in self.idx:
                continue
            for k, t in self.idx[f]:
                out[k].append(("suffix", f, t))
        for j in range(min(n - 1, self.max_len), 1, -1):   # 앞부분 = 형태 (두 글자 이상)
            f = core[:j]
            if f in self.idx:
                for k, t in self.idx[f]:
                    out[k].append(("prefix", f, t))
        return out


def ingredient_doc(ing: Ingredient) -> str:
    base = sorted(ing.forms_primary, key=len)[:12]
    return " ".join(base + sorted(ing.forms_secondary, key=len)[:6])


class TextSim:
    """글자 n-gram TF-IDF. 식재료 문서와 상품 핵심 이름을 같은 공간에 놓는다."""

    def __init__(self, ings: list[Ingredient]):
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3), min_df=1, sublinear_tf=True)
        self.docs = [ingredient_doc(i) for i in ings]
        self.I = self.vec.fit_transform(self.docs)

    def matrix(self, cores: list[str]):
        return self.vec.transform(cores) @ self.I.T          # (상품 × 식재료) 희소 행렬


class Embedder:
    """선택 기능. 모델이 없으면 꺼진다 (특징값 0)."""

    def __init__(self, ings: list[Ingredient]):
        self.model = None
        name = os.getenv("MAPPING_EMBED_MODEL")              # 예: intfloat/multilingual-e5-small
        if not name:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(name)
            self.I = self.model.encode([f"query: {i.rep_name} {i.mfds_name or ''}" for i in ings],
                                       normalize_embeddings=True)
        except Exception as e:                                # noqa: BLE001
            print(f"[mapping] 임베딩 끔: {e}")
            self.model = None

    def sims(self, products: list[Product], pairs: list[tuple[int, int]]) -> np.ndarray:
        if self.model is None or not pairs:
            return np.zeros(len(pairs))
        P = self.model.encode([f"passage: {p.core} {p.attrs[:40]}" for p in products], normalize_embeddings=True)
        return np.array([float(P[pi] @ self.I[ki]) for pi, ki in pairs])


def candidate_pairs(products: list[Product], ings: list[Ingredient], fidx: FormIndex, tsim: TextSim,
                    topk_ing: int = C.TOPK_PER_INGREDIENT, topk_prod: int = C.TOPK_PER_PRODUCT,
                    min_sim: float = C.MIN_SIM) -> dict:
    """{(상품 번호, 식재료 번호): {'sim': 글자유사도, 'hits': [...]}}
    = 이름 관계가 있는 쌍 전부 ∪ 식재료별·공급사별 유사도 상위 k ∪ 상품별 유사도 상위 k (min_sim 이상)."""
    out: dict = {}
    S = tsim.matrix([p.core or p.item_nm for p in products]).tocsr()
    meat_ings = defaultdict(list)
    for k, ing in enumerate(ings):
        if ing.animal and not ing.not_product:
            meat_ings[ing.animal].append(k)

    def add(pi, ki, hit=None):
        key = (pi, ki)
        if key not in out:
            out[key] = {"sim": float(S[pi, ki]), "hits": []}
        if hit:
            out[key]["hits"].append(hit)

    for pi, p in enumerate(products):
        for ki, hs in fidx.hits(p.core).items():
            for h in hs:
                add(pi, ki, h)
        if p.animal:                                          # 육류: 같은 동물의 식재료는 모두 후보 (부위로 판정)
            for ki in meat_ings.get(p.animal, []):
                add(pi, ki)
        row = S.getrow(pi)
        if row.nnz:
            order = np.argsort(-row.data)[:topk_prod]
            for j in order:
                if row.data[j] >= min_sim:
                    add(pi, int(row.indices[j]))

    St = S.T.tocsr()                                          # 식재료 → 상품
    by_sup = defaultdict(list)
    for pi, p in enumerate(products):
        by_sup[p.supplier].append(pi)
    sup_of = np.array([p.supplier for p in products])
    for ki, ing in enumerate(ings):
        if ing.not_product:
            continue
        row = St.getrow(ki)
        if not row.nnz:
            continue
        for sup in by_sup:
            mask = sup_of[row.indices] == sup
            if not mask.any():
                continue
            idx, val = row.indices[mask], row.data[mask]
            for j in np.argsort(-val)[:topk_ing]:
                if val[j] >= min_sim:
                    add(int(idx[j]), ki)
    return out

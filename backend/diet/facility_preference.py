"""
facility_preference.py  ─  시설 단위 선호도 (2026-10-19)
========================================================
개인별 점수를 다수결(0.3/0.7)로 모으던 방식 대신, 시설 전체가 메뉴를 평균적으로
얼마나 드시는지를 0~1 연속값으로 추정합니다. (MOPI-HFRS의 '비슷한 음식끼리 정보 공유' 아이디어를
그래프 신경망 대신 메뉴 속성 회귀로 가볍게 구현)

[1] 끼니별 시설 섭취율   배식 1회(일자·식사·메뉴)마다 어르신 평균 섭취율
                          최근 기록일수록 가중치 ↑ (반감기 HALF_LIFE_DAYS)
[2] 속성 모델            메뉴 속성(카테고리·조리법·주재료군·양념·물성)으로 [1]을 설명하는 릿지 회귀
                          → 배식된 적 없는 메뉴, 고령친화식품도 선호 예측 가능
[3] 기록 수 보정          점수 = (n·관측 평균 + K·속성 예측) / (n + K)
                          n = 최근 가중 배식 횟수 → 적게 나온 메뉴는 속성 예측 쪽으로 당겨짐

[입력]  data/잔반기록.xlsx  (열: 일자 · 식사 · 음식명 · 구분 · 섭취율  [선택: 기존식사형태, 제공량_g, 잔반량_g])
[출력]  pool_preference_scores.json   ← candidate_agent가 pool preference_score로 사용 (NSGA-II f3)
        product_preference_scores.json ← substitute_agent가 제품 선호로 사용
        시설선호도_보고서.xlsx          ← 메뉴별 점수 · 속성 효과 (영양사 확인용)

[식사형태 그룹] GROUP_BY_TEXTURE = True 이면 일반찬 / 다진찬·죽식 그룹별 점수도 계산 (기록 적으면 시설 점수로 당김)
"""
import os
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
import json
import numpy as np
import pandas as pd

WASTE_XLSX        = os.path.join(DATA_DIR, "잔반기록.xlsx")
RECIPE_CSV        = os.path.join(DATA_DIR, "recipes.csv")
POOL_SCORES_PATH  = "pool_preference_scores.json"
PRODUCT_SCORES_PATH = "product_preference_scores.json"
REPORT_PATH       = "시설선호도_보고서.xlsx"

HALF_LIFE_DAYS    = 28     # 이 일수만큼 지난 기록은 가중치 절반
SHRINK_K          = 0.5    # 기록 수 보정 강도 (배식 1회 → 관측 2/3 · 예측 1/3)
RIDGE_LAMBDA      = 2.0    # 속성 회귀 규제 (클수록 시설 평균 쪽으로)
MIN_RESIDENTS     = 5      # 한 끼에 이보다 적게 드신 기록은 제외 (외출·결식 등)
GROUP_BY_TEXTURE  = False  # True: 일반찬 / 다진찬·죽식 그룹 점수 추가
DEFAULT_SCORE     = 0.7    # 잔반 기록이 전혀 없을 때

# ── 메뉴 속성 ─────────────────────────────────────────────────
_METHOD = [("볶음", "볶음"), ("무침", "무침"), ("조림", "조림"), ("찜", "찜"), ("샐러드", "샐러드"),
           ("전 및 부침", "전"), ("튀김", "튀김"), ("구이", "구이"), ("장아찌", "절임"), ("김치", "김치")]
_MAIN = [
    ("생선", ("고등어", "꽁치", "삼치", "갈치", "임연수", "가자미", "동태", "명태", "코다리", "연어", "조기", "참치", "황태", "북어", "대구", "멸치", "생선")),
    ("해산물", ("오징어", "새우", "낙지", "주꾸미", "조개", "바지락", "홍합", "굴", "게살", "어묵", "맛살", "해물")),
    ("돼지", ("돼지", "베이컨", "햄", "소시지", "돈육", "목살", "미트볼")),
    ("소", ("쇠고기", "소고기", "차돌", "너비아니")),
    ("닭", ("닭", "오리")),
    ("두부콩", ("두부", "유부", "콩", "청국장")),
    ("달걀", ("달걀", "계란", "메추리알")),
    ("해조", ("미역", "다시마", "파래", "톳", "매생이", "꼬시래기", "우뭇가사리", "김(")),
    ("버섯", ("버섯",)),
    ("면떡", ("국수", "떡", "당면", "수제비", "만두", "면")),
    ("과일", ("사과", "딸기", "배(", "귤", "바나나", "파인애플", "포도")),
]
_NOT_MAIN = ("물", "소금", "간장", "설탕", "기름", "참기름", "식용유", "들기름", "깨", "마늘", "대파", "쪽파", "양파",
             "생강", "고춧가루", "고추장", "된장", "물엿", "올리고당", "식초", "후추", "육수", "멸치육수", "다시")


def _group_of(text: str) -> str:
    for g, kws in _MAIN:
        if any(k in text for k in kws):
            return g
    return "채소"


def _method_of(text: str) -> str:
    for k, m in _METHOD:
        if k in text:
            return m
    return "국탕" if any(k in text for k in ("국", "탕", "찌개", "전골", "스프")) else "기타"


def recipe_features(path: str = RECIPE_CSV) -> dict:
    """{메뉴명: {cat, method, main, spicy, soy, doenjang}}"""
    r = pd.read_csv(path)
    out = {}
    for name, g in r.groupby("음식명"):
        ings = g[["원재료명", "원재료 중량 (실사용량)"]].fillna(0)
        cand = ings[~ings["원재료명"].astype(str).str.startswith(_NOT_MAIN)]
        main = cand.sort_values("원재료 중량 (실사용량)", ascending=False)["원재료명"].astype(str)
        names = " ".join(ings["원재료명"].astype(str))
        out[name] = {
            "cat": str(g["구분"].iloc[0]),
            "method": _method_of(f"{g['조리법 유형'].iloc[0]} {g['중분류'].iloc[0]} {name}"),
            "main": _group_of(main.iloc[0] if len(main) else name),
            "spicy": int(any(k in names for k in ("고추장", "고춧가루", "청양"))),
            "soy": int("간장" in names),
            "doenjang": int("된장" in names),
        }
    return out


def product_features(products: dict) -> dict:
    """대체 제품 {칸: [제품]} → {제품명: 속성} (제품명 키워드 기준)"""
    out = {}
    for slot, items in products.items():
        for p in items:
            n = p["menu_name"]
            out[n] = {"cat": slot, "method": _method_of(n), "main": _group_of(n),
                      "spicy": int(any(k in n for k in ("고추장", "매운", "제육"))),
                      "soy": int(any(k in n for k in ("간장", "장조림", "데리야끼"))), "doenjang": int("된장" in n),
                      "texture": "적합"}
    return out


# ── 잔반 → 끼니별 시설 섭취율 ────────────────────────────────
def load_waste(path: str = WASTE_XLSX) -> pd.DataFrame:
    if not os.path.exists(path):
        return None
    xl = pd.ExcelFile(path)
    for sh in xl.sheet_names:
        df = pd.read_excel(xl, sheet_name=sh)
        if {"일자", "식사", "음식명"} <= set(df.columns):
            break
    else:
        raise ValueError(f"{path}: '일자·식사·음식명' 열이 있는 시트가 없습니다.")
    if "섭취율" not in df.columns:
        df["섭취율"] = 1 - df["잔반량_g"] / df["제공량_g"].replace(0, np.nan)
    df["섭취율"] = pd.to_numeric(df["섭취율"], errors="coerce").clip(0, 1)
    df["일자"] = pd.to_datetime(df["일자"])
    return df.dropna(subset=["섭취율"])


def _texture_group(s: str) -> str:
    s = str(s)
    return "다진찬·죽식" if ("다진" in s or "갈" in s or "죽" in s) else "일반찬"


def serving_table(df: pd.DataFrame, group: str = None) -> pd.DataFrame:
    """배식 1회 단위 시설(또는 그룹) 평균 섭취율 + 최근 가중치"""
    if group:
        df = df[df["기존식사형태"].map(_texture_group) == group]
    s = (df.groupby(["일자", "식사", "음식명"])
           .agg(섭취율=("섭취율", "mean"), 인원=("섭취율", "size"), 구분=("구분", "first"))
           .reset_index())
    s = s[s["인원"] >= MIN_RESIDENTS]
    age = (df["일자"].max() - s["일자"]).dt.days
    s["w"] = 0.5 ** (age / HALF_LIFE_DAYS)
    return s


def menu_observed(serv: pd.DataFrame) -> pd.DataFrame:
    g = serv.assign(wy=serv["섭취율"] * serv["w"]).groupby("음식명")
    m = pd.DataFrame({"n": g["w"].sum(), "y": g["wy"].sum() / g["w"].sum(),
                      "배식횟수": g.size(), "구분": g["구분"].first()})
    return m


# ── 속성 회귀 (릿지) ──────────────────────────────────────────
class AttributeModel:
    KEYS = ["cat", "method", "main", "texture"]
    FLAGS = ["spicy", "soy", "doenjang"]

    def fit(self, feats: list, y: np.ndarray, w: np.ndarray, lam: float = RIDGE_LAMBDA):
        self.cols = sorted({f"{k}={f.get(k)}" for f in feats for k in self.KEYS}) + self.FLAGS
        X = self._X(feats)
        self.mu = float(np.average(y, weights=w))
        W = np.diag(w)
        A = X.T @ W @ X + lam * np.eye(X.shape[1])
        self.beta = np.linalg.solve(A, X.T @ W @ (y - self.mu))
        return self

    def _X(self, feats):
        idx = {c: i for i, c in enumerate(self.cols)}
        X = np.zeros((len(feats), len(self.cols)))
        for r, f in enumerate(feats):
            for k in self.KEYS:
                j = idx.get(f"{k}={f.get(k)}")
                if j is not None:
                    X[r, j] = 1
            for k in self.FLAGS:
                X[r, idx[k]] = f.get(k, 0)
        return X

    def predict(self, feats: list) -> np.ndarray:
        return np.clip(self.mu + self._X(feats) @ self.beta, 0.05, 1.0)

    def effects(self) -> pd.DataFrame:
        return (pd.DataFrame({"속성": self.cols, "효과(섭취율)": np.round(self.beta, 3)})
                  .sort_values("효과(섭취율)"))


def _feat(name, cat, rf, texture_pol):
    f = dict(rf.get(name) or {"cat": cat, "method": _method_of(name), "main": _group_of(name),
                              "spicy": 0, "soy": 0, "doenjang": 0})
    f["cat"] = cat or f["cat"]
    f["texture"] = (texture_pol.get((f["cat"], name)) or {}).get("texture", "주의")
    return f


def fit_scores(pool: dict, waste: pd.DataFrame, products: dict = None, group: str = None,
               base_scores: dict = None, verbose: bool = True) -> dict:
    """pool(+제품) 메뉴별 시설 점수 계산 → {"pool": {메뉴: 점수}, "product": {...}, "model", "obs"}"""
    from .meal_rules import load_policy
    rf, pol = recipe_features(), load_policy()
    obs = menu_observed(serving_table(waste, group))
    feats = [_feat(n, r["구분"], rf, pol) for n, r in obs.iterrows()]
    model = AttributeModel().fit(feats, obs["y"].to_numpy(), obs["n"].to_numpy())

    def score(name, cat):
        prior = model.predict([_feat(name, cat, rf, pol)])[0]
        if base_scores and name in base_scores:          # 그룹 점수: 시설 점수를 사전값으로
            prior = base_scores[name]
        if name in obs.index:
            n, y = obs.at[name, "n"], obs.at[name, "y"]
            return float((n * y + SHRINK_K * prior) / (n + SHRINK_K))
        return float(prior)

    pool_scores = {m["menu_name"]: round(score(m["menu_name"], cat), 3) for cat, ms in pool.items() for m in ms}
    for name, r in obs.iterrows():                       # pool에 없는 관측 메뉴도 보관
        pool_scores.setdefault(name, round(score(name, r["구분"]), 3))
    prod_scores = {}
    if products:
        pf = product_features(products)
        prod_scores = {n: round(float(model.predict([f])[0]), 3) for n, f in pf.items()}
    if verbose:
        tag = f"[{group}] " if group else ""
        print(f"  [시설 선호도] {tag}관측 메뉴 {len(obs)}개 · 배식 {int(obs['배식횟수'].sum())}회 · "
              f"시설 평균 섭취율 {model.mu:.3f} · 점수 범위 {min(pool_scores.values()):.2f}~{max(pool_scores.values()):.2f}")
    return {"pool": pool_scores, "product": prod_scores, "model": model, "obs": obs}


def cross_validate(waste: pd.DataFrame) -> pd.DataFrame:
    """처음 나오는 메뉴 예측력: 메뉴 하나씩 빼고 나머지로 학습 → 뺀 메뉴의 시설 섭취율 예측 (LOO)"""
    from .meal_rules import load_policy
    rf, pol = recipe_features(), load_policy()
    obs = menu_observed(serving_table(waste))
    feats = [_feat(n, r["구분"], rf, pol) for n, r in obs.iterrows()]
    y, w = obs["y"].to_numpy(), obs["n"].to_numpy()
    pred_attr, pred_mean = [], []
    for i in range(len(obs)):
        keep = np.arange(len(obs)) != i
        m = AttributeModel().fit([feats[j] for j in np.where(keep)[0]], y[keep], w[keep])
        pred_attr.append(m.predict([feats[i]])[0]); pred_mean.append(m.mu)
    # 기존 방식: 개인 EMA(0.7에서 시작) → 과반 기피(<0.65)면 0.3, 아니면 0.7
    per = waste.assign(ema=0.85 * 0.7 + 0.15 * waste["섭취율"])
    old = per.groupby("음식명")["ema"].apply(lambda s: 0.3 if (s < 0.65).mean() > 0.5 else 0.7).reindex(obs.index)
    res = pd.DataFrame({
        "방식": ["기존 (0.3/0.7)", "시설 평균 하나", "속성 모델 (신규)"],
        "MAE": [np.mean(np.abs(old - y)), np.mean(np.abs(np.array(pred_mean) - y)), np.mean(np.abs(np.array(pred_attr) - y))],
        "상관계수": [np.nan if np.std(old) == 0 else np.corrcoef(old, y)[0, 1], np.nan, np.corrcoef(pred_attr, y)[0, 1]],
    })
    res["MAE"] = res["MAE"].round(4); res["상관계수"] = res["상관계수"].round(3)
    return res


def save_report(result: dict, cv: pd.DataFrame = None, path: str = REPORT_PATH, groups: dict = None):
    obs = result["obs"].copy()
    obs["시설점수"] = [result["pool"].get(n) for n in obs.index]
    with pd.ExcelWriter(path) as w:
        top = obs.sort_values("시설점수").reset_index().rename(columns={"index": "음식명", "y": "관측 섭취율", "n": "가중 배식횟수"})
        top[["음식명", "구분", "배식횟수", "관측 섭취율", "시설점수"]].round(3).to_excel(w, sheet_name="배식메뉴_점수", index=False)
        unseen = {k: v for k, v in result["pool"].items() if k not in obs.index}
        pd.DataFrame(sorted(unseen.items(), key=lambda x: x[1]), columns=["음식명", "예측 점수"]).to_excel(w, sheet_name="미배식메뉴_예측", index=False)
        if result["product"]:
            pd.DataFrame(sorted(result["product"].items(), key=lambda x: -x[1]), columns=["제품", "예측 점수"]).to_excel(w, sheet_name="제품_예측", index=False)
        result["model"].effects().to_excel(w, sheet_name="속성효과", index=False)
        if cv is not None:
            cv.to_excel(w, sheet_name="검증", index=False)
        if groups:
            pd.DataFrame(groups).round(3).to_excel(w, sheet_name="식사형태별")
    print(f"  [시설 선호도] 보고서 → {path}")


def update_facility_preference(pool: dict, waste_path: str = WASTE_XLSX, products: dict = None) -> dict:
    """잔반 → 시설 점수 계산 · 저장. 반환: 점수를 반영한 pool"""
    waste = load_waste(waste_path)
    if waste is None or waste.empty:
        print(f"  [시설 선호도] ⚠ {waste_path} 없음 → 기존 점수 유지")
        return pool
    res = fit_scores(pool, waste, products)
    groups = None
    if GROUP_BY_TEXTURE and "기존식사형태" in waste.columns:
        groups = {g: fit_scores(pool, waste, None, g, base_scores=res["pool"])["pool"] for g in ("일반찬", "다진찬·죽식")}
    with open(POOL_SCORES_PATH, "w", encoding="utf-8") as f:
        json.dump(res["pool"], f, ensure_ascii=False, indent=2)
    with open(PRODUCT_SCORES_PATH, "w", encoding="utf-8") as f:
        json.dump(res["product"], f, ensure_ascii=False, indent=2)
    if groups:
        with open("pool_preference_scores_by_group.json", "w", encoding="utf-8") as f:
            json.dump(groups, f, ensure_ascii=False, indent=2)
    save_report(res, cross_validate(waste), groups=groups)
    return {cat: [{**m, "preference_score": res["pool"].get(m["menu_name"], DEFAULT_SCORE)} for m in ms]
            for cat, ms in pool.items()}


def load_product_scores() -> dict:
    if os.path.exists(PRODUCT_SCORES_PATH):
        with open(PRODUCT_SCORES_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


if __name__ == "__main__":   # 단독 실행: python facility_preference.py  (pool_dump.json 기준)
    from .sodium_config import apply_sodium_adjustment
    from .substitute_agent import load_products
    pool = apply_sodium_adjustment(json.load(open("pool_dump.json", encoding="utf-8")), verbose=False)
    update_facility_preference(pool, products=load_products())

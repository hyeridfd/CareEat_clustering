"""
inventory.py  ─  재고 활용 (2026-10-19)
=======================================
[데이터]  data/재고.xlsx  ('재고' 시트: 식재료명 · 재고량(g) · 유통기한 / '설정' 시트: 식단 시작일)
          data/# (senior)음식_레시피_1.csv  (메뉴별 원재료 · 실사용량)

[사용처]
  ① OptimizerAgent f2  : 예산 초과 + INV_WEIGHT × 재고 미활용률
  ② meal_form.py       : 일반식에서 쓰고 남은 재고 → 죽식 어르신 점심·저녁 영양죽 선택

[재고 미활용률] 0(재고를 유통기한 안에 모두 사용) ~ 1(전혀 사용 안 함)
  · 식재료 k의 사용량 = 유통기한 전날까지 식단에서 쓰인 양 (인원수 × 1인분 실사용량 × 배식 비율)
  · 가중치 w_k = 1 + (URGENT_DAYS − 남은 일수)/URGENT_DAYS  (유통기한이 가까울수록 최대 2배)
  · 미활용률 = 1 − Σ w_k·min(재고_k, 사용량_k) / Σ w_k·재고_k

[식재료명 매칭] 재고 '두부' ↔ 레시피 '두부', '두부(부침용)'  (이름이 같거나 '이름(' 으로 시작)
                재고 '돼지고기(앞다리)' ↔ 레시피 '돼지고기(앞다리)'만
"""
import os
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
import datetime as dt
import numpy as np
import pandas as pd

INVENTORY_XLSX = os.path.join(DATA_DIR, "재고.xlsx")
RECIPE_CSV     = os.path.join(DATA_DIR, "recipes.csv")
INV_WEIGHT     = 1.0      # f2에 더하는 재고 미활용률 가중치 (0이면 재고 무시)
URGENT_DAYS    = 14       # 유통기한 가중치 기준 일수
PLAN_DAYS      = 28


def load_inventory(path: str = INVENTORY_XLSX):
    """재고.xlsx → {"items": DataFrame(식재료명, 재고량(g), 남은일수), "start": date} / 파일 없으면 None"""
    if not os.path.exists(path):
        print(f"  [재고] ⚠ {path} 없음 → 재고 활용 미반영")
        return None
    df = pd.read_excel(path, sheet_name="재고")
    df = df.dropna(subset=["식재료명", "재고량(g)"])
    df["식재료명"] = df["식재료명"].astype(str).str.strip()
    df["재고량(g)"] = pd.to_numeric(df["재고량(g)"], errors="coerce").fillna(0)
    df = df[df["재고량(g)"] > 0]
    try:
        st = pd.read_excel(path, sheet_name="설정")
        start = pd.to_datetime(st.loc[st["항목"] == "식단 시작일", "값"].iloc[0]).date()
    except Exception:
        start = dt.date.today()
    exp = pd.to_datetime(df["유통기한"], errors="coerce")
    df["남은일수"] = [(e.date() - start).days if pd.notna(e) else PLAN_DAYS + 1 for e in exp]
    df = df.groupby("식재료명", as_index=False).agg({"재고량(g)": "sum", "남은일수": "min"})
    print(f"  [재고] {len(df)}개 식재료 · 총 {df['재고량(g)'].sum()/1000:.1f}kg · 식단 시작일 {start}")
    return {"items": df, "start": start}


def _match(inv_name: str, recipe_name: str) -> bool:
    return recipe_name == inv_name or recipe_name.startswith(inv_name + "(")


def recipe_ingredients(path: str = RECIPE_CSV) -> dict:
    """{메뉴명: {원재료명: 실사용량 g}}"""
    r = pd.read_csv(path)
    out = {}
    for (menu, ing), g in r.groupby(["음식명", "원재료명"]):
        out.setdefault(menu, {})[ing] = float(g["원재료 중량 (실사용량)"].fillna(0).sum())
    return out


class InventoryModel:
    """pool 메뉴 × 재고 식재료 사용량 행렬로 염색체별 재고 미활용률을 빠르게 계산"""

    def __init__(self, pool: dict, inventory: dict, n_people: int,
                 recipe_map: dict = None, portion: dict = None):
        from .portion_config import PORTION
        self.items  = inventory["items"].reset_index(drop=True)
        self.names  = list(self.items["식재료명"])
        self.stock  = self.items["재고량(g)"].to_numpy(dtype=float)
        days_left   = self.items["남은일수"].to_numpy(dtype=int)
        self.exp_idx = np.clip(days_left, 0, PLAN_DAYS)            # 이 일차 전까지 사용 가능
        urgency     = np.clip((URGENT_DAYS - days_left) / URGENT_DAYS, 0, 1)
        self.w      = np.where(days_left > 0, 1.0 + urgency, 0.0)  # 이미 지난 재고는 제외
        self.n_people = n_people
        recipe_map  = recipe_map or recipe_ingredients()
        portion     = portion or PORTION
        K = len(self.names)
        self.M = {}
        self.name_index = {}
        for cat, menus in pool.items():
            mat = np.zeros((len(menus), K))
            for i, m in enumerate(menus):
                ings = m.get("ingredients") or recipe_map.get(m["menu_name"], {})
                p = m.get("portion", portion.get(cat, 1.0))
                for k, inv in enumerate(self.names):
                    g = sum(v for nm, v in ings.items() if _match(inv, nm))
                    mat[i, k] = g * p * n_people
                self.name_index[(cat, m["menu_name"])] = (cat, i)
            self.M[cat] = mat
        used = {cat: int((mat.sum(1) > 0).sum()) for cat, mat in self.M.items()}
        print(f"  [재고] 재고 식재료를 쓰는 후보 메뉴 수 {used}")

    # ── 최적화용 ─────────────────────────────────────────────
    def daily_usage_chrom(self, chrom, daily_slots, n_slots) -> np.ndarray:
        """염색체 → (28, K) 일자별 식재료 사용량"""
        U = np.zeros((PLAN_DAYS, len(self.names)))
        chrom = np.asarray(chrom, dtype=int)
        for s, (_, cat) in enumerate(daily_slots):
            mat = self.M[cat]
            idx = chrom[s::n_slots][:PLAN_DAYS] % len(mat)
            U += mat[idx]
        return U

    def unused_score(self, U: np.ndarray) -> float:
        total = float((self.w * self.stock).sum())
        if total <= 0:
            return 0.0
        cum = np.vstack([np.zeros((1, U.shape[1])), np.cumsum(U, axis=0)])   # cum[d] = d일 전까지
        use = cum[self.exp_idx, np.arange(len(self.names))]
        used = np.minimum(self.stock, use)
        return float(1.0 - (self.w * used).sum() / total)

    # ── 식단표(메뉴명) 기준 ──────────────────────────────────
    def daily_usage_records(self, records: list, slot_cats: list) -> np.ndarray:
        """28일 식단표 records → (28, K)"""
        U = np.zeros((PLAN_DAYS, len(self.names)))
        for r in records:
            d = int("".join(ch for ch in str(r["일차"]) if ch.isdigit()) or 1) - 1
            for slot, cat in slot_cats:
                hit = self.name_index.get((cat, r.get(slot)))
                if hit and 0 <= d < PLAN_DAYS:
                    U[d] += self.M[hit[0]][hit[1]]
        return U

    def report(self, U: np.ndarray) -> pd.DataFrame:
        cum = np.vstack([np.zeros((1, U.shape[1])), np.cumsum(U, axis=0)])
        use = cum[self.exp_idx, np.arange(len(self.names))]
        df = self.items.copy()
        df["유통기한 전 사용량(g)"] = np.round(np.minimum(self.stock, use))
        df["남는 양(g)"] = np.round(self.stock - df["유통기한 전 사용량(g)"])
        df["활용률(%)"] = np.round(df["유통기한 전 사용량(g)"] / self.stock * 100, 1)
        return df

-- =====================================================================
-- 공급사 식자재 가격 매핑 (backend/mapping/)
-- price-crawler/supabase_tables.sql 실행 후 Supabase SQL Editor 에서 1회 실행
-- 식재료 키 = 식재료ID (scripts/load_graph.py 와 같은 규칙: Recipe_<식품코드> / Recipe_NAME:<원재료명>)
-- =====================================================================

-- 1) 매핑 대상 식재료 (공급사매핑_대상_식재료.xlsx 를 run 이 매번 반영)
create table if not exists mapping_ingredients (
    ingredient_id   text primary key,
    rep_name        text not null,             -- 대표 원재료명
    names           text,                      -- 같은 코드 레시피 원재료명들 ' | ' 로 연결
    food_code       text,
    mfds_name       text,                      -- 식약처 식품명
    food_group      text,                      -- 식약처 식품대분류
    discard_pct     numeric,                   -- 폐기율(%)
    usage_g         numeric,                   -- 레시피 사용 중량 합 (검수 우선순위)
    rank            int,
    product_status  text default 'product',    -- product | not_product (육수·쌀뜨물 등 조리 중간물)
    updated_at      timestamptz default now()
);

-- 2) 매핑 기억: 한 번 판단한 (상품, 식재료) 쌍
create table if not exists ingredient_product_map (
    ingredient_id   text not null,
    supplier        text not null,             -- hgreenfood | sajo
    item_cd         text not null,
    score           numeric,                   -- 같은 식재료일 확률 0–1
    method          text,                      -- rule | model | llm | human
    status          text not null,             -- auto_approved | approved | pending | rejected | auto_rejected | not_product
    features        jsonb,                     -- 판정 근거 (이름 관계·상태·가공·분류·g당 가격 …)
    reason          text,                      -- 규칙·LLM·사람이 남긴 근거
    model_version   text,
    reviewed_by     text,
    reviewed_at     timestamptz,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now(),
    primary key (supplier, item_cd, ingredient_id)
);
create index if not exists ipm_ing_idx on ingredient_product_map (ingredient_id, status);
create index if not exists ipm_status_idx on ingredient_product_map (status);

-- 3) 한 번 판단한 상품 (다음 날부터는 여기에 없는 상품만 판단)
create table if not exists mapping_seen_products (
    supplier    text not null,
    item_cd     text not null,
    first_seen  date,
    n_pairs     int,
    primary key (supplier, item_cd)
);

-- 4) 식재료별 하루 가격 (앱 식단 비용은 price_per_g_28d 만 읽는다)
create table if not exists ingredient_price_daily (
    ingredient_id    text not null,
    price_date       date not null,
    price_per_g      numeric,                  -- 오늘 가장 싼 승인 상품의 g당 가격 (세금 포함). 없으면 null
    supplier         text,                     -- 선택된 상품 (구매 안내용)
    item_cd          text,
    item_nm          text,
    n_candidates     int,                      -- 오늘 판매 중인 승인 상품 수 (두 공급사 합)
    price_per_g_28d  numeric,                  -- 최적화용: 최근 28일 오늘 가격의 중앙값
    hgreenfood_min   numeric,                  -- 공급사별 최저 g당 가격과 그 상품
    hgreenfood_item_cd text,
    hgreenfood_item_nm text,
    hgreenfood_n     int,
    sajo_min         numeric,
    sajo_item_cd     text,
    sajo_item_nm     text,
    sajo_n           int,
    primary key (ingredient_id, price_date)
);
-- 이미 테이블을 만들었다면 열만 추가
alter table ingredient_price_daily add column if not exists hgreenfood_item_cd text;
alter table ingredient_price_daily add column if not exists hgreenfood_item_nm text;
alter table ingredient_price_daily add column if not exists hgreenfood_n int;
alter table ingredient_price_daily add column if not exists sajo_item_cd text;
alter table ingredient_price_daily add column if not exists sajo_item_nm text;
alter table ingredient_price_daily add column if not exists sajo_n int;
create index if not exists ipd_date_idx on ingredient_price_daily (price_date);

-- 앱이 읽기 편하도록: 식재료별 가장 최근 가격 1행
create or replace view ingredient_price_latest as
select distinct on (ingredient_id) *
from ingredient_price_daily
order by ingredient_id, price_date desc;

-- 5) 밀도·개당 중량 (비어 있으면 mapping/units.py 기본값 사용, 여기 넣은 값이 우선)
create table if not exists unit_conversions (
    key         text primary key,              -- 식재료 이름에 들어 있는 말 (예: 간장, 달걀) 또는 식재료ID
    kind        text not null,                 -- density | each
    value       numeric not null,              -- 밀도(g/ml) 또는 개당 g
    basis       text,                          -- 근거
    updated_at  timestamptz default now()
);

-- 6) 공급사 분류 ↔ 식약처 식품대분류 (검수 결과로 보완: 승인/거절 수)
create table if not exists category_map (
    supplier     text not null,
    lcls_nm      text not null,
    mcls_nm      text not null,
    food_group   text not null,
    n_approved   int default 0,
    n_rejected   int default 0,
    source       text default 'review',        -- seed | review
    primary key (supplier, lcls_nm, mcls_nm, food_group)
);

-- 검수 대기열: 식재료별 대기 건수 (사용 중량 큰 순으로 보여 준다)
create or replace view mapping_queue as
select i.ingredient_id, i.rep_name, i.food_group, i.usage_g, i.rank,
       count(*) filter (where m.status = 'pending')                          as n_pending,
       count(*) filter (where m.status in ('approved', 'auto_approved'))     as n_approved,
       max(m.score) filter (where m.status = 'pending')                      as top_score
from ingredient_product_map m
join mapping_ingredients i using (ingredient_id)
where i.product_status = 'product'
group by i.ingredient_id, i.rep_name, i.food_group, i.usage_g, i.rank
having count(*) filter (where m.status = 'pending') > 0;

-- 상태별 건수 (통계용)
create or replace view mapping_status_counts as
select status, count(*) as n from ingredient_product_map group by status;

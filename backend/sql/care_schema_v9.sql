-- =====================================================================
-- Care-Eat 확장 v9 — 식재료 재고 추적 (맞춤 식단 설계 > 재고 리포트)
--   care_schema_v8.sql 실행 후 Supabase SQL Editor 에서 1회 실행 (여러 번 실행해도 안전)
--
--   diet_runs.start_date   승인한 식단의 1일차 날짜 → 날짜별 예상 사용량 계산
--   diet_stock_events      입고 · 실사(실제 재고로 보정) · 폐기 기록 (식재료 1개 = 1행)
--   재고 = 마지막 실사 + 입고 − 승인 식단 예상 사용량 − 폐기  (유통기한 빠른 것부터 사용)
-- =====================================================================

alter table diet_runs add column if not exists start_date date;

create table if not exists diet_stock_events (
    id               uuid primary key default gen_random_uuid(),
    nursing_home_id  text not null references nursing_homes(id),
    event_date       date not null,
    kind             text not null check (kind in ('입고', '실사', '폐기')),
    ingredient       text not null,
    qty_g            numeric not null default 0,
    expiry           date,
    note             text,
    created_by       text,
    created_at       timestamptz not null default now()
);
create index if not exists idx_diet_stock_home on diet_stock_events(nursing_home_id, event_date);

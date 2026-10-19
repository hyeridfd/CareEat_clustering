-- =====================================================================
-- Care-Eat 확장 v8 — 맞춤 식단 설계 (솔루션 > 맞춤 식단 설계)
--   care_schema_v7.sql 실행 후 Supabase SQL Editor 에서 1회 실행 (여러 번 실행해도 안전)
--
--   diet_runs              식단 설계 실행 1회 = 1행 (28일 식단표 · 지표 · 대체찬 · 발주 · 죽 계획)
--   diet_servings          실행별 어르신 1명의 28일 배식표 (84끼)
--   diet_inventory         요양원 재고 (식재료 · 양 · 유통기한) — 일반식 최적화 f2 와 영양죽 선택에 사용
--   diet_preferences       요양원 시설 선호도 (잔반 기록 → 메뉴·제품 점수) — f3 와 대체 제품 선택에 사용
--   diet_resident_settings 어르신 식단 설정 (매운 음식 불가 → 백김치)
-- =====================================================================

create table if not exists diet_runs (
    id               uuid primary key default gen_random_uuid(),
    nursing_home_id  text not null references nursing_homes(id),
    status           text not null default 'queued',     -- queued | running | done | failed | approved
    progress         text,                               -- 진행 단계 문구
    params           jsonb not null default '{}'::jsonb,  -- {preset, seed, inventory_used, preference_used}
    menu             jsonb,                               -- 28일 × 3끼 식단표 (일차·끼니·밥~김치·열량·나트륨…)
    metrics          jsonb,                               -- 목적함수 · 파레토 지표 · 영양 기여도 · 식단 규칙 · 재고
    result           jsonb,                               -- 대체찬 · 발주 · 제품 합계 · 죽 계획 · 어르신 요약 · 배식 요약
    error            text,
    parent_run_id    uuid references diet_runs(id),       -- 영양사 수정으로 다시 계산한 경우 원본
    created_by       text,
    approved_by      text,
    approved_at      timestamptz,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);
create index if not exists idx_diet_runs_home on diet_runs(nursing_home_id, created_at desc);

create table if not exists diet_servings (
    run_id      uuid not null references diet_runs(id) on delete cascade,
    elderly_id  text not null references elderly_residents(id),
    meals       jsonb not null,                           -- [{일차, 끼니, 메뉴, 밥(g)…, 예상열량…, 칸별비율, 조정결과}]
    primary key (run_id, elderly_id)
);

create table if not exists diet_inventory (
    nursing_home_id  text primary key references nursing_homes(id),
    items            jsonb not null default '[]'::jsonb,  -- [{식재료명, 재고량(g), 유통기한, 비고}]
    start_date       date,                                -- 식단 1일차 날짜 (유통기한까지 남은 일수 계산)
    updated_by       text,
    updated_at       timestamptz not null default now()
);

create table if not exists diet_preferences (
    nursing_home_id  text primary key references nursing_homes(id),
    pool_scores      jsonb not null default '{}'::jsonb,  -- {메뉴명: 0~1}
    product_scores   jsonb not null default '{}'::jsonb,  -- {제품명: 0~1}
    report           jsonb,                               -- 관측 메뉴 · 속성 효과 · 검증 · 기간
    updated_by       text,
    updated_at       timestamptz not null default now()
);

create table if not exists diet_resident_settings (
    elderly_id       text primary key references elderly_residents(id),
    nursing_home_id  text not null references nursing_homes(id),
    no_spicy         boolean not null default false,      -- 매운 음식 불가 → 김치 칸 백김치
    note             text,
    updated_at       timestamptz not null default now()
);
create index if not exists idx_diet_settings_home on diet_resident_settings(nursing_home_id);

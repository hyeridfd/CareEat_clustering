-- =====================================================================
-- 돌봄 관리(유형 분류 · 우선순위 · 솔루션 · 보호자 알림) 확장 스키마
-- 기존 database_schema.sql 실행 후 Supabase SQL Editor 에서 1회 실행
-- =====================================================================

-- 1) 요양원 담당자 계정
create table if not exists facility_staff (
    id               text primary key,                 -- 로그인 ID
    nursing_home_id  text not null references nursing_homes(id),
    name             text not null,
    role             text not null default 'staff',    -- staff | manager
    password_hash    text not null,                    -- pbkdf2_sha256$iter$salt$hash
    is_active        boolean not null default true,
    created_at       timestamptz not null default now()
);

-- 2) 보호자 (카카오 알림톡 수신자)
create table if not exists guardians (
    id                   uuid primary key default gen_random_uuid(),
    elderly_id           text not null references elderly_residents(id),
    nursing_home_id      text not null references nursing_homes(id),
    name                 text not null,
    relation             text,                          -- 자녀, 배우자 등
    phone                text not null,                 -- 01012345678
    consent_health_info  boolean not null default false,-- 건강정보 제3자 제공·알림 수신 동의
    consent_at           timestamptz,
    is_active            boolean not null default true,
    created_at           timestamptz not null default now()
);
create index if not exists idx_guardians_elderly on guardians(elderly_id);

-- 3) 유형 모델 레지스트리 (모델 파일은 backend/models/<version>/ 에 저장)
create table if not exists type_models (
    version      text primary key,                      -- 예: v1-pilot-n55, v2-n200
    k            int not null,
    type_meta    jsonb not null,                         -- {C1:{name,guardian_label,risk_weight,description}, ...}
    n_train      int,
    parent_version text,                                 -- 이전 모델 (라벨 매칭 기준)
    label_mapping jsonb,                                 -- {new_code: old_code} 및 ARI
    is_active    boolean not null default false,
    notes        text,
    created_at   timestamptz not null default now()
);

-- 4) 유형·우선순위 평가 결과 (실행할 때마다 1행 누적 → 이력/추이)
create table if not exists care_assessments (
    id               uuid primary key default gen_random_uuid(),
    elderly_id       text not null references elderly_residents(id),
    nursing_home_id  text not null references nursing_homes(id),
    model_version    text not null,
    type_code        text not null,                      -- C1, C2 ...
    type_name        text,
    centroid_margin  double precision,                   -- 1·2순위 유형 중심 거리 차
    relative_margin  double precision,                   -- margin / 2순위 거리
    is_borderline    boolean not null default false,     -- 경계 대상 → 담당자 검토
    transition       jsonb,                              -- {prev_type, prev_model, kind: first|same|state_change|model_change}
    priority_score   double precision not null,
    priority_level   text not null,                      -- high | medium | low
    priority_factors jsonb not null,                     -- [{code,label,points,value}]
    features         jsonb not null,                     -- 산출 지표 원값 (추이 비교용)
    imputed_vars     text[],
    survey_updated_at timestamptz,
    created_by       text,
    created_at       timestamptz not null default now()
);
create index if not exists idx_assess_elderly on care_assessments(elderly_id, created_at desc);
create index if not exists idx_assess_home on care_assessments(nursing_home_id, created_at desc);

-- 5) 돌봄 솔루션 (LLM/규칙 초안 → 담당자 수정·승인)
create table if not exists care_solutions (
    id               uuid primary key default gen_random_uuid(),
    assessment_id    uuid not null references care_assessments(id),
    elderly_id       text not null references elderly_residents(id),
    nursing_home_id  text not null references nursing_homes(id),
    generator        text not null,                      -- openai:<model> | anthropic:<model> | rules
    content          jsonb not null,                     -- {summary, staff_actions[], meal_guidance, monitoring[], cautions[]}
    guardian_message text not null,                      -- 보호자용 쉬운 문장
    guardrail_flags  jsonb not null default '[]'::jsonb, -- 검증 경고
    status           text not null default 'draft',      -- draft | approved | rejected | sent
    edited_by        text,
    approved_by      text,
    approved_at      timestamptz,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);
create index if not exists idx_solution_elderly on care_solutions(elderly_id, created_at desc);

-- 6) 보호자 알림 발송 로그
create table if not exists care_notifications (
    id               uuid primary key default gen_random_uuid(),
    solution_id      uuid not null references care_solutions(id),
    guardian_id      uuid not null references guardians(id),
    elderly_id       text not null,
    nursing_home_id  text not null,
    channel          text not null default 'kakao_alimtalk',
    mode             text not null,                      -- dry_run | live
    provider         text,                               -- dryrun | solapi | nhn
    template_code    text not null,
    variables        jsonb not null,
    rendered_text    text not null,
    report_token     text not null unique,               -- 보호자 리포트 링크 토큰
    report_expires_at timestamptz not null,
    status           text not null,                      -- previewed | sent | failed
    provider_response jsonb,
    sent_by          text,
    created_at       timestamptz not null default now()
);

-- 7) 돌봄 수행·결과 기록 (모델 고도화용 결과 데이터)
create table if not exists care_actions (
    id               uuid primary key default gen_random_uuid(),
    elderly_id       text not null references elderly_residents(id),
    nursing_home_id  text not null,
    solution_id      uuid references care_solutions(id),
    action           text not null,
    status           text not null default 'done',       -- planned | done | skipped
    outcome_note     text,
    recorded_by      text,
    recorded_at      timestamptz not null default now()
);
create index if not exists idx_actions_elderly on care_actions(elderly_id, recorded_at desc);

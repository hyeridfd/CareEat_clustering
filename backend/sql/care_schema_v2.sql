-- =====================================================================
-- Care-Eat 확장 (시설 가입 신청) — care_schema.sql 실행 후 1회 실행
-- =====================================================================

create table if not exists facility_applications (
    id               uuid primary key default gen_random_uuid(),
    facility_name    text not null,
    facility_kind    text,
    ltc_code         text,                         -- 장기요양기관 기호
    address          text,
    resident_count   int,
    manager_name     text not null,
    manager_role     text,
    manager_phone    text not null,
    manager_email    text,
    desired_staff_id text,
    message          text,
    status           text not null default 'pending',   -- pending | approved | rejected
    review_note      text,
    nursing_home_id  text references nursing_homes(id), -- 승인 시 생성·연결된 시설
    staff_id         text,                              -- 승인 시 발급된 담당자 계정
    reviewed_by      text,
    reviewed_at      timestamptz,
    created_at       timestamptz not null default now()
);
create index if not exists idx_apps_status on facility_applications(status, created_at desc);

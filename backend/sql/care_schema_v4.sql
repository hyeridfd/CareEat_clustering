-- =====================================================================
-- Care-Eat 확장 (어르신 기본정보·진단·약물·알레르기) — care_schema_v3.sql 실행 후 1회 실행
--
-- elderly_residents 는 설문(IRB) 쪽과 공유하는 테이블이라 건드리지 않고,
-- 돌봄 기록용 정보는 elderly_id 로 연결되는 별도 테이블에 둔다.
-- 건강정보이므로 기존 테이블과 동일하게 nursing_home_id 로 시설 격리한다.
-- =====================================================================

-- 1) 어르신 기본정보 (어르신 1명당 1행)
create table if not exists resident_profiles (
    elderly_id         text primary key references elderly_residents(id),
    nursing_home_id    text not null references nursing_homes(id),
    birth_date         date,
    gender             text,                              -- female | male
    admit_date         date,
    room               text,
    ltc_grade          text,                              -- 장기요양등급: 1~5 | 인지지원 | 등급외 | 미신청
    guardian_name      text,
    guardian_relation  text,
    guardian_phone     text,
    texture_level      int,                               -- 0 일반 | 1 다진 | 2 갈은 | 3 유동
    thickener          text,                              -- 점도증진제: none | mild | moderate | extreme
    therapeutic_diet   text,                              -- 당뇨식, 저염식 등
    banned_foods       jsonb not null default '[]'::jsonb, -- ["갑각류", "견과류"]
    notes              text,
    updated_by         text,
    updated_at         timestamptz not null default now(),
    created_at         timestamptz not null default now()
);
create index if not exists idx_resident_profiles_home on resident_profiles(nursing_home_id);

-- 2) 질병·진단명
create table if not exists resident_conditions (
    id               uuid primary key default gen_random_uuid(),
    elderly_id       text not null references elderly_residents(id),
    nursing_home_id  text not null references nursing_homes(id),
    name             text not null,                       -- 치매, 당뇨병 ...
    status           text not null default 'active',      -- active | resolved
    diagnosed_on     date,
    note             text,
    recorded_by      text,
    created_at       timestamptz not null default now()
);
create index if not exists idx_conditions_elderly on resident_conditions(elderly_id, created_at desc);

-- 3) 복용 약물
create table if not exists resident_medications (
    id               uuid primary key default gen_random_uuid(),
    elderly_id       text not null references elderly_residents(id),
    nursing_home_id  text not null references nursing_homes(id),
    name             text not null,
    dose             text,                                -- "1정", "5mL" 등 표기 그대로
    schedule         jsonb not null default '[]'::jsonb,  -- ["아침","점심","저녁","취침 전","필요시"]
    started_on       date,
    ended_on         date,
    is_active        boolean not null default true,
    food_caution     text,                                -- 음식 궁합·복용 시 주의 (식사 돌봄에 필요)
    note             text,
    recorded_by      text,
    created_at       timestamptz not null default now()
);
create index if not exists idx_medications_elderly on resident_medications(elderly_id, is_active, created_at desc);

-- 4) 알레르기
create table if not exists resident_allergies (
    id               uuid primary key default gen_random_uuid(),
    elderly_id       text not null references elderly_residents(id),
    nursing_home_id  text not null references nursing_homes(id),
    allergen         text not null,                       -- 땅콩, 갑각류 ...
    severity         text not null default 'mild',        -- mild | moderate | severe
    reaction         text,                                -- 두드러기, 호흡곤란 ...
    note             text,
    recorded_by      text,
    created_at       timestamptz not null default now()
);
create index if not exists idx_allergies_elderly on resident_allergies(elderly_id, created_at desc);

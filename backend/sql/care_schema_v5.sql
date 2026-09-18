-- =====================================================================
-- Care-Eat 확장 v5 — 어르신 기본정보에 학력·음주·흡연 추가
-- care_schema_v4.sql 실행 후 1회 실행 (여러 번 실행해도 안전)
-- =====================================================================
alter table resident_profiles add column if not exists education text;   -- 무학 | 초등학교 졸업 | ...
alter table resident_profiles add column if not exists alcohol   text;   -- none | sometimes | often | quit
alter table resident_profiles add column if not exists smoking   text;   -- none | current | quit

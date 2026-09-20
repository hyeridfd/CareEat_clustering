-- =====================================================================
-- Care-Eat 확장 v7 — 근거 각주용 짧은 문헌명
--   리포트의 '근거 문헌' 목록에서 긴 서지사항 대신 쓸 짧은 이름.
--   care_schema_v6.sql 실행 후 1회 실행 (여러 번 실행해도 안전)
--
--   ※ 뷰는 create or replace 로 컬럼을 끼워 넣을 수 없어서(42P16),
--     먼저 지우고 다시 만든다. 뷰는 조회 전용이라 지워도 데이터는 그대로다.
-- =====================================================================
alter table care_sources add column if not exists short text;   -- 예: ESPEN 노인영양 2022

drop view if exists care_knowledge_status;

create view care_knowledge_status as
    select s.id, s.title, s.short, s.org, s.year, s.license, s.enabled,
           count(c.id)        as chunks,
           count(c.embedding) as embedded,
           max(c.created_at)  as last_ingested
    from care_sources s
    left join care_chunks c on c.source_id = s.id
    group by s.id, s.title, s.short, s.org, s.year, s.license, s.enabled
    order by s.id;

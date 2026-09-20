-- =====================================================================
-- Care-Eat 확장 v6 — 근거 문헌 검색(RAG)
--   지침·매뉴얼·논문을 문단 단위로 저장하고, 솔루션 생성 시 의미 검색으로
--   관련 문단을 찾아 LLM 프롬프트의 '참고 지침'으로 넣는다.
--   care_schema_v5.sql 실행 후 1회 실행 (여러 번 실행해도 안전)
--
--   ※ Supabase 대시보드 → Database → Extensions 에서 vector 를 켜도 되고,
--     아래 create extension 한 줄로도 켜진다.
-- =====================================================================
create extension if not exists vector;

-- 1) 문헌 (서지사항)
create table if not exists care_sources (
    id           text primary key,                 -- KDRI2020, LTC_MEAL_MANUAL ...
    title        text not null,                    -- 2020 한국인 영양소 섭취기준
    org          text,                             -- 보건복지부·한국영양학회
    year         int,
    edition      text,
    doc_type     text default 'guideline',         -- guideline | manual | textbook | paper
    license      text,                             -- 공공누리 제1유형 | 오픈액세스 | 내부요약 ...
    url          text,
    citation     text,                             -- 리포트 각주에 그대로 쓸 인용 문구
    enabled      boolean not null default true,    -- false 면 검색에서 제외
    note         text,
    created_at   timestamptz not null default now()
);

-- 2) 문단 청크 + 임베딩 (text-embedding-3-small = 1536차원)
create table if not exists care_chunks (
    id           bigserial primary key,
    source_id    text not null references care_sources(id) on delete cascade,
    section      text,                             -- "3.2 저염식 제공 원칙"
    page         int,
    ord          int not null default 0,           -- 문헌 내 순서
    text         text not null,
    hash         text not null,                    -- 본문 sha1 — 재적재 시 중복 방지
    embedding    vector(1536),
    created_at   timestamptz not null default now(),
    unique (source_id, hash)
);
create index if not exists idx_care_chunks_source on care_chunks(source_id);

-- 코사인 거리 인덱스. 문단 수가 적을 때는 없어도 되지만 수천 건부터 효과가 있다.
create index if not exists idx_care_chunks_embedding on care_chunks
    using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- 3) 의미 검색 함수
--    enabled = true 인 문헌만, 유사도 하한을 넘는 문단을 가까운 순으로 돌려준다.
create or replace function match_care_chunks(
    query_embedding vector(1536),
    match_count     int   default 5,
    min_similarity  float default 0.15,
    only_sources    text[] default null
)
returns table (
    id          bigint,
    source_id   text,
    section     text,
    page        int,
    text        text,
    similarity  float
)
language sql stable
as $$
    select c.id, c.source_id, c.section, c.page, c.text,
           1 - (c.embedding <=> query_embedding) as similarity
    from care_chunks c
    join care_sources s on s.id = c.source_id
    where c.embedding is not null
      and s.enabled
      and (only_sources is null or c.source_id = any(only_sources))
      and 1 - (c.embedding <=> query_embedding) > min_similarity
    order by c.embedding <=> query_embedding
    limit match_count;
$$;

-- 4) 적재 현황 확인용 뷰
create or replace view care_knowledge_status as
    select s.id, s.title, s.org, s.year, s.license, s.enabled,
           count(c.id)                                as chunks,
           count(c.embedding)                         as embedded,
           max(c.created_at)                          as last_ingested
    from care_sources s
    left join care_chunks c on c.source_id = s.id
    group by s.id, s.title, s.org, s.year, s.license, s.enabled
    order by s.id;

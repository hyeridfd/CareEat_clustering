-- =====================================================================
-- Care-Eat 확장 (고령·돌봄 뉴스 브리핑) — care_schema_v2.sql 실행 후 1회 실행
--
-- 뉴스는 시설별 데이터가 아니라 전 시설 공통이므로 nursing_home_id 를 두지 않는다.
-- 조회는 로그인한 담당자·관리자 모두, 수집은 관리자 또는 예약 실행만 수행한다.
-- =====================================================================

-- 1) 날짜별 브리핑 (그날 전체를 아우르는 5줄)
create table if not exists news_briefings (
    brief_date     date primary key,
    lines          jsonb not null default '[]'::jsonb,   -- ["...", "..."]
    article_count  int not null default 0,
    generator      text,                                  -- openai:gpt-4o-mini | rules | empty
    collected_at   timestamptz not null default now(),
    created_at     timestamptz not null default now()
);

-- 2) 기사 (하루치를 다시 수집하면 그 날짜만 지우고 새로 넣는다)
create table if not exists news_articles (
    id             uuid primary key default gen_random_uuid(),
    brief_date     date not null references news_briefings(brief_date) on delete cascade,
    published_at   timestamptz not null,
    title          text not null,
    press          text,
    url            text not null,
    url_key        text not null,                         -- 정규화 URL (같은 날 중복 방지)
    category       text not null,                         -- 노인 전반 | 돌봄·요양 | 고령자 식품·영양 | 정책·제도
    summary        text,
    is_key         boolean not null default false,        -- 그날의 주요 기사
    created_at     timestamptz not null default now()
);
create index if not exists idx_news_articles_date on news_articles(brief_date desc, published_at desc);
create index if not exists idx_news_articles_cat  on news_articles(category, brief_date desc);
create unique index if not exists idx_news_articles_unique on news_articles(brief_date, url_key);

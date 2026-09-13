# 요양원 설문조사 시스템 v2 (FastAPI + React)

Streamlit 기반에서 **FastAPI 백엔드 + React 프론트엔드**로 완전 재작성한 버전입니다.

## 🏗️ 아키텍처

```
[React / Vite]  →  Vercel 배포
      ↕ REST API (JWT 인증)
[FastAPI]       →  AWS (ECS / EC2 / App Runner 등)
      ↕ Supabase Python SDK
[Supabase]      →  PostgreSQL + Storage (기존 그대로 사용)
```

## 📁 프로젝트 구조

```
survey-app/
├── backend/
│   ├── main.py               # FastAPI 앱 진입점
│   ├── dependencies.py       # Supabase 클라이언트, JWT 유틸리티
│   ├── requirements.txt
│   ├── Dockerfile            # AWS 배포용
│   ├── .env.example
│   └── routers/
│       ├── auth.py           # 로그인 (일반 / 관리자)
│       ├── surveys.py        # 설문 조회/저장 (기초/영양/만족도)
│       └── admin.py          # 관리자 대시보드 API
│
└── frontend/
    ├── vite.config.js
    ├── package.json
    ├── tailwind.config.js
    ├── vercel.json
    ├── .env.example
    └── src/
        ├── App.jsx
        ├── main.jsx
        ├── lib/
        │   ├── api.js         # Axios 클라이언트 (JWT 자동 첨부)
        │   └── authStore.js   # Zustand 인증 상태
        ├── components/
        │   ├── FormFields.jsx  # 공통 폼 컴포넌트
        │   └── layout/
        │       └── SurveyLayout.jsx
        └── pages/
            ├── LoginPage.jsx
            ├── DashboardPage.jsx
            ├── AdminPage.jsx
            └── surveys/
                ├── BasicSurveyPage.jsx      # 9페이지
                ├── NutritionSurveyPage.jsx  # 3페이지
                └── SatisfactionSurveyPage.jsx # 4페이지
```

---

## ⚡ 로컬 개발 빠른 시작

### 1. 백엔드 실행

```bash
cd backend
pip install -r requirements.txt

# .env 파일 설정
cp .env.example .env
# .env에 SUPABASE_URL, SUPABASE_KEY, ADMIN_PASSWORD, JWT_SECRET 입력

uvicorn main:app --reload
# → http://localhost:8000
# → API 문서: http://localhost:8000/docs
```

### 2. 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

> vite.config.js의 proxy 설정으로 `/api` 요청이 자동으로 `localhost:8000`으로 전달됩니다.

---

## 🚀 배포

### 프론트엔드 → Vercel

```bash
cd frontend
npm run build

# Vercel CLI
npx vercel --prod
```

Vercel 환경 변수 설정:
```
VITE_API_URL = https://your-backend.amazonaws.com/api
```

### 백엔드 → AWS

#### AWS App Runner (가장 간단)
1. ECR에 Docker 이미지 푸시:
```bash
cd backend
docker build -t survey-backend .
# ECR에 push 후 App Runner에서 이미지 선택
```

2. App Runner 환경 변수 설정:
```
SUPABASE_URL = ...
SUPABASE_KEY = ...
ADMIN_PASSWORD = ...
JWT_SECRET = ...
FRONTEND_URL = https://your-app.vercel.app
```

#### AWS EC2 (직접 실행)
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 🗄️ Supabase 데이터베이스

기존 `database_schema.sql`과 `sample_data.sql`을 그대로 사용합니다.
새로 설정하는 경우 Supabase SQL Editor에서 두 파일을 순서대로 실행하세요.

---

## 🔐 인증 방식

- 일반 사용자: 요양원ID + 조사원ID + 어르신ID → JWT 토큰 (8시간)
- 관리자: 비밀번호 → JWT 토큰 (관리자 권한 포함)
- 프론트엔드: localStorage에 토큰 저장, 모든 API 요청에 `Authorization: Bearer <token>` 자동 첨부

---

## 📡 API 엔드포인트

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | /api/auth/login | 일반 로그인 |
| POST | /api/auth/admin-login | 관리자 로그인 |
| GET | /api/surveys/progress | 설문 진행 현황 |
| GET/POST | /api/surveys/basic | 기초 조사표 |
| GET/POST | /api/surveys/nutrition | 영양 조사표 |
| GET/POST | /api/surveys/satisfaction | 만족도 조사표 |
| GET | /api/admin/nursing-homes | 요양원 목록 |
| GET | /api/admin/surveyors | 조사원 목록 |
| GET | /api/admin/elderly | 어르신 목록 |
| GET | /api/admin/progress | 전체 진행 현황 + 통계 |

전체 API 문서: `http://localhost:8000/docs` (Swagger UI 자동 생성)

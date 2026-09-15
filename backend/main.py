from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
from supabase import create_client, Client
from dotenv import load_dotenv
import jwt
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

load_dotenv()  # 라우터·모듈이 환경변수를 읽기 전에 .env 먼저 로드

from routers import auth, surveys, admin, care, public, news, ehr  # noqa: E402

app = FastAPI(title="요양원 설문조사 API", version="1.0.0")

# CORS 설정
_frontend_url = os.getenv("FRONTEND_URL", "")
allow_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://bluefood-survey.vercel.app",
    "https://bluefood-survey-ij8gkha85-hr18.vercel.app",
    "https://survey-backend-qwjk.onrender.com",
]
if _frontend_url and _frontend_url not in allow_origins:
    allow_origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["인증"])
app.include_router(surveys.router, prefix="/api/surveys", tags=["설문"])
app.include_router(admin.router, prefix="/api/admin", tags=["관리자"])
app.include_router(care.router, prefix="/api/care", tags=["돌봄 관리"])
app.include_router(public.router, prefix="/api/public", tags=["보호자 리포트"])
app.include_router(news.router, prefix="/api/news", tags=["뉴스 브리핑"])
app.include_router(ehr.router, prefix="/api/ehr", tags=["어르신 기록"])

@app.get("/")
def root():
    return {"status": "ok", "message": "요양원 설문조사 API 서버"}

@app.get("/health")
def health():
    return {"status": "healthy"}
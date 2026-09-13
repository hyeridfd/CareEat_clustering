from typing import Optional
from supabase import create_client, Client
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
SECRET_KEY = os.getenv("JWT_SECRET", "change-me-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8

_supabase: Client = None

def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수가 설정되지 않았습니다.")
        _supabase = create_client(url, key)
    return _supabase

def get_kst_now() -> str:
    return datetime.now(KST).isoformat()

def create_token(payload: dict) -> str:
    data = payload.copy()
    data["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    return decode_token(credentials.credentials)

def require_admin(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    user = decode_token(credentials.credentials)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user


# ─────────────────────────── 요양원 담당자 ───────────────────────────
import hashlib
import hmac
import secrets as _secrets

from fastapi import Query


def hash_password(pw: str, iterations: int = 200_000) -> str:
    salt = _secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), int(it)).hex()
        return hmac.compare_digest(calc, h)
    except Exception:
        return False


def require_staff(credentials: HTTPAuthorizationCredentials = Security(security),
                  nursing_home_id: Optional[str] = Query(None, description="관리자 전용: 조회할 요양원 ID")) -> dict:
    """담당자는 자기 요양원만, 관리자는 ?nursing_home_id= 로 특정 요양원 접근."""
    user = decode_token(credentials.credentials)
    if user.get("role") == "staff":
        return {**user, "scope_home": user["nursing_home_id"], "actor": f"staff:{user['staff_id']}"}
    if user.get("is_admin"):
        if not nursing_home_id:
            raise HTTPException(status_code=400, detail="관리자는 nursing_home_id 파라미터가 필요합니다.")
        return {**user, "scope_home": nursing_home_id, "actor": "admin"}
    raise HTTPException(status_code=403, detail="요양원 담당자 권한이 필요합니다.")

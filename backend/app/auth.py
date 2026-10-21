import hashlib
import hmac
import secrets
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .db import get_db, utcnow
from .models import AuthSession, Company, User


def hash_password(password: str):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, encoded: str):
    salt, expected = encoded.split("$")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def make_session(db, user):
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id,
                       expires_at=utcnow() + timedelta(hours=12)))
    db.commit()
    return token


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("alfa_session", "")
    session = db.get(AuthSession, token_hash(token))
    if not session or session.expires_at <= utcnow():
        raise HTTPException(401, "Войдите в сервис")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Пользователь не найден")
    return user


def admin(user: User = Depends(current_user)):
    if not user.is_admin:
        raise HTTPException(403, "Требуются права администратора")
    return user


def authorize_company(db, user, company_id):
    if company_id not in user.company_ids:
        raise HTTPException(403, "Компания недоступна")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Компания не найдена")
    return company

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User
from .schemas import EmailCodeRequest, LoginRequest, PasswordChangeRequest, PasswordResetRequest, RegisterRequest
from .security import (COOKIE_NAME, create_session, csrf_protected, current_user, decode_session,
                       hash_password, set_session_cookie, verify_password)
from .services.auth import (PURPOSE_REGISTER, PURPOSE_RESET, clear_login_failures, client_ip, consume_code,
                            ensure_account_unlocked, ensure_corporate_email, ensure_ip_allowed, ensure_password,
                            issue_code, normalize_email, record_login_failure, user_by_email, utcnow as auth_now)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_json(user: User) -> dict:
    return {
        "id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role,
        "position": user.position, "phone": user.phone, "department": user.department,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def set_new_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.password_changed_at = auth_now()
    user.session_version = (user.session_version or 0) + 1
    clear_login_failures(user)


@router.post("/register/request-code")
def request_registration_code(payload: EmailCodeRequest, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    ensure_corporate_email(email)
    if user_by_email(db, email):
        raise HTTPException(409, "Этот адрес уже зарегистрирован. Войдите или восстановите пароль")
    issue_code(db, email, PURPOSE_REGISTER, client_ip(request))
    return {"ok": True, "email": email, "ttl_minutes": settings.email_code_ttl_minutes,
            "resend_seconds": settings.email_code_resend_seconds}


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    ensure_corporate_email(email)
    ensure_password(payload.password, email)
    if user_by_email(db, email):
        raise HTTPException(409, "Этот адрес уже зарегистрирован. Войдите или восстановите пароль")
    consume_code(db, email, PURPOSE_REGISTER, payload.code)
    now = auth_now()
    user = User(email=email, full_name=payload.full_name, department=payload.department, phone=payload.phone,
                password_hash=hash_password(payload.password), email_verified_at=now, password_changed_at=now)
    db.add(user)
    db.commit()
    db.refresh(user)
    token, csrf = create_session(user)
    set_session_cookie(response, token)
    return {"user": user_json(user), "csrf_token": csrf}


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    ip = client_ip(request)
    ensure_ip_allowed(ip)
    user = user_by_email(db, email)
    ensure_account_unlocked(user, email)
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        record_login_failure(db, user, email, ip)
        raise HTTPException(401, "Неверный email или пароль")
    clear_login_failures(user)
    db.commit()
    token, csrf = create_session(user)
    set_session_cookie(response, token)
    return {"user": user_json(user), "csrf_token": csrf}


@router.post("/password/forgot")
def forgot_password(payload: EmailCodeRequest, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    user = user_by_email(db, email)
    if user and user.is_active:
        issue_code(db, email, PURPOSE_RESET, client_ip(request))
    return {"ok": True, "email": email, "ttl_minutes": settings.email_code_ttl_minutes,
            "resend_seconds": settings.email_code_resend_seconds}


@router.post("/password/reset")
def reset_password(payload: PasswordResetRequest, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    ensure_password(payload.password, email)
    user = user_by_email(db, email)
    consume_code(db, email, PURPOSE_RESET, payload.code)
    if not user or not user.is_active:
        raise HTTPException(400, "Код устарел или не запрашивался. Запросите новый код")
    set_new_password(user, payload.password)
    user.email_verified_at = user.email_verified_at or auth_now()
    db.commit()
    db.refresh(user)
    token, csrf = create_session(user)
    set_session_cookie(response, token)
    return {"user": user_json(user), "csrf_token": csrf}


@router.post("/password/change")
def change_password(payload: PasswordChangeRequest, response: Response, user: User = Depends(csrf_protected),
                    db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно")
    ensure_password(payload.password, user.email)
    if verify_password(payload.password, user.password_hash):
        raise HTTPException(400, "Новый пароль совпадает с текущим")
    set_new_password(user, payload.password)
    db.commit()
    db.refresh(user)
    token, csrf = create_session(user)
    set_session_cookie(response, token)
    return {"user": user_json(user), "csrf_token": csrf}


@router.post("/logout")
def logout(response: Response, _: User = Depends(csrf_protected)):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: User = Depends(current_user)):
    return {"user": user_json(user), "csrf_token": decode_session(request.cookies[COOKIE_NAME])["csrf"]}

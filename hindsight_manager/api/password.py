"""Password management API endpoints."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.auth.dependencies import get_current_user
from hindsight_manager.auth.password import (
    hash_password,
    verify_password,
    validate_password_strength,
    PasswordStrengthError,
    generate_secure_password,
)
from hindsight_manager.config import Settings
from hindsight_manager.db import get_session
from hindsight_manager.models.email_verification import EmailVerification
from hindsight_manager.models.login_history import LoginHistory
from hindsight_manager.models.user import User
from hindsight_manager.services.email import get_email_service

router = APIRouter(prefix="/password", tags=["password"])


# Request/Response models
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str = Field(min_length=8)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class SendVerificationRequest(BaseModel):
    email: EmailStr
    purpose: str = Field(pattern="^(register|reset_password|change_email)$")


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str
    purpose: str = Field(pattern="^(register|reset_password|change_email)$")


class MessageResponse(BaseModel):
    message: str


class GeneratePasswordResponse(BaseModel):
    password: str
    message: str


# Helper functions
async def _record_login(
    session: AsyncSession,
    user_id: uuid.UUID,
    success: bool,
    request: Request,
    failure_reason: str | None = None,
):
    """Record login attempt to history."""
    history = LoginHistory(
        user_id=user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=success,
        failure_reason=failure_reason,
    )
    session.add(history)


async def _create_verification_code(
    session: AsyncSession,
    email: str,
    purpose: str,
    expiry_minutes: int = 10,
) -> str:
    """Create and store verification code."""
    import random
    import string

    # Generate 6-digit code
    code = "".join(random.choices(string.digits, k=6))

    # Set expiry
    expires_at = datetime.now() + timedelta(minutes=expiry_minutes)

    # Delete any existing unverified codes for this email and purpose
    await session.execute(
        select(EmailVerification).where(
            and_(
                EmailVerification.email == email,
                EmailVerification.purpose == purpose,
                EmailVerification.verified == False,  # noqa: E712
            )
        )
    )
    # Delete existing codes
    await session.execute(
        EmailVerification.__table__.delete().where(
            and_(
                EmailVerification.email == email,
                EmailVerification.purpose == purpose,
                EmailVerification.verified == False,  # noqa: E712
            )
        )
    )

    # Create new verification record
    verification = EmailVerification(
        email=email, code=code, purpose=purpose, expires_at=expires_at
    )
    session.add(verification)
    await session.commit()

    return code


# Endpoints
@router.post("/change", response_model=MessageResponse)
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Change user password."""
    if not current_user.password_hash:
        raise HTTPException(status_code=400, detail="User uses social login, no password to change")

    # Verify old password
    if not verify_password(req.old_password, current_user.password_hash):
        await _record_login(
            session,
            current_user.id,
            False,
            request,
            failure_reason="Incorrect old password",
        )
        await session.commit()
        raise HTTPException(status_code=401, detail="Incorrect old password")

    # Validate new password strength
    try:
        validate_password_strength(req.new_password)
    except PasswordStrengthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Hash and update password
    current_user.password_hash = hash_password(req.new_password)
    current_user.updated_at = datetime.now()

    await session.commit()
    await _record_login(session, current_user.id, True, request)
    await session.commit()

    return MessageResponse(message="密码修改成功")


@router.post("/reset", response_model=MessageResponse)
async def reset_password(
    req: ResetPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Reset password with verification code."""
    # Find verification code
    result = await session.execute(
        select(EmailVerification).where(
            and_(
                EmailVerification.email == req.email,
                EmailVerification.code == req.code,
                EmailVerification.purpose == "reset_password",
                EmailVerification.verified == False,  # noqa: E712
                EmailVerification.expires_at > datetime.now(),
            )
        )
    )
    verification = result.scalar_one_or_none()

    if not verification:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    # Check attempts
    if verification.attempts >= 3:
        raise HTTPException(status_code=400, detail="验证码尝试次数过多，请重新获取")

    # Find user by email
    user_result = await session.execute(select(User).where(User.email == req.email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # Validate new password strength
    try:
        validate_password_strength(req.new_password)
    except PasswordStrengthError as e:
        verification.attempts += 1
        await session.commit()
        raise HTTPException(status_code=400, detail=str(e))

    # Update password
    user.password_hash = hash_password(req.new_password)
    user.updated_at = datetime.now()

    # Mark verification as used
    verification.verified = True
    verification.attempts += 1

    await session.commit()
    await _record_login(session, user.id, True, request)
    await session.commit()

    return MessageResponse(message="密码重置成功")


@router.post("/forgot", response_model=MessageResponse)
async def forgot_password(
    req: ForgotPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Request password reset code."""
    # Check if user exists
    result = await session.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # Generate verification code
    code = await _create_verification_code(session, req.email, "reset_password")

    # Send email
    settings = Settings()
    email_service = get_email_service(settings)
    if email_service:
        reset_link = f"{settings.base_url}/password/reset?email={req.email}&code={code}"
        await email_service.send_password_reset_email(req.email, reset_link)
    else:
        # For development, return code in response
        logger = __import__("logging").getLogger(__name__)
        logger.warning(f"Email service not configured. Verification code: {code}")
        return JSONResponse(
            status_code=200,
            content={
                "message": f"密码重置验证码已发送到您的邮箱（开发环境：{code}）",
                "code": code,
            },
        )

    return MessageResponse(message="密码重置验证码已发送到您的邮箱")


@router.post("/verify/send", response_model=MessageResponse)
async def send_verification_code(
    req: SendVerificationRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send verification code for email verification."""
    # Generate verification code
    code = await _create_verification_code(session, req.email, req.purpose)

    # Send email
    settings = Settings()
    email_service = get_email_service(settings)
    if email_service:
        await email_service.send_verification_email(req.email, code)
    else:
        # For development, return code in response
        logger = __import__("logging").getLogger(__name__)
        logger.warning(f"Email service not configured. Verification code: {code}")
        return JSONResponse(
            status_code=200,
            content={
                "message": f"验证码已发送到您的邮箱（开发环境：{code}）",
                "code": code,
            },
        )

    return MessageResponse(message="验证码已发送到您的邮箱")


@router.post("/verify", response_model=MessageResponse)
async def verify_email_code(
    req: VerifyEmailRequest,
    session: AsyncSession = Depends(get_session),
):
    """Verify email code."""
    # Find verification code
    result = await session.execute(
        select(EmailVerification).where(
            and_(
                EmailVerification.email == req.email,
                EmailVerification.code == req.code,
                EmailVerification.purpose == req.purpose,
                EmailVerification.verified == False,  # noqa: E712
                EmailVerification.expires_at > datetime.now(),
            )
        )
    )
    verification = result.scalar_one_or_none()

    if not verification:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    # Check attempts
    if verification.attempts >= 3:
        raise HTTPException(status_code=400, detail="验证码尝试次数过多，请重新获取")

    # Mark as verified
    verification.verified = True
    verification.attempts += 1
    await session.commit()

    return MessageResponse(message="验证成功")


@router.post("/generate", response_model=GeneratePasswordResponse)
async def generate_password():
    """Generate secure random password."""
    password = generate_secure_password()
    return GeneratePasswordResponse(
        password=password, message="已生成安全随机密码，请妥善保管"
    )

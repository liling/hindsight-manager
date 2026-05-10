"""Tests for password management API."""

import pytest

from hindsight_manager.api.password import router


@pytest.mark.asyncio
async def test_password_router_has_endpoints():
    """测试密码管理路由包含所有必要的端点."""
    routes = [route.path for route in router.routes]
    expected_routes = [
        "/password/change",
        "/password/reset",
        "/password/forgot",
        "/password/verify/send",
        "/password/verify",
        "/password/generate",
    ]

    for expected_route in expected_routes:
        assert expected_route in routes, f"Route {expected_route} not found in password router"


@pytest.mark.asyncio
async def test_change_password_request_validation():
    """测试修改密码请求验证."""
    from hindsight_manager.api.password import ChangePasswordRequest
    from pydantic import ValidationError

    # Test missing old password
    with pytest.raises(ValidationError):
        ChangePasswordRequest(new_password="NewPassword123!")

    # Test missing new password
    with pytest.raises(ValidationError):
        ChangePasswordRequest(old_password="oldpassword123")

    # Test valid request
    req = ChangePasswordRequest(
        old_password="oldpassword123", new_password="NewPassword123!"
    )
    assert req.old_password == "oldpassword123"
    assert req.new_password == "NewPassword123!"


@pytest.mark.asyncio
async def test_reset_password_request_validation():
    """测试重置密码请求验证."""
    from hindsight_manager.api.password import ResetPasswordRequest
    from pydantic import ValidationError

    # Test missing email
    with pytest.raises(ValidationError):
        ResetPasswordRequest(code="123456", new_password="NewPassword123!")

    # Test missing code
    with pytest.raises(ValidationError):
        ResetPasswordRequest(email="test@example.com", new_password="NewPassword123!")

    # Test missing new password
    with pytest.raises(ValidationError):
        ResetPasswordRequest(email="test@example.com", code="123456")

    # Test valid request
    req = ResetPasswordRequest(
        email="test@example.com", code="123456", new_password="NewPassword123!"
    )
    assert req.email == "test@example.com"
    assert req.code == "123456"
    assert req.new_password == "NewPassword123!"


@pytest.mark.asyncio
async def test_verification_purpose_validation():
    """测试验证码目的验证."""
    from hindsight_manager.api.password import SendVerificationRequest
    from pydantic import ValidationError

    # Test invalid purpose
    with pytest.raises(ValidationError):
        SendVerificationRequest(email="test@example.com", purpose="invalid")

    # Test valid purposes
    for purpose in ["register", "reset_password", "change_email"]:
        req = SendVerificationRequest(email="test@example.com", purpose=purpose)
        assert req.purpose == purpose

import pytest

from hindsight_manager.auth.password import (
    COMMON_PASSWORDS,
    MIN_LENGTH,
    generate_secure_password,
    hash_password,
    validate_password_strength,
    verify_password,
)
from hindsight_manager.auth.password import PasswordStrengthError


def test_validate_password_strength_success():
    """测试符合要求的密码"""
    password = "SecurePass123!"
    assert validate_password_strength(password) is True


def test_validate_password_strength_too_short():
    """测试密码太短"""
    with pytest.raises(PasswordStrengthError) as exc:
        validate_password_strength("Short1!")
    assert f"{MIN_LENGTH} 位" in str(exc.value)


def test_validate_password_strength_no_upper():
    """测试缺少大写字母"""
    with pytest.raises(PasswordStrengthError) as exc:
        validate_password_strength("lowercase123!")
    assert "大写字母" in str(exc.value)


def test_validate_password_strength_no_lower():
    """测试缺少小写字母"""
    with pytest.raises(PasswordStrengthError) as exc:
        validate_password_strength("UPPERCASE123!")
    assert "小写字母" in str(exc.value)


def test_validate_password_strength_no_digit():
    """测试缺少数字"""
    with pytest.raises(PasswordStrengthError) as exc:
        validate_password_strength("NoDigits!")
    assert "数字" in str(exc.value)


def test_validate_password_strength_no_special():
    """测试缺少特殊字符"""
    with pytest.raises(PasswordStrengthError) as exc:
        validate_password_strength("NoSpecialChars123")
    assert "特殊字符" in str(exc.value)


def test_validate_password_strength_common_password():
    """测试常见弱密码"""
    for pwd in COMMON_PASSWORDS:
        with pytest.raises(PasswordStrengthError) as exc:
            validate_password_strength(pwd)
        assert "过于常见" in str(exc.value)


def test_hash_and_verify_password():
    """测试密码哈希和验证"""
    plain = "MySecurePass123!"
    hashed = hash_password(plain)

    # 哈希值应该不同（由于 salt）
    hashed2 = hash_password(plain)
    assert hashed != hashed2

    # 但验证应该都成功
    assert verify_password(plain, hashed) is True
    assert verify_password(plain, hashed2) is True


def test_verify_password_wrong():
    """测试错误的密码"""
    plain = "MySecurePass123!"
    hashed = hash_password(plain)
    assert verify_password("WrongPassword123!", hashed) is False


def test_generate_secure_password():
    """测试生成随机密码"""
    password = generate_secure_password()
    assert len(password) == 16

    # 生成的密码应该符合强度要求
    assert validate_password_strength(password) is True


def test_generate_secure_password_custom_length():
    """测试自定义长度的随机密码"""
    password = generate_secure_password(24)
    assert len(password) == 24
    assert validate_password_strength(password) is True

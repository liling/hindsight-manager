import re
import secrets
import string
from typing import Literal

import passlib.hash


class PasswordError(Exception):
    """密码相关错误"""
    pass


class PasswordStrengthError(PasswordError):
    """密码强度不足"""
    pass


class PasswordValidationError(PasswordError):
    """密码验证失败"""
    pass


# 密码强度要求
MIN_LENGTH = 8
# 常见弱密码列表（示例）
COMMON_PASSWORDS = {
    "password", "12345678", "abcdefgh", "qwerty123",
    "abc12345", "password1", "123456789", "welcome1"
}


def validate_password_strength(password: str) -> Literal[True]:
    """
    验证密码强度。

    要求：
    - 至少 8 个字符
    - 包含大写字母
    - 包含小写字母
    - 包含数字
    - 包含特殊字符
    - 不在常见弱密码列表中

    Raises:
        PasswordStrengthError: 密码强度不足
    """
    if len(password) < MIN_LENGTH:
        raise PasswordStrengthError(f"密码长度至少需要 {MIN_LENGTH} 位")

    if password.lower() in COMMON_PASSWORDS:
        raise PasswordStrengthError("此密码过于常见，请使用更复杂的密码")

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in string.punctuation for c in password)

    missing = []
    if not has_upper:
        missing.append("大写字母")
    if not has_lower:
        missing.append("小写字母")
    if not has_digit:
        missing.append("数字")
    if not has_special:
        missing.append("特殊字符")

    if missing:
        raise PasswordStrengthError(f"密码必须包含：{'、'.join(missing)}")

    return True


def hash_password(password: str) -> str:
    """
    使用 bcrypt 哈希密码。

    Args:
        password: 明文密码

    Returns:
        哈希后的密码
    """
    return passlib.hash.bcrypt.using(rounds=12).hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码。

    Args:
        plain_password: 明文密码
        hashed_password: 哈希后的密码

    Returns:
        密码是否匹配
    """
    return passlib.hash.bcrypt.using(rounds=12).verify(plain_password, hashed_password)


def generate_secure_password(length: int = 16) -> str:
    """
    生成安全的随机密码。

    Args:
        length: 密码长度（默认 16）

    Returns:
        随机密码
    """
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(alphabet) for _ in range(length))

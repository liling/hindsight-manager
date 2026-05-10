import bcrypt


def hash_password(password: str) -> str:
    """
    使用 bcrypt 哈希密码。

    Args:
        password: 明文密码

    Returns:
        哈希后的密码
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password[:72].encode('utf-8'), salt).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    """
    验证密码。

    Args:
        plain: 明文密码
        hashed: 哈希后的密码

    Returns:
        密码是否匹配
    """
    return bcrypt.checkpw(plain[:72].encode('utf-8'), hashed.encode('utf-8'))

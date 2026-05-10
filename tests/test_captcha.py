"""测试滑动验证码服务"""
import time

import pytest

from hindsight_manager.auth.captcha import (
    CAPTCHA_EXPIRE_MINUTES,
    CAPTCHA_TOLERANCE,
    CaptchaVerifyRequest,
    _cleanup_expired_captchas,
    create_captcha,
    verify_captcha,
)


def test_create_captcha():
    """测试创建验证码"""
    captcha_data = create_captcha()

    # 验证返回的数据结构
    assert captcha_data.captcha_id is not None
    assert len(captcha_data.captcha_id) == 32  # 16字节的hex编码
    assert captcha_data.background_image is not None
    assert captcha_data.puzzle_image is not None
    assert captcha_data.target_x is not None
    assert 0 <= captcha_data.target_x <= 250  # 300 - 50 (puzzle size)
    assert captcha_data.expire_at > time.time()


def test_verify_captcha_success_within_tolerance():
    """测试验证成功 - 在容差范围内"""
    captcha_data = create_captcha()

    # 在容差范围内验证
    for offset in range(-CAPTCHA_TOLERANCE, CAPTCHA_TOLERANCE + 1):
        captcha_data = create_captcha()
        request = CaptchaVerifyRequest(
            captcha_id=captcha_data.captcha_id,
            x=captcha_data.target_x + offset
        )
        result = verify_captcha(request)
        assert result is True, f"Failed at offset {offset}"


def test_verify_captcha_failure_outside_tolerance():
    """测试验证失败 - 超出容差范围"""
    captcha_data = create_captcha()

    # 超出容差范围
    request = CaptchaVerifyRequest(
        captcha_id=captcha_data.captcha_id,
        x=captcha_data.target_x + CAPTCHA_TOLERANCE + 1
    )
    result = verify_captcha(request)
    assert result is False


def test_verify_captcha_invalid_id():
    """测试无效的验证码ID"""
    request = CaptchaVerifyRequest(
        captcha_id="invalid_id_12345",
        x=100
    )
    result = verify_captcha(request)
    assert result is False


def test_verify_captcha_one_time_use():
    """测试验证码的一次性使用"""
    captcha_data = create_captcha()

    # 第一次验证成功
    request1 = CaptchaVerifyRequest(
        captcha_id=captcha_data.captcha_id,
        x=captcha_data.target_x
    )
    result1 = verify_captcha(request1)
    assert result1 is True

    # 第二次验证失败（已被删除）
    request2 = CaptchaVerifyRequest(
        captcha_id=captcha_data.captcha_id,
        x=captcha_data.target_x
    )
    result2 = verify_captcha(request2)
    assert result2 is False


def test_verify_captcha_expired():
    """测试过期的验证码"""
    # 创建一个验证码并手动修改过期时间
    captcha_data = create_captcha()

    # 手动设置过期时间为过去
    import hindsight_manager.auth.captcha as captcha_module
    with captcha_module._captcha_lock:
        captcha_data.expire_at = time.time() - 10  # 10秒前过期
        captcha_module._captcha_store[captcha_data.captcha_id] = captcha_data

    # 验证应该失败
    request = CaptchaVerifyRequest(
        captcha_id=captcha_data.captcha_id,
        x=captcha_data.target_x
    )
    result = verify_captcha(request)
    assert result is False


def test_cleanup_expired_captchas():
    """测试清理过期验证码"""
    import hindsight_manager.auth.captcha as captcha_module

    # 创建几个验证码
    captcha1 = create_captcha()
    captcha2 = create_captcha()

    # 手动设置一个为过期
    with captcha_module._captcha_lock:
        captcha1.expire_at = time.time() - 10
        captcha_module._captcha_store[captcha1.captcha_id] = captcha1

    # 清理过期验证码
    cleaned_count = _cleanup_expired_captchas()

    assert cleaned_count == 1

    # 验证过期的已被删除
    request = CaptchaVerifyRequest(
        captcha_id=captcha1.captcha_id,
        x=captcha1.target_x
    )
    result = verify_captcha(request)
    assert result is False

    # 验证未过期的仍然存在
    request = CaptchaVerifyRequest(
        captcha_id=captcha2.captcha_id,
        x=captcha2.target_x
    )
    result = verify_captcha(request)
    assert result is True


def test_create_captcha_different_images():
    """测试每次创建的验证码都不同"""
    captcha1 = create_captcha()
    captcha2 = create_captcha()

    # 验证码ID应该不同
    assert captcha1.captcha_id != captcha2.captcha_id

    # 图片可能相同（由于随机性），但ID必须不同
    # 目标位置可能相同（由于随机性）
    assert captcha1.background_image is not None
    assert captcha2.background_image is not None


def test_verify_captcha_failure_deletes_captcha():
    """测试验证失败时也会删除验证码"""
    captcha_data = create_captcha()

    # 验证失败
    request = CaptchaVerifyRequest(
        captcha_id=captcha_data.captcha_id,
        x=captcha_data.target_x + 100  # 故意错误
    )
    result = verify_captcha(request)
    assert result is False

    # 再次验证应该失败（已被删除）
    request2 = CaptchaVerifyRequest(
        captcha_id=captcha_data.captcha_id,
        x=captcha_data.target_x
    )
    result2 = verify_captcha(request2)
    assert result2 is False

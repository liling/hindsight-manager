"""验证码API路由"""
from pydantic import BaseModel
from fastapi import APIRouter

from hindsight_manager.auth.captcha import CaptchaData, CaptchaVerifyRequest, create_captcha, verify_captcha

router = APIRouter(prefix="/captcha", tags=["captcha"])


class CaptchaCreateResponse(BaseModel):
    """验证码创建响应"""
    captcha_id: str
    background_image: str
    puzzle_image: str


class CaptchaVerifyResponse(BaseModel):
    """验证码验证响应"""
    success: bool


def _captcha_response(captcha_data: CaptchaData) -> CaptchaCreateResponse:
    """将验证码数据转换为API响应"""
    return CaptchaCreateResponse(
        captcha_id=captcha_data.captcha_id,
        background_image=captcha_data.background_image,
        puzzle_image=captcha_data.puzzle_image,
    )


@router.post("/create", response_model=CaptchaCreateResponse)
async def create_captcha_endpoint():
    """
    创建滑动验证码。

    Returns:
        验证码数据，包含背景图和拼图块的base64编码
    """
    captcha_data = create_captcha()
    return _captcha_response(captcha_data)


@router.post("/verify", response_model=CaptchaVerifyResponse)
async def verify_captcha_endpoint(request: CaptchaVerifyRequest):
    """
    验证滑动验证码。

    Args:
        request: 验证请求，包含验证码ID和用户拖动的X坐标

    Returns:
        验证结果
    """
    success = verify_captcha(request)
    return CaptchaVerifyResponse(success=success)


# 导出路由供主应用使用
__all__ = ["router"]

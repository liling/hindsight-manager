"""滑动验证码服务"""
import base64
import secrets
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Dict

from PIL import Image, ImageDraw, ImageFont


# 常量定义
CAPTCHA_EXPIRE_MINUTES = 5
CAPTCHA_TOLERANCE = 5  # 容差±5像素
IMAGE_WIDTH = 300
IMAGE_HEIGHT = 150
PUZZLE_SIZE = 50
PUZZLE_SHAPE_WIDTH = 10


@dataclass
class CaptchaData:
    """验证码数据"""
    captcha_id: str
    background_image: str  # base64编码
    puzzle_image: str  # base64编码
    target_x: int  # 目标X坐标
    expire_at: float


@dataclass
class CaptchaVerifyRequest:
    """验证码验证请求"""
    captcha_id: str
    x: int


# 内存存储
_captcha_store: Dict[str, CaptchaData] = {}
_captcha_lock = threading.Lock()


def _create_noise_image(width: int, height: int) -> Image.Image:
    """
    创建带噪声的背景图片。

    Args:
        width: 图片宽度
        height: 图片高度

    Returns:
        PIL Image对象
    """
    # 创建白色背景
    img = Image.new('RGB', (width, height), color='#f0f0f0')
    draw = ImageDraw.Draw(img)

    # 添加随机噪声点
    for _ in range(100):
        x = secrets.randbelow(width)
        y = secrets.randbelow(height)
        color = secrets.choice(('#cccccc', '#dddddd', '#bbbbbb'))
        draw.point((x, y), fill=color)

    # 添加随机线条
    for _ in range(5):
        x1 = secrets.randbelow(width)
        y1 = secrets.randbelow(height)
        x2 = secrets.randbelow(width)
        y2 = secrets.randbelow(height)
        color = secrets.choice(('#e0e0e0', '#d0d0d0', '#c0c0c0'))
        draw.line([(x1, y1), (x2, y2)], fill=color, width=1)

    return img


def _create_puzzle_piece() -> Image.Image:
    """
    创建拼图块图片（拼图形状）。

    Returns:
        PIL Image对象
    """
    img = Image.new('RGBA', (PUZZLE_SIZE, PUZZLE_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 绘制拼图形状（带凸起的拼图块）
    # 主体矩形
    draw.rectangle([0, 0, PUZZLE_SIZE - PUZZLE_SHAPE_WIDTH, PUZZLE_SIZE],
                   fill='#4a90e2', outline='#357abd')

    # 凸起部分
    bump_x = PUZZLE_SIZE - PUZZLE_SHAPE_WIDTH
    bump_y = PUZZLE_SIZE // 2
    bump_height = 10

    # 绘制凸起
    draw.ellipse([bump_x, bump_y - bump_height,
                  bump_x + PUZZLE_SHAPE_WIDTH, bump_y + bump_height],
                 fill='#4a90e2', outline='#357abd')

    return img


def create_captcha() -> CaptchaData:
    """
    创建滑动验证码。

    Returns:
        验证码数据
    """
    captcha_id = secrets.token_hex(16)
    expire_at = time.time() + (CAPTCHA_EXPIRE_MINUTES * 60)

    # 生成随机位置
    max_x = IMAGE_WIDTH - PUZZLE_SIZE
    target_x = secrets.randbelow(max_x)
    target_y = secrets.randbelow(IMAGE_HEIGHT - PUZZLE_SIZE)

    # 创建背景图片
    background = _create_noise_image(IMAGE_WIDTH, IMAGE_HEIGHT)

    # 创建拼图块
    puzzle_piece = _create_puzzle_piece()

    # 在背景上绘制拼图块的阴影（目标位置）
    shadow = puzzle_piece.copy()
    shadow_pixels = shadow.load()
    for i in range(shadow.width):
        for j in range(shadow.height):
            if shadow_pixels[i, j][3] > 0:  # 如果不是透明
                shadow_pixels[i, j] = (200, 200, 200, 128)  # 半透明灰色

    background.paste(shadow, (target_x, target_y), shadow)

    # 转换为base64
    background_buffer = BytesIO()
    background.save(background_buffer, format='PNG')
    background_base64 = base64.b64encode(background_buffer.getvalue()).decode('utf-8')

    puzzle_buffer = BytesIO()
    puzzle_piece.save(puzzle_buffer, format='PNG')
    puzzle_base64 = base64.b64encode(puzzle_buffer.getvalue()).decode('utf-8')

    captcha_data = CaptchaData(
        captcha_id=captcha_id,
        background_image=background_base64,
        puzzle_image=puzzle_base64,
        target_x=target_x,
        expire_at=expire_at
    )

    # 存储到内存
    with _captcha_lock:
        _captcha_store[captcha_id] = captcha_data

    return captcha_data


def verify_captcha(request: CaptchaVerifyRequest) -> bool:
    """
    验证滑动验证码。

    Args:
        request: 验证请求

    Returns:
        是否验证成功
    """
    with _captcha_lock:
        if request.captcha_id not in _captcha_store:
            return False

        captcha_data = _captcha_store[request.captcha_id]

        # 检查是否过期
        if time.time() > captcha_data.expire_at:
            del _captcha_store[request.captcha_id]
            return False

        # 验证X坐标是否在容差范围内
        target_x = captcha_data.target_x
        if abs(request.x - target_x) <= CAPTCHA_TOLERANCE:
            # 验证成功，删除验证码（一次性使用）
            del _captcha_store[request.captcha_id]
            return True
        else:
            # 验证失败，删除验证码
            del _captcha_store[request.captcha_id]
            return False


def _cleanup_expired_captchas() -> int:
    """
    清理过期的验证码。

    Returns:
        清理的数量
    """
    current_time = time.time()
    expired_ids = []

    with _captcha_lock:
        for captcha_id, captcha_data in _captcha_store.items():
            if current_time > captcha_data.expire_at:
                expired_ids.append(captcha_id)

        for captcha_id in expired_ids:
            del _captcha_store[captcha_id]

    return len(expired_ids)

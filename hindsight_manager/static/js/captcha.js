/**
 * 滑动验证码组件
 */
class CaptchaSlider {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            throw new Error(`Container with id "${containerId}" not found`);
        }

        this.options = {
            apiCreate: options.apiCreate || '/api/captcha/create',
            apiVerify: options.apiVerify || '/api/captcha/verify',
            onSuccess: options.onSuccess || null,
            onFailure: options.onFailure || null,
            ...options
        };

        this.captchaId = null;
        this.isDragging = false;
        this.startX = 0;
        this.currentX = 0;
        this.puzzleX = 0;

        this.init();
    }

    init() {
        this.render();
        this.loadCaptcha();
    }

    render() {
        this.container.innerHTML = `
            <div class="captcha-container">
                <div class="captcha-canvas" id="captcha-canvas">
                    <img class="captcha-background" id="captcha-background" alt="背景" />
                    <img class="captcha-puzzle" id="captcha-puzzle" alt="拼图块" />
                </div>
                <div class="captcha-slider-container">
                    <div class="captcha-slider-track">
                        <div class="captcha-slider-handle" id="captcha-handle"></div>
                    </div>
                </div>
                <div class="captcha-message" id="captcha-message"></div>
                <div class="captcha-refresh">
                    <button type="button" id="captcha-refresh-btn">刷新验证码</button>
                </div>
            </div>
        `;

        this.setupEventListeners();
    }

    setupEventListeners() {
        const handle = document.getElementById('captcha-handle');
        const refreshBtn = document.getElementById('captcha-refresh-btn');

        // 鼠标事件
        handle.addEventListener('mousedown', this.handleDragStart.bind(this));
        document.addEventListener('mousemove', this.handleDragMove.bind(this));
        document.addEventListener('mouseup', this.handleDragEnd.bind(this));

        // 触摸事件
        handle.addEventListener('touchstart', this.handleDragStart.bind(this));
        document.addEventListener('touchmove', this.handleDragMove.bind(this));
        document.addEventListener('touchend', this.handleDragEnd.bind(this));

        // 刷新按钮
        refreshBtn.addEventListener('click', () => this.loadCaptcha());
    }

    async loadCaptcha() {
        try {
            this.setMessage('加载中...', '');
            const response = await fetch(this.options.apiCreate, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error('加载验证码失败');
            }

            const data = await response.json();
            this.captchaId = data.captcha_id;
            this.renderImages(data.background_image, data.puzzle_image);
            this.resetSlider();
            this.setMessage('拖动滑块完成拼图', '');
        } catch (error) {
            console.error('加载验证码失败:', error);
            this.setMessage('加载验证码失败，请重试', 'error');
        }
    }

    renderImages(backgroundImage, puzzleImage) {
        const background = document.getElementById('captcha-background');
        const puzzle = document.getElementById('captcha-puzzle');

        background.src = `data:image/png;base64,${backgroundImage}`;
        puzzle.src = `data:image/png;base64,${puzzleImage}`;
    }

    resetSlider() {
        const handle = document.getElementById('captcha-handle');
        const puzzle = document.getElementById('captcha-puzzle');

        handle.style.left = '0px';
        puzzle.style.left = '0px';
        this.currentX = 0;
        this.puzzleX = 0;
    }

    handleDragStart(e) {
        e.preventDefault();
        this.isDragging = true;

        const clientX = e.type === 'touchstart' ? e.touches[0].clientX : e.clientX;
        this.startX = clientX - this.currentX;
    }

    handleDragMove(e) {
        if (!this.isDragging) return;

        const clientX = e.type === 'touchmove' ? e.touches[0].clientX : e.clientX;
        this.currentX = clientX - this.startX;

        // 限制范围
        const maxDistance = 260; // 300 - 40 (handle width)
        this.currentX = Math.max(0, Math.min(this.currentX, maxDistance));

        this.updateSliderPosition();
    }

    handleDragEnd(e) {
        if (!this.isDragging) return;
        this.isDragging = false;

        this.verifyCaptcha();
    }

    updateSliderPosition() {
        const handle = document.getElementById('captcha-handle');
        const puzzle = document.getElementById('captcha-puzzle');

        handle.style.left = `${this.currentX}px`;
        puzzle.style.left = `${this.currentX}px`;
    }

    async verifyCaptcha() {
        if (!this.captchaId) {
            this.setMessage('验证码已过期，请刷新', 'error');
            return;
        }

        try {
            const response = await fetch(this.options.apiVerify, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    captcha_id: this.captchaId,
                    x: Math.round(this.currentX)
                })
            });

            if (!response.ok) {
                throw new Error('验证失败');
            }

            const result = await response.json();

            if (result.success) {
                this.setMessage('验证成功！', 'success');
                if (this.options.onSuccess) {
                    this.options.onSuccess();
                }
            } else {
                this.setMessage('验证失败，请重试', 'error');
                if (this.options.onFailure) {
                    this.options.onFailure();
                }
                // 延迟重新加载
                setTimeout(() => this.loadCaptcha(), 1500);
            }
        } catch (error) {
            console.error('验证失败:', error);
            this.setMessage('验证失败，请重试', 'error');
            if (this.options.onFailure) {
                this.options.onFailure();
            }
            // 延迟重新加载
            setTimeout(() => this.loadCaptcha(), 1500);
        }
    }

    setMessage(text, type) {
        const messageEl = document.getElementById('captcha-message');
        if (!messageEl) return;

        messageEl.textContent = text;
        messageEl.className = 'captcha-message';
        if (type) {
            messageEl.classList.add(`captcha-${type}`);
        }
    }

    reset() {
        this.loadCaptcha();
    }
}

// 导出供外部使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CaptchaSlider;
}

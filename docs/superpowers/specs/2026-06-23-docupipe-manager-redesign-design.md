# docupipe-manager 设计文档（基于 xinyi-platform 重构版）

**日期**: 2026-06-23
**状态**: 设计已确认,待用户审阅
**项目位置**: `~/src/lab/docupipe-manager/`（新建）
**前置**: xinyi-platform 已落地,hindsight-manager 已改造为 OAuth2 client（参见 `2026-06-22-platform-extraction-design.md`）

## 关系与变更说明

本 spec 基于 `2026-06-21-docupipe-manager-design.md` 重写。原 spec 假设"通过 `import hindsight_manager` 复用 auth/db/crypto",平台抽取后此路线废弃——改用 OAuth2 client 接入 xinyi-platform,UI 共享 `xinyi_platform.ui_common`,与 hindsight-manager 完全解耦。

数据模型(§2)、服务层(§4)、API 路由骨架(§5)、测试策略骨架(§6)、业务 UI 设计(§7 业务页面部分)沿用 6-21 设计,语义不变。重写部分:§1(项目骨架/依赖)、§3(Settings)、§5 认证端点、§7 导航集成、§8(部署生命周期)、§9(实现顺序)。

## 目标

为 hindsight-manager 生态增加文档管道管理能力:建立一个 project,在其中配置 docupipe 任务(整段 YAML)、绑定 dws 钉钉认证,支持手工触发或 cron 定时执行。

## 非目标(v1)

- 不做 docupipe 进程内调用(保持 subprocess 模型)
- 不做多 worker / 跨进程任务队列(单 web 进程内并发)
- 不做运行重试链(failed 由 admin 决定是否重跑)
- 不做 YAML 表单化编辑(保留文本编辑)
- 不做 venv 隔离 / 容器级隔离
- 不做 MinerU OCR 依赖(只装基础 docupipe)
- 不做二维码图片生成(用文本 URL)
- 不强制测试覆盖率阈值
- 不做 per-document 进度上报(docupipe 的 `.state/` 已经管这个)
- 不 import hindsight-manager 任何代码
- 不独立实现认证登录/用户管理(走 xinyi-platform 平台)

## 关键决策

| # | 决策 | 选定 |
|---|---|---|
| 1 | 接入方式 | 在 xinyi-platform 注册为 OAuth2 business_client `docupipe-prod`;UI 共享 `xinyi_platform.ui_common`;**完全不 import hindsight_manager** |
| 2 | 整体形态 | 独立项目 `~/src/lab/docupipe-manager/`,与 hindsight-manager / xinyi-platform 并列 |
| 3 | DB schema | 独占 schema `docupipe_manager`,共享 Postgres 实例 |
| 4 | 共享密钥 | `jwt_secret` / `encryption_key`(SM4)跟 xinyi-platform 同值;env 名各自独立 |
| 5 | dws 认证机制 | 浏览器扫码 → 后台 `dws auth login --device` → `dws auth export --base64` → SM4 加密入库 |
| 6a | 凭证数量 | 多份(`dws_credentials` 表,project 关联到具体凭证) |
| 6b | 失效感知 | 失败日志自然暴露,不做主动提醒 |
| 7a | 配置编辑形态 | 整段 YAML 文本编辑 |
| 7b | project↔pipeline | 一 project 多 pipeline,运行时 `--pipeline NAME` 指定(不指定则全跑) |
| 8a | 调度表达式 | 裸 cron 字符串(标准 5 段) |
| 8b | 调度器 | 进程内 APScheduler + MemoryJobStore |
| 9a | 日志 | 文件存全文 + DB 存摘要 + 路径 |
| 9b | 进程隔离 | 独立子进程 + 临时 HOME |
| 9c | 失败感知 | UI banner(仅 `/docupipe/*` 路径下显示) |
| 10 | UI 顶部导航 | 直接编辑 `xinyi_platform/ui_common/registry.py` 的 `PRODUCTS` 列表,新增 `docupipe_url` placeholder |
| 11 | 跨服务审计推送 | `asyncio.create_task` 走 `XinyiPlatformClient.push_audit`,fire-and-forget,平台抖动不阻塞业务请求 |
| 12 | 用户信息查询 | 进程内 LRU 缓存(5min TTL)+ 平台 `POST /internal/users/batch-get` 兜底 |
| 13 | 部署 | 独立 docker-compose,加入 hindsight-manager 的 `hindsight_default` 网络 |
| 14 | 端口 | 8002 |
| 15 | schema 名 | `docupipe_manager` |
| 16 | SM4 实现 | 从 xinyi-platform 复制一份(沿用 platform-extraction 决策 14) |
| 17 | YAML 编辑器 | textarea,不引外部库 |

## §1 项目骨架与依赖

### 目录布局

```
~/src/lab/docupipe-manager/
├── pyproject.toml
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── docupipe_manager/
│   ├── __init__.py
│   ├── main.py                       # FastAPI app + lifespan(起 APScheduler + 孤儿清理)
│   ├── config.py                     # Settings, env prefix: DOCUPIPE_MANAGER_
│   ├── db.py                         # create_async_engine + session_factory(独立,schema=docupipe_manager)
│   ├── crypto.py                     # SM4 加解密 — 从 xinyi-platform 复制(沿用 platform-extraction 决策 14)
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── session.py                # JWT 编解码 access token(HS256,与 hindsight-manager 同款)
│   │   ├── oauth_state.py            # OAuth2 state(CSRF)生成/校验
│   │   └── dependencies.py           # get_current_user / require_admin,cookie=docupipe_session
│   ├── platform/                     # xinyi-platform client 适配层(与 hm 镜像)
│   │   ├── __init__.py
│   │   ├── client.py                 # XinyiPlatformClient(httpx):refresh_token / revoke / batch_get_users / push_audit
│   │   ├── cache.py                  # UserLRUCache(进程内, 5min TTL)
│   │   └── config.py                 # PlatformSettings(platform_url / oauth_client_id / oauth_client_secret)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py                   # /auth/login-redirect /auth/callback /auth/refresh /auth/logout
│   │   ├── pages.py                  # UI 页面
│   │   ├── projects.py
│   │   ├── credentials.py
│   │   └── runs.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                   # Base(metadata=MetaData(schema="docupipe_manager"))
│   │   ├── dws_credential.py
│   │   ├── docupipe_project.py
│   │   └── pipeline_run.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── runner_service.py
│   │   ├── scheduler_service.py
│   │   └── credential_service.py
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/
│   └── templates/
│       └── docupipe/                 # 全部业务模板
│           ├── projects.html
│           ├── project_form.html
│           ├── credentials.html
│           ├── credential_login.html
│           └── runs.html
└── tests/
    ├── unit/
    ├── services/
    ├── api/
    └── conftest.py
```

注:`templates/` 下不再有 `docupipe_admin_base.html` extends hindsight-manager 的 `base.html`;改用 `xinyi_platform.ui_common.install_ui()` 提供的共享骨架 + globals,自己写 `templates/base.html` 引用 globals。

### pyproject.toml 关键依赖

```toml
[project]
name = "docupipe-manager"
dependencies = [
    "fastapi",
    "uvicorn",
    "sqlalchemy[asyncio]",
    "alembic",
    "apscheduler",
    "croniter",
    "docupipe",                  # 包工具本体
    "xinyi-platform",          # 仅用 ui_common(path install)
    "pyyaml",
    "jinja2",
    "pydantic-settings",
    "python-jose[cryptography]",
    "httpx",
    "bcrypt",
    "psycopg[binary]",          # 跟 xinyi-platform 一致
]

[tool.uv.sources]
xinyi-platform = { path = "../xinyi-platform" }
```

`docupipe` 走 PyPI 或 path install(部署侧选择)。`xinyi-platform` 只 import 其 `ui_common` 子包。

### 复用与不复用

**复用(import)**:

- `xinyi_platform.ui_common.install_ui` / `ui_jinja_globals`(顶部导航 + 共享样式)
- `xinyi_platform.crypto` SM4 实现 —— 复制一份到 docupipe-manager(不 import 跨进程),沿用平台抽取决策 14 的"复制不发布共享包"

**不复用**:

- `hindsight_manager.*` —— 完全不 import,与 hm 解耦
- `docupipe`(pipeline 工具)—— subprocess 调用,不进程内调用

### DB / schema 规划

共用同一 Postgres 实例,独占 schema `docupipe_manager`(可通过 `DOCUPIPE_MANAGER_MANAGER_SCHEMA` 配置)。

Alembic 配置:

- `script_location = docupipe_manager/migrations`
- `version_table_schema = docupipe_manager`(迁移历史隔离,不污染别的版本表)

不建跨 schema FK constraint(`created_by` 等只做逻辑引用),与 hindsight-manager / xinyi-platform 现有约定一致。

### 与 xinyi-platform 的集成点

1. **业务 client 注册**:在 `xinyi.business_clients` 表登记 `docupipe-prod`(SQL 脚本或平台 `/admin/clients` UI 注册);`redirect_uri` 与 docupipe-manager 的 `OAUTH_REDIRECT_URI` 必须一致。
2. **UI registry**:直接编辑 `xinyi_platform/ui_common/registry.py` 的 `PRODUCTS`,新增:
   ```python
   {
       "id": "docupipe-manager",
       "label": "DocuPipe",
       "subtitle": "文档管道调度",
       "kind": "business",
       "url_template": "{docupipe_url}",
   }
   ```
   - `url_template` 新增 `{docupipe_url}` placeholder
   - `install_ui._resolve_products` 需扩参数 `docupipe_url`,平平接受 `None`(已部署的 hindsight-manager 不传 → 显示为空字符串,无害)

### 共享 vs 独立 清单

| 资源 | 共享/独立 | 说明 |
|---|---|---|
| Postgres 实例 | 共享 | schema 隔离 |
| `jwt_secret` | 共享 | access token 本地验签,与 platform / hm 一致 |
| `encryption_key` (SM4) | 共享 | 加密 `auth_blob` / `oauth_client_secret` |
| Cookie | 独立 | `docupipe_session`(业务接入 cookie) |
| `xinyi_platform.ui_common` | import 复用 | 只用 install_ui / Jinja globals |
| `hindsight_manager.*` | 完全不 import | 与 hm 解耦 |
| `docupipe`(pipeline 工具) | subprocess 调用 | 不进程内调用 |
| `crypto.py` SM4 实现 | 复制 | 与 xinyi-platform 各一份 |
| `db.py` / `config.py` | 各自独立一份 | |

## §2 数据模型

三张表 + 四个 ENUM,全部在 schema `docupipe_manager`。

### ENUM 定义

```sql
CREATE TYPE docupipe_manager.credential_status AS ENUM ('active', 'expired', 'revoked');
CREATE TYPE docupipe_manager.project_status   AS ENUM ('active', 'paused', 'archived');
CREATE TYPE docupipe_manager.run_trigger_type AS ENUM ('manual', 'scheduled');
CREATE TYPE docupipe_manager.run_status      AS ENUM ('pending', 'running', 'succeeded', 'failed', 'cancelled');
```

### 表 1: `dws_credentials`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) UNIQUE | 用户可读名 |
| `corp_id` | VARCHAR(64) | 从 `dws auth status` 读到,登录后回填 |
| `auth_blob` | BYTEA | SM4 加密的 `dws auth export --base64` 产物 |
| `token_expires_at` | TIMESTAMPTZ | access token 过期(通常 2 小时),过期不影响可用性(dws CLI 自动续) |
| `refresh_token_expires_at` | TIMESTAMPTZ | 真正失效点(通常 30 天) |
| `last_refreshed_at` | TIMESTAMPTZ | 最后一次 dws 状态查询成功时间 |
| `status` | ENUM `credential_status` | `active` / `expired` / `revoked` |
| `created_by` | UUID | 逻辑引用 `xinyi.users.id` |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

索引:`name` 唯一;`(status, refresh_token_expires_at)` 用于过期扫描。

### 表 2: `docupipe_projects`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) UNIQUE | 用户可读名 |
| `slug` | VARCHAR(64) UNIQUE | 文件系统安全名,`[a-z0-9-]` |
| `description` | TEXT | 自由说明 |
| `config_yaml` | TEXT | 整段 docupipe.yaml 内容 |
| `dws_credential_id` | UUID NOT NULL | 逻辑引用 `dws_credentials.id` |
| `schedule_cron` | VARCHAR(64) NULL | 标准 5 段 cron;NULL 表示只手工触发 |
| `schedule_enabled` | BOOLEAN DEFAULT TRUE | cron 存在但可暂停 |
| `schedule_pipeline` | VARCHAR(255) NULL | 调度时调用的 pipeline 名;NULL 表示全跑 |
| `schedule_mode` | VARCHAR(16) DEFAULT 'incremental' | 透传 `--mode` 给 docupipe |
| `status` | ENUM `project_status` | `active` / `paused` / `archived` |
| `created_by` | UUID | 逻辑引用 `xinyi.users.id` |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

索引:`name` / `slug` 唯一;`(status, dws_credential_id)`。

### 表 3: `pipeline_runs`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID NOT NULL | 逻辑引用 `docupipe_projects.id` |
| `trigger_type` | ENUM `run_trigger_type` | `manual` / `scheduled` |
| `triggered_by` | UUID NULL | 手工触发有值,调度触发为 NULL |
| `pipeline_name` | VARCHAR(255) NULL | 本次跑的 `--pipeline NAME`;NULL 表示全跑 |
| `mode` | VARCHAR(16) | 透传给 docupipe |
| `status` | ENUM `run_status` | `pending` / `running` / `succeeded` / `failed` / `cancelled` |
| `pid` | INTEGER NULL | 运行中 subprocess 的 PID |
| `exit_code` | INTEGER NULL | subprocess exit code |
| `started_at` / `completed_at` | TIMESTAMPTZ NULL | |
| `log_path` | VARCHAR(512) NULL | `data_dir/projects/<slug>/runs/<run_id>.log` |
| `error_message` | TEXT NULL | 失败时 stderr 末尾 2KB |
| `created_at` | TIMESTAMPTZ | |

索引:`(project_id, created_at DESC)` 复合;`status` 单列。

不存 per-document 进度(由 docupipe 的 `.state/` 管)。

### 初始迁移

v1 初始迁移创建:schema + 4 个 ENUM + 3 张表。启动时自动 `alembic upgrade head`(FastAPI lifespan 调)。

## §3 配置（Settings）

相比 6-21 spec,删除 `jwt_secret` 跟 hindsight-manager "对齐共享"的措辞、删除 SSO token 字段;新增 OAuth2 client 配置 + `platform_url`。

```python
class Settings(BaseSettings):
    # —— 数据库 ——
    database_url: str
    manager_schema: str = "docupipe_manager"

    # —— 运行 ——
    data_dir: str = "/var/lib/docupipe-manager"
    dws_cli_path: str = "dws"
    docupipe_python: str = "python"
    docupipe_working_dir: str = ""
    run_timeout_seconds: int = 0                  # 0 = 不限时
    max_concurrent_runs: int = 3
    run_log_max_bytes: int = 10 * 1024 * 1024

    # —— 共享密钥(跟 xinyi-platform 同值)——
    jwt_secret: str                               # 验签 access JWT(本地)
    encryption_key: str = ""                      # SM4 加密 dws auth_blob

    # —— OAuth2 client 接入 xinyi-platform ——
    platform_url: str = "http://xinyi-platform:8000"
    oauth_client_id: str = "docupipe-prod"
    oauth_client_secret: str = ""                 # 明文存 env(平台侧 bcrypt 存 hash);运行时直接做 X-Client-Secret header
    oauth_redirect_uri: str = "http://localhost:8002/auth/callback"

    refresh_token_ttl_days: int = 7               # refresh cookie max_age(跟平台同款)
    access_token_ttl_seconds: int = 900           # 本地过期判断用,业务不签发只验签
    platform_request_timeout_seconds: int = 10
    user_cache_ttl_seconds: int = 300             # LRU 缓存 TTL

    # —— HTTP 服务 ——
    host: str = "0.0.0.0"
    port: int = 8002
    base_url: str = "http://localhost:8002"

    model_config = {"env_prefix": "DOCUPIPE_MANAGER_", "env_file": ".env"}
```

### data_dir 布局

```
/var/lib/docupipe-manager/
└── projects/
    └── <slug>/
        ├── config.yaml                 # 每次 run 前从 DB 重写
        ├── .state/                     # docupipe 状态目录
        ├── output/                     # YAML 里相对 output_dir 落在这下面
        └── runs/
            └── <run_id>.log            # 单次 run 的 stdout+stderr 全量
```

subprocess 启动时 `cwd = data_dir/projects/<slug>/`、`--config config.yaml`、`--state-dir .state` 由 RunnerService 代填。用户 YAML 不要再写这些路径。UI 保存配置前对绝对路径 `output_dir` 做 lint 提示("建议相对路径"),非强制。

### 运行限制

- `max_concurrent_runs`:RunnerService 持 `asyncio.Semaphore(max_concurrent_runs)`,超出的 run 保持 pending。
- `run_timeout_seconds`:>0 时,subprocess 用 `asyncio.wait_for` 包,超时发 SIGTERM、宽限 10s 后 SIGKILL,run 标 failed 且 `error_message="timeout"`。

### 配置同步约束

docupipe-manager 必须跟 xinyi-platform 共享这些 env 的**值**(env 名不同):

- `XINYI_PLATFORM_JWT_SECRET` ≡ `DOCUPIPE_MANAGER_JWT_SECRET`
- `XINYI_PLATFORM_ENCRYPTION_KEY` ≡ `DOCUPIPE_MANAGER_ENCRYPTION_KEY`

不复用 hindsight-manager 的任何 env(除非三者本就一值)。

### `.env.example`

```bash
DOCUPIPE_MANAGER_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/hindsight
DOCUPIPE_MANAGER_MANAGER_SCHEMA=docupipe_manager

# 跟 xinyi-platform 共享
DOCUPIPE_MANAGER_JWT_SECRET=<same as xinyi-platform>
DOCUPIPE_MANAGER_ENCRYPTION_KEY=<same as xinyi-platform>

# 运行
DOCUPIPE_MANAGER_DATA_DIR=/var/lib/docupipe-manager
DOCUPIPE_MANAGER_DWS_CLI_PATH=/usr/local/bin/dws
DOCUPIPE_MANAGER_DOCUPIPE_PYTHON=python
DOCUPIPE_MANAGER_RUN_TIMEOUT_SECONDS=0
DOCUPIPE_MANAGER_MAX_CONCURRENT_RUNS=3

# OAuth2 client(在平台 business_clients 注册时的同一份 secret)
DOCUPIPE_MANAGER_PLATFORM_URL=http://xinyi-platform:8000
DOCUPIPE_MANAGER_OAUTH_CLIENT_ID=docupipe-prod
DOCUPIPE_MANAGER_OAUTH_CLIENT_SECRET=<明文 secret>
DOCUPIPE_MANAGER_OAUTH_REDIRECT_URI=http://localhost:8002/auth/callback

# 服务
DOCUPIPE_MANAGER_HOST=0.0.0.0
DOCUPIPE_MANAGER_PORT=8002
DOCUPIPE_MANAGER_BASE_URL=http://localhost:8002
```

## §4 服务层

### §4.1 RunnerService —— 跑管道的核心

```python
class RunnerService:
    def __init__(self, engine, settings: Settings, platform_client: XinyiPlatformClient):
        self._engine = engine
        self._settings = settings
        self._platform_client = platform_client
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_runs)

    async def start_run(
        self,
        project_id: UUID,
        trigger_type: TriggerType,
        triggered_by: UUID | None,
        pipeline_name: str | None = None,
        mode: str = "incremental",
    ) -> PipelineRun:
        """创建 run 记录(status=pending),后台执行,立即返回。"""
```

`start_run` 立即 INSERT run 记录后 `asyncio.create_task(_execute_run(run_id))`,返回 run 实体。

`_execute_run` 完整生命周期:

1. `async with semaphore:` —— 等并发槽
2. UPDATE run SET status=running, started_at=now, pid=...
3. 准备目录:
   - `home_dir = mkdtemp(prefix="dws-home-")` —— 临时 HOME,放 dws 凭证
   - `project_dir = data_dir/projects/<slug>/`
   - `config_path = project_dir/config.yaml`
4. 写 config.yaml(从 DB `config_yaml` 字段)
5. 解 SM4 取 `auth_blob` → 写 `<home_dir>/auth.b64`(绝对路径,避免 cwd 漂移)
6. `dws auth import -i <home_dir>/auth.b64 --base64`(env: `HOME=<home_dir>`)
7. `python -m docupipe run --config config_path [--pipeline NAME] --mode <mode> --state-dir <project_dir>/.state --log-level INFO`(env: `HOME=home_dir`, `cwd=project_dir`)
8. stdout/stderr 边读边写到 `log_path`;超出 `run_log_max_bytes` 时保留首尾、截断中段
9. 等 exit code(或 `asyncio.wait_for` 超时)
10. UPDATE run SET status=succeeded/failed, exit_code, completed_at, error_message
11. **finally: `shutil.rmtree(home_dir)`**(任何路径都要清,避免泄漏 auth.b64)

工程细节:

- subprocess 用 `asyncio.create_subprocess_exec`,不阻塞事件循环
- `error_message`:失败时取 stderr 末尾 2KB
- `pid` 字段:启动后立即写入,UI 可发 SIGTERM
- 取消:running → SIGTERM;pending → 直接改 status 跳过执行
- `_execute_run` 是 fire-and-forget task,所有异常捕获后写 error_message,status 标 failed
- **审计推送**:run 完成(成功/失败)后用 `self._platform_client.push_audit` 推 `docupipe.run.{success|fail}` 事件(fire-and-forget,非阻塞)

### §4.2 SchedulerService —— APScheduler 编排

```python
class SchedulerService:
    def __init__(self, runner: RunnerService, engine, settings):
        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._runner = runner

    async def start(self):
        """FastAPI lifespan 启动时:扫描 active+schedule_enabled 的 project,注册 cron job。"""
        await self._reload_all()
        self._scheduler.start()

    async def stop(self):
        self._scheduler.shutdown(wait=False)

    async def schedule_project(self, project_id: UUID): ...
    async def unschedule_project(self, project_id: UUID): ...
```

Job 函数(注册到 APScheduler):

```python
async def _scheduled_run(project_id: UUID):
    async with session_factory() as session:
        project = await session.get(DocupipeProject, project_id)
        if project.status != "active" or not project.schedule_enabled:
            return  # 防止已暂停的 project 仍触发
        await runner.start_run(
            project_id=project_id,
            trigger_type="scheduled",
            triggered_by=None,
            pipeline_name=project.schedule_pipeline,
            mode=project.schedule_mode,
        )
```

JobStore:MemoryJobStore(默认)。进程重启时所有 cron job 丢失,但 `start()` 时从 DB 重建。重启代价仅"到下一个 cron 触发点的等待"重置,可接受。不选 SQLAlchemyJobStore,因为它会自建表、生命周期跟 `pipeline_runs` 解耦,反而更复杂。

触发器:`CronTrigger.from_crontab(schedule_cron)` 直接解析 5 段标准 cron。v1 不支持秒级。

### §4.3 CredentialService —— dws 设备流 + 凭证管理

```python
class CredentialService:
    async def start_device_login(self, name: str) -> dict:
        """启动 dws auth login --device,返回 verification_url + user_code + session_key。"""
    async def poll_device_login(self, session_key: str) -> dict:
        """前端轮询:{"status": "pending" | "success" | "failed"}。"""
    async def finalize_login(self, session_key: str, name: str, user_id: UUID) -> DwsCredential:
        """登录成功后:查 dws auth status + dws auth export --base64 + SM4 加密入库。"""
    async def check_status(self, credential_id: UUID) -> dict: ...
    async def revoke(self, credential_id: UUID): ...
```

设备流实现细节:

```python
async def start_device_login(self, name: str) -> dict:
    session_key = uuid4().hex
    home_dir = mkdtemp(prefix="dws-device-")

    proc = await asyncio.create_subprocess_exec(
        settings.dws_cli_path, "auth", "login", "--device",
        "--format", "json",
        stdout=PIPE, stderr=PIPE,
        env={**os.environ, "HOME": home_dir},
        cwd=home_dir,
    )

    first_chunk = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
    info = json.loads(first_chunk)

    self._active_sessions[session_key] = {
        "proc": proc,
        "home_dir": home_dir,
        "name": name,
    }
    return {"session_key": session_key, **info}
```

设备流状态暂存:`{session_key: subprocess_handle + home_dir + name}` 进程内字典。v1 单实例假设。多实例部署是 v2 的事,届时换 Redis 或 Postgres 表,service 接口已预留(`session_key` 是 opaque string)。

`finalize_login` 后流程:

1. `dws auth status` 读 corp_id / expires_at / refresh_expires_at
2. `dws auth export --base64 -o <tmpfile>` 拿认证包字节
3. SM4 加密入库 `auth_blob`,status=active
4. 清理临时 HOME(`shutil.rmtree`)
5. **审计推送**:`platform_client.push_audit` 推 `docupipe.credential.create`

`revoke` 成功后推 `docupipe.credential.revoke`。

## §5 API 层

### 鉴权

- API 写端点(`/admin/api/docupipe/*`)走 `Depends(require_admin)` —— docupipe-manager 自有 `auth/dependencies.py`,cookie 名 = `docupipe_session`,本地验签 access JWT 与改造后的 hindsight-manager **同款实现**(参见 `hindsight_manager/auth/dependencies.py`),仅改 `SELF_AUDIENCE = "docupipe-prod"`、cookie 名。
- UI 页面用 `Depends(get_current_user)` + 模板层校验 `user["role"] == "admin"`。

### 路由清单

| Method | Path | 功能 |
|---|---|---|
| **Auth(接入 xinyi-platform OAuth2)** ||
| GET | `/auth/login-redirect` | 未认证请求 302 → 平台 `/oauth/authorize`,带 state / return_to |
| GET | `/auth/callback` | 收 `?code=` + state,校验 state,POST 平台 `/oauth/token` 兑换,设 `docupipe_session` cookie(access) + `docupipe_refresh` cookie(refresh, HttpOnly),跳 return_to |
| POST | `/auth/refresh` | 调平台 `/oauth/token` (grant_type=refresh_token),刷新后更新 cookie |
| POST | `/auth/logout` | 清 cookie + 调平台 `/oauth/revoke` |
| **Credentials** ||
| GET | `/admin/api/docupipe/credentials` | 列出所有凭证 |
| POST | `/admin/api/docupipe/credentials/device-login/start` | 启动设备流 |
| GET | `/admin/api/docupipe/credentials/device-login/poll?session_key=...` | 前端轮询 |
| POST | `/admin/api/docupipe/credentials/device-login/finalize` | 入库(SM4 加密) |
| GET | `/admin/api/docupipe/credentials/{id}/status` | 调 dws auth status 刷新 |
| POST | `/admin/api/docupipe/credentials/{id}/revoke` | 标记 revoked(不删 row) |
| **Projects** ||
| GET | `/admin/api/docupipe/projects` | 列表 |
| POST | `/admin/api/docupipe/projects` | 创建 |
| GET | `/admin/api/docupipe/projects/{id}` | 详情 |
| PUT | `/admin/api/docupipe/projects/{id}` | 更新(YAML、cron、状态) |
| DELETE | `/admin/api/docupipe/projects/{id}` | 软删除(status=archived) |
| POST | `/admin/api/docupipe/projects/{id}/trigger` | 手工触发(可选 body: `pipeline_name`, `mode`) |
| **Runs** ||
| GET | `/admin/api/docupipe/runs?project_id=...&status=...&page=...` | 分页列表 |
| GET | `/admin/api/docupipe/runs/{id}` | 详情(含 error_message) |
| GET | `/admin/api/docupipe/runs/{id}/log?tail=200` | 读日志尾部(默认 200 行,上限 1000) |
| GET | `/admin/api/docupipe/runs/{id}/download-log` | 下载完整 log |
| POST | `/admin/api/docupipe/runs/{id}/cancel` | 取消(running→SIGTERM / pending→status=cancelled) |
| **Dashboard** ||
| GET | `/admin/api/docupipe/stats` | 仪表板汇总 |
| **Pages** ||
| GET | `/docupipe` | 重定向到 `/docupipe/projects` |
| GET | `/docupipe/credentials` | 凭证管理 |
| GET | `/docupipe/credentials/new` | 设备流二维码页 |
| GET | `/docupipe/projects` | 项目列表 |
| GET | `/docupipe/projects/new` | 新建 |
| GET | `/docupipe/projects/{id}/edit` | 编辑 |
| GET | `/docupipe/projects/{id}/runs` | 项目 run 历史 |
| GET | `/docupipe/runs/{id}` | Run 详情 + 日志 |

**变化**:6-21 spec 的 `POST /auth/sso`(SSO token bridge)全部删除,替换为上面 4 个标准 OAuth2 端点。

### 关键端点请求/响应

**POST /projects** 请求体:

```json
{
  "name": "钉钉平台知识库同步",
  "slug": "dingtalk-platform-kb",
  "description": "每天凌晨 3 点从钉钉下载新文档",
  "config_yaml": "pipelines:\n  - name: download\n    source: ...",
  "dws_credential_id": "uuid-...",
  "schedule_cron": "0 3 * * *",
  "schedule_enabled": true,
  "schedule_pipeline": "download",
  "schedule_mode": "incremental"
}
```

后端校验:

- `name` 唯一、`slug` 唯一(只允许 `[a-z0-9-]`)
- `config_yaml` 必须能被 `yaml.safe_load` 解析 → 必须含 `pipelines` key 且是 list
- `schedule_cron` 若非空 → `croniter.is_valid()` 校验,否则 400
- `dws_credential_id` 必须存在且 status=active
- 不调 docupipe 验证 YAML 业务正确性(那是 run 时报错的事)

**POST /projects/{id}/trigger** 请求体(可选):

```json
{"pipeline_name": "download", "mode": "incremental"}
```

不传则用 project 默认(`schedule_pipeline`、`schedule_mode`)。

**GET /runs/{id}/log?tail=N**:

- 文件不存在 → 404
- Python 读文件反向迭代取末尾 N 行(N 上限 1000,避免 shell 依赖 `tail`)
- 响应:`{"lines": [...], "truncated": bool, "total_bytes": int}`

### cron 变更触发调度器重载

`PUT /projects/{id}` 改到任何 `schedule_*` 字段时,API 层在 DB commit 后立即调 `scheduler_service.schedule_project(id)`。不在事务里,失败只记 log。删除(archived)→ `unschedule_project(id)`。

### OAuth2 登录流程(接入点)

```
1. 用户访问 docupipe-manager 业务页(未带 docupipe_session cookie)
   → get_current_user 抛 401 with Location: /auth/login-redirect
2. GET /auth/login-redirect
   → 生成 state(CSRF),302 到 xinyi-platform:8000/oauth/authorize?
     response_type=code&client_id=docupipe-prod
     &redirect_uri=<DOCUPIPE_MANAGER_OAUTH_REDIRECT_URI>
     &state=<csrf>&return_to=<...>
3. 平台校验 client_id + redirect_uri,未登录跳平台 /login
4. 用户登录平台后静默签发 code,302 回 docupipe-manager /auth/callback?code=...&state=...
5. docupipe-manager 校验 state,POST 平台 /oauth/token {code, client_secret, redirect_uri}
   → 拿到 access_token(15min) + refresh_token(7d) + user info
6. 设 cookie: docupipe_session=access_token, docupipe_refresh=refresh_token
7. 302 to return_to
8. 后续请求: docupipe-manager 本地验签 access_token (共享 jwt_secret)
   → access 过期时前端调 /auth/refresh
```

### 审计推送

CRUD / 触发 run / 凭证操作等动作成功后,业务侧 `asyncio.create_task(platform_client.push_audit({...}))` 推审计到 xinyi-platform `/internal/audit`。fire-and-forget,永不阻塞主请求,平台抖动走 `_post_json` 内的 catch。事件前缀 `docupipe.*`,如 `docupipe.project.create`、`docupipe.run.trigger`、`docupipe.credential.revoke`。

### 服务层依赖注入

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()

    # Alembic 自动迁移
    await loop.run_in_executor(_pool, _run_migrations)

    engine = create_async_engine(settings.database_url)

    # 孤儿清理:重启时把 pending/running 改为 failed
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE docupipe_manager.pipeline_runs "
            "SET status='failed', error_message='process restart' "
            "WHERE status IN ('pending', 'running')"
        ))

    platform_client = XinyiPlatformClient(PlatformSettings())
    user_cache = UserLRUCache(ttl=settings.user_cache_ttl_seconds)

    runner = RunnerService(engine, settings, platform_client)
    scheduler = SchedulerService(runner, engine, settings)
    credential = CredentialService(engine, settings, platform_client)

    await scheduler.start()

    app.state.runner = runner
    app.state.scheduler = scheduler
    app.state.credential = credential
    app.state.platform_client = platform_client
    app.state.user_cache = user_cache
    app.state.settings = settings
    app.state.engine = engine

    yield

    await scheduler.stop()
    await engine.dispose()
```

API 路由通过 `Depends` 取 `app.state` 上的 service 单例。

## §6 测试策略

沿用 6-21 spec 的分层 + 用例清单,改动如下:

### 分层

| 层 | 范围 | 怎么 mock |
|---|---|---|
| 单元测试 | Settings 校验、YAML 校验、cron 校验、临时目录生成、日志截断、SM4、JWT 本地验签、OAuth2 state CSRF | 纯函数 |
| Service 层测试 | RunnerService / SchedulerService / CredentialService / XinyiPlatformClient / UserLRUCache | mock DB + `monkeypatch asyncio.create_subprocess_exec` + httpx mock |
| API 层测试 | 所有 router 端点鉴权/校验/响应 + OAuth2 callback/refresh/logout | FastAPI `dependency_overrides`,mock service + mock platform_client |
| 集成测试(稀疏) | 真跑 docupipe 一次,验证 subprocess 编排 | 不 mock subprocess,真起 docupipe(localdrive source/dest);mock `dws auth import`;mock 平台回调 |

### 关键用例

**RunnerService**:
- `start_run_success` — subprocess 返回 0,status=succeeded,exit_code 写入,临时 HOME 清理
- `start_run_docupipe_failure` — subprocess 非零,status=failed,error_message 是 stderr 末尾
- `start_run_timeout` — 卡住超时,发 SIGTERM,status=failed,error="timeout"
- `start_run_semaphore_queuing` — 3 任务信号量=2,第三个保持 pending
- `cancel_running_run` — 改 cancelled 后 subprocess 收到 SIGTERM
- `cancel_pending_run` — 信号量未获取时取消,直接改 status
- `temp_home_cleanup_on_failure` — 异常路径临时 HOME 仍被 rmtree
- `config_yaml_written_to_disk` — DB YAML 真被写到 `<project_dir>/config.yaml`
- `run_success_pushes_audit_event` — 成功/失败后用 `platform_client.push_audit` 推送事件(mock client,断言被调用)

**SchedulerService**:
- `start_loads_active_projects` — 2 active + 1 paused,启动后只有 2 个 cron job
- `schedule_project_registers_job`
- `unschedule_project_removes_job`
- `cron_change_reloads_job` — schedule_cron 改变后,job trigger 更新
- `disabled_project_does_not_fire` — schedule_enabled=False 时 start_run 不被调用
- `memory_job_store_rebuilds_on_restart`

**CredentialService**:
- `start_device_login_parses_dws_output` — mock subprocess 返回真实 dws JSON,确认解析出 user_code/verification_url
- `finalize_login_encrypts_and_stores` — mock dws status + export,验证 SM4 加密入库、`refresh_token_expires_at` 正确
- `check_status_updates_expires_at`
- `revoke_does_not_delete`
- `finalize_pushes_audit_event`
- `revoke_pushes_audit_event`

**XinyiPlatformClient**:
- `batch_get_users_retries_on_server_error`
- `batch_get_users_partial_null_for_missing`
- `push_audit_failure_does_not_block_caller` — 关键:异常永不 raise
- `refresh_token_success_returns_new_pair`
- `refresh_token_revoked_returns_none`

**UserLRUCache**:
- `lru_get_hit`、`lru_get_miss`、`lru_eviction_when_full`、`lru_expiry_after_ttl`

**API 层**:
- 所有端点 happy path + 主要错误分支
- 非 admin 调用 → 403
- YAML/cron/slug 无效 → 400/409
- run log 不存在 → 404
- `callback_valid_code_exchanges_and_sets_cookie`
- `callback_invalid_state_returns_400`
- `callback_invalid_code_returns_401`
- `callback_redirect_to_return_to`
- `refresh_success_updates_cookies`
- `refresh_with_expired_refresh_token_redirects_to_login`
- `refresh_with_revoked_token_401`
- `unauthenticated_request_redirects_to_xinyi_platform`
- `redirect_url_includes_return_to_and_state_csrf`
- `logout_clears_docupipe_cookies_and_calls_platform_revoke`

### pytest 配置

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["integration: real docupipe runs (slow, skipped by default)"]
addopts = "-m 'not integration'"
```

`pytest -m integration` 才跑集成测试。

### conftest.py

与 hindsight-manager / xinyi-platform 对称:env 设默认值(`DOCUPIPE_MANAGER_*`)、mock 平台 HTTP、mock `get_session` 返回 mock AsyncSession,不真连 Postgres。

### 覆盖率目标(v1 不强制阈值,核心 service 建议)

- RunnerService: ≥ 90%
- SchedulerService: ≥ 85%
- CredentialService: ≥ 75%(设备流 mock 难度高)
- XinyiPlatformClient: ≥ 85%
- API 层: ≥ 70%

## §7 UI 设计要点

### 导航集成

用 `xinyi_platform.ui_common.install_ui()` 接入共享顶部导航:

```python
from xinyi_platform.ui_common import install_ui

install_ui(
    app,
    current_service="docupipe-manager",
    nav_menu=DOCUPIPE_NAV_MENU,
    brand=settings.brand_name,
    platform_url=settings.platform_url,
    manager_url="",
    docupipe_url=settings.base_url,
)
```

业务侧自己的 `templates/base.html` 通过 `ui_jinja_globals` helper 取 `ui.nav_menu` / `ui.products` globals,渲染侧栏。sidebar 与 hindsight-manager 不同(任务管理本来就与 tenant/api_key 不同),不强求合并。

样式与 hindsight-manager 自定义 CSS 对齐(非 Tailwind/Bootstrap)。v1 不 inherited hm 的样式文件 —— `ui_common` 静态资源够了。

### 导航菜单 `DOCUPIPE_NAV_MENU`

```python
DOCUPIPE_NAV_MENU = [
    {"type": "section", "label": "账户",
     "items": [{"id": "account", "label": "我的账户", "href": "/account"}]},
    {"type": "section", "label": "管理", "require_admin": True,
     "items": [
         {"id": "projects",    "label": "项目",   "href": "/docupipe/projects"},
         {"id": "credentials", "label": "凭证",   "href": "/docupipe/credentials"},
         {"id": "runs",        "label": "运行",   "href": "/docupipe/runs"},
     ]},
]
```

### 关键页面

**仪表板 / 项目列表 `/docupipe/projects`**

顶部统计条:`[项目 N 个] [活跃凭证 x/y] [今日运行 N 次] [失败 N 个↑]`。失败 > 0 时标红 + 链接到 `?status=failed` 的 runs。

项目列表表格列:名称(链接)、slug、凭证(过期标红)、cron(若无 "—")、下次运行时间(croniter 算)、上次运行状态(成功绿/失败红/—)、操作(编辑 / 立即运行 / 归档)。

**项目编辑 `/docupipe/projects/{id}/edit`**

- 基本信息:名称、slug、描述、绑定的凭证(下拉)
- YAML 编辑器:textarea + 等宽字体,**不引入 codemirror/monaco**
- 调度:cron 文本框 + "启用调度"开关 + "运行哪个 pipeline"(从 YAML 解析所有 pipeline name 给下拉)+ mode(full/incremental/mirror)
- "立即运行"按钮(可不保存就触发,触发时用表单当前值)
- 提交:保存 → 同步重载 scheduler

**凭证列表 `/docupipe/credentials`**

表格列:名称、corp_id、状态(徽章)、access_token 过期、refresh_token 过期(倒计时,< 7 天黄/< 1 天红)、操作(查看状态 / 重新登录 / 撤销)。

**添加凭证 `/docupipe/credentials/new`** —— 设备流

- 后端启动设备流 → 返回 `verification_url` + `user_code`
- v1 不生成二维码图片:直接显示 URL 文本 + user_code,用户复制链接到浏览器扫
- JS 每 5 秒调 `/poll?session_key=...`(setTimeout 链,非 WebSocket)
- poll 返回 success → 自动跳 `/finalize`(输入名称确认)
- poll 返回 failed / 15 分钟超时 → "重新开始"按钮

**运行列表 `/docupipe/runs`**(可按 project_id 过滤)

表格列:project 名、触发类型、pipeline name、状态(徽章)、起止时间 + 耗时、操作(查看详情 / 取消)。

**运行详情 `/docupipe/runs/{id}`**

- 顶部元数据(project、状态、起止、exit_code、触发者)
- 失败时显眼显示 error_message(等宽字体块)
- "取消运行"按钮(running/pending 时)
- 日志面板:默认末尾 200 行,"显示全部"按钮下载完整 log
- 日志等宽字体、可滚动、`white-space: pre-wrap`

### UX 细节

- 状态徽章:与 hindsight-manager 现有 `admin_task_monitor.html` 风格对齐(等宽字体块、绿/红/灰),但不引静态资源依赖
- 失败 banner:全局顶栏显眼提示,**只在 `/docupipe/*` 路径下显示**,不污染其它产品页面
- cron 输入框下面实时显示"下次运行:YYYY-MM-DD HH:MM"(纯 JS,v1 可选)
- 设备流轮询:`setTimeout` 链而非 WebSocket
- 归档确认:删除项目用二次确认 dialog

## §8 部署与生命周期

### docker-compose 集成

docupipe-manager 自己的 docker-compose.yml,跟 hindsight-manager / xinyi-platform 的 compose 并列:

```yaml
services:
  docupipe-manager:
    build: .
    ports:
      - "8002:8002"
    env_file: .env
    volumes:
      - ./data:/var/lib/docupipe-manager
      - /tmp:/tmp                    # 临时 HOME 给 dws auth
    networks:
      - default
      - hindsight_default

networks:
  hindsight_default:
    external: true
```

`hindsight_default` 是 hindsight-manager compose 创建的默认网络。docupipe-manager 加入即可访问 `postgres` 与 `xinyi-platform` service。

### Dockerfile

```dockerfile
FROM python:3.12-slim

# dws CLI(设备流需要)
RUN curl -fsSL https://raw.githubusercontent.com/DingTalk-Real-AI/dingtalk-workspace-cli/main/scripts/install.sh | sh

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

COPY docupipe_manager ./docupipe_manager

CMD alembic upgrade head && uvicorn docupipe_manager.main:app --host 0.0.0.0 --port 8002
```

v1 不装 MinerU(镜像膨胀 vs PDF OCR 需求 tradeoff)。用户需要 OCR 时自行改 Dockerfile。

### 数据库迁移

`alembic.ini`:`script_location = docupipe_manager/migrations`,`version_table_schema = docupipe_manager`。跟 hindsight-manager / xinyi-platform 各管各的版本表,不污染别的 alembic_version。

v1 初始迁移创建:

- schema `docupipe_manager`
- 4 个 ENUM
- 3 张表

启动时自动迁移(FastAPI lifespan 里调 `alembic upgrade head`)。

### 信号处理

进程收到 SIGTERM/SIGINT(docker stop):

1. APScheduler `shutdown(wait=False)`
2. 所有 in-flight subprocess 收到 SIGTERM
3. run 记录由下次启动的孤儿清理修正为 failed

docker stop 默认 10 秒宽限,够 docupipe 接收 SIGTERM 做 `.state/` 落盘,但不保证当前文档处理完成。

### 健康检查

`/health` 返回 `{"status": "ok"}`,与 hindsight-manager / xinyi-platform 对称。

### 部署准备清单

1. **平台侧**(依赖 xinyi-platform 部署完成):
   - 编辑 `xinyi_platform/ui_common/registry.py` 新增 docupipe-manager 条目
   - `install_ui._resolve_products` 扩参数 `docupipe_url`(平平接受 `None`)
   - 在 `xinyi.business_clients` 表注册 `docupipe-prod` client(SQL 脚本或 admin UI),生成 client_secret,redirect_uri = `<DOCUPIPE_MANAGER_OAUTH_REDIRECT_URI>`
2. **docupipe-manager 侧**:
   - 配置 `.env`:`JWT_SECRET`、`ENCRYPTION_KEY` 跟平台一值;`OAUTH_CLIENT_SECRET` 跟注册时同值;`OAUTH_REDIRECT_URI` 跟注册一致
   - 部署 docker-compose

## §9 实现顺序建议

供后续 writing-plans 参考:

1. **Phase 0 — 项目骨架**:pyproject、目录、Settings、独立 `db.py` / `crypto.py`、`main.py` + lifespan、Alembic 初始迁移、Dockerfile、docker-compose
2. **Phase 1 — 接入平台**:`auth/session.py` + `oauth_state.py` + `dependencies.py`、`platform/` (XinyiPlatformClient + UserLRUCache)、`api/auth.py` 4 个 OAuth2 端点 + 单测
3. **Phase 2 — xinyi-platform 适配**:编辑 `ui_common/registry.py`、`install_ui` 扩 `docupipe_url` 参数、注册 `docupipe-prod` business_client 的 SQL
4. **Phase 3 — 数据模型**:3 张表 + 4 个 ENUM 的 SQLAlchemy 模型
5. **Phase 4 — CredentialService + 设备流**:dws 集成、SM4 加密入库、UI 凭证页 + 测试
6. **Phase 5 — RunnerService**:subprocess 编排、临时 HOME、日志捕获、取消、审计推送 + 测试
7. **Phase 6 — SchedulerService**:APScheduler + cron 注册 + 重载 + 测试
8. **Phase 7 — Projects API + UI**:CRUD、YAML 编辑、立即触发 + 测试
9. **Phase 8 — Runs API + UI**:列表、详情、日志查看、取消 + 测试
10. **Phase 9 — 统计仪表板**:全局 banner + `/admin/api/docupipe/stats` 端点
11. **Phase 10 — 集成测试**:localdrive 真跑一次

## 已知后续工作(超出 v1)

- 平台 SDK 抽取:若第 3 个业务接入,考虑把 `XinyiPlatformClient + LRU cache` 抽成独立 pip 包,docupipe-manager 切换为依赖该包
- 多实例部署:设备流状态从进程内 dict 改为 Redis / Postgres 表
- YAML 表单化编辑器(v2 可选)
- MinerU OCR 集成(用户按需,镜像膨胀 tradeoff)
- 失败主动提醒(企业微信 / 钉钉机器人 webhook)
- venv 隔离 / 容器级隔离(每个 project 独立运行环境)
- 运行重试链(自动重跑 max N 次)

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAN | 7 issues, 0 critical gaps |

**VERDICT:** ENG REVIEW CLEARED — ready to implement.

### Review Decisions

| # | Section | Issue | Decision |
|---|---------|-------|----------|
| A1 | Architecture | Device flow state cleanup (memory leak on abandon) | Keep current + add timeout cleanup |
| A2 | Architecture | Graceful shutdown CancelledError race | Add CancelledError handler |
| A3 | Architecture | No request body size limit (OOM risk) | Add Starlette middleware (1MB / 413) |
| C1 | Code Quality | SM4 crypto.py duplicated from xinyi-platform | Accept duplication (per decision 14) |
| C2 | Code Quality | `mode` param no enum validation | Add Pydantic `Literal['full','incremental','mirror']` |
| C3 | Code Quality | YAML parse returns non-dict → TypeError | Add `isinstance(config, dict)` guard |
| T1 | Test | CancelledError regression test | Unit + service layer tests |
| T2 | Test | Log truncation algorithm no tests | Unit test (UTF-8 edges, boundaries) |
| P1 | Performance | UserLRUCache no maxsize → unbounded growth | `maxsize=1000` |

### Failure Modes Flagged

| Failure | Covered | Risk |
|---------|---------|------|
| Shutdown in-flight run | ✅ test + handler | Low |
| Device flow session leak | ✅ timeout cleanup | Low |
| SM4 key drift with platform | ❌ no health check | Medium — v2 item |
| DWS CLI not installed | ❌ no startup check | Medium — v2 item |

### New Test Requirements
- [CRITICAL] `CancelledError` during shutdown — `tests/unit/test_runner_cancel.py`
- [HIGH] Log truncation — `tests/unit/test_log_truncation.py`

### Worktree Parallelization
- Lane A: Phase 0 → 1 → 4 → 7 (sequential, shared platform/)
- Lane B: Phase 3 → 5 → 6 → 8 (sequential, shared models/ + services/)
- Lane C: Phase 2 (xinyi-platform repo, independent)
- Phase 4 ∥ Phase 5 (no shared modules)
- Phase 7 ∥ Phase 8 (no shared modules)
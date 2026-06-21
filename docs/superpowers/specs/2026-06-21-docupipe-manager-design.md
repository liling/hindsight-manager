# docupipe-manager 设计文档

**日期**: 2026-06-21
**状态**: 设计已确认,待用户审阅
**项目位置**: `~/src/lab/docupipe-manager/`(新建)

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

## 关键决策

| # | 决策 | 选定 |
|---|---|---|
| 1 | 整体形态 | 独立项目 `~/src/lab/docupipe-manager/`,与 hindsight-manager 并列 |
| 2 | 共享基础设施 | 通过 import 复用 hindsight-manager 的 auth/db/crypto;不发布独立 PyPI 包(v1 用 path install) |
| 3 | 管道运行进程模型 | subprocess + 进程内 APScheduler(`asyncio.create_subprocess_exec`) |
| 4 | dws 认证机制 | 浏览器扫码 → 后台 `dws auth login --device` → `dws auth export --base64` → SM4 加密入库 |
| 5a | 凭证数量 | 多份(`dws_credentials` 表,project 关联到具体凭证) |
| 5b | 失效感知 | 失败日志自然暴露,不做主动提醒 |
| 6a | 配置编辑形态 | 整段 YAML 文本编辑 |
| 6b | project↔pipeline | 一 project 多 pipeline,运行时 `--pipeline NAME` 指定(不指定则全跑) |
| 7a | 调度表达式 | 裸 cron 字符串(标准 5 段) |
| 7b | 调度器 | 进程内 APScheduler + MemoryJobStore |
| 8a | 日志 | 文件存全文 + DB 存摘要 + 路径 |
| 8b | 进程隔离 | 独立子进程 + 临时 HOME |
| 8c | 失败感知 | UI banner |
| 认证 | 跨服务认证 | SSO token 桥接(C1b:自包含短 JWT + 共享 `jwt_secret`,无跨服务 HTTP 调用) |
| UI 继承 | 自建 `docupipe_admin_base.html` extends hindsight-manager 的 `base.html` |
| YAML 编辑器 | textarea,不引外部库 |
| 二维码 | v1 用文本 URL |
| 部署 | 独立 docker-compose,加入 hindsight-manager 的 `hindsight_default` 网络 |
| 端口 | 8002 |
| schema 名 | `docupipe_manager` |

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
│   ├── main.py                       # FastAPI app + lifespan(起 APScheduler)
│   ├── config.py                     # Settings,env prefix: DOCUPIPE_MANAGER_
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── dependencies.py           # get_current_user / require_admin(独立 cookie name)
│   │   └── session.py                # JWT 编解码、SSO token 处理
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py                   # /auth/sso 端点
│   │   ├── pages.py                  # UI 页面
│   │   ├── projects.py
│   │   ├── credentials.py
│   │   └── runs.py
│   ├── models/
│   │   ├── __init__.py
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
│   ├── templates/
│   │   ├── docupipe_admin_base.html  # extends hindsight_manager base.html
│   │   └── docupipe/
│   │       ├── projects.html
│   │       ├── project_form.html
│   │       ├── credentials.html
│   │       ├── credential_login.html
│   │       └── runs.html
│   └── static/
└── tests/
```

### pyproject.toml 关键依赖

```toml
[project]
name = "docupipe-manager"
dependencies = [
    "hindsight-manager",       # path install 用于开发
    "fastapi",
    "uvicorn",
    "sqlalchemy[asyncio]",
    "alembic",
    "apscheduler",
    "croniter",
    "docupipe",
    "pyyaml",
    "jinja2",
    "pydantic-settings",
    "python-jose[cryptography]",
]
```

`hindsight-manager` 在 `pyproject.toml` 中通过 path install 引入:

```toml
[tool.uv.sources]
hindsight-manager = { path = "../hindsight-manager" }
```

生产部署方式(私有 PyPI / git mono repo 等)不在 v1 范围。

### 复用 hindsight-manager 的部分

**复用(import)**:
- `hindsight_manager.db`(engine、`get_session`、`init_db`)
- `hindsight_manager.crypto`(SM4 加密 dws auth 包)
- `hindsight_manager.models.user.User`(只读 `manager.users`)
- env 变量:`DATABASE_URL` / `ENCRYPTION_KEY` / `JWT_SECRET` 跟 hindsight-manager 共享同一个值

**不复用**:
- `hindsight_manager.auth.dependencies`(cookie name 不同,docupipe-manager 用 `docupipe_session`)
- `hindsight_manager.config.Settings`(docupipe-manager 有自己的 Settings 子集)
- hindsight-manager 的业务表(tenants/api_keys/...)
- hindsight-manager 的 router

**关于 `init_db(settings)` 的兼容性**:hindsight-manager 的 `init_db` 期望其自己的 Settings 类型。docupipe-manager 在 lifespan 里**直接用 hindsight-manager 的 Settings 类**(`from hindsight_manager.config import Settings as HMSettings`)实例化一份,把共享的 env 值(database_url、encryption_key 等)传进去。docupipe-manager 自己的 Settings 仅负责它独有的字段(data_dir、dws_cli_path、run_timeout 等)。两个 Settings 实例并存,各管各的字段子集。

### DB / schema 规划

共用同一 Postgres,独立 schema `docupipe_manager`(可通过 `DOCUPIPE_MANAGER_MANAGER_SCHEMA` 配置)。

Alembic 配置:
- `script_location = docupipe_manager/migrations`
- `version_table_schema = docupipe_manager`

不建跨 schema FK constraint(`created_by` 等仅做逻辑引用),跟 hindsight-manager 现有模式一致。

## §2 数据模型

三张表 + 四个 ENUM,都在 schema `docupipe_manager`。

### 表 1: `dws_credentials`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) UNIQUE | 用户可读名,如 "平台产品知识库-主账号" |
| `corp_id` | VARCHAR(64) | 从 `dws auth status` 读到,登录后回填 |
| `auth_blob` | BYTEA | SM4 加密的 `dws auth export --base64` 产物 |
| `token_expires_at` | TIMESTAMPTZ | access token 过期(通常 2 小时) |
| `refresh_token_expires_at` | TIMESTAMPTZ | refresh token 过期(通常 30 天)—— 真正失效点 |
| `last_refreshed_at` | TIMESTAMPTZ | 最后一次 dws 状态查询成功时间 |
| `status` | ENUM `credential_status` | `active` / `expired` / `revoked` |
| `created_by` | UUID | 逻辑引用 `manager.users.id` |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

索引:`name` 唯一;`(status, refresh_token_expires_at)` 用于过期扫描。

`token_expires_at` 过期不影响可用性(dws CLI 用 refresh_token 自动续)。只有 `refresh_token_expires_at` 过期才真正失效,需要重新扫码。

### 表 2: `docupipe_projects`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) UNIQUE | 用户可读名 |
| `slug` | VARCHAR(64) UNIQUE | 文件系统安全的目录名,`[a-z0-9-]` |
| `description` | TEXT | 自由说明 |
| `config_yaml` | TEXT | 整段 docupipe.yaml 内容 |
| `dws_credential_id` | UUID NOT NULL | 逻辑引用 `dws_credentials.id` |
| `schedule_cron` | VARCHAR(64) NULL | 标准 5 段 cron;NULL 表示只手工触发 |
| `schedule_enabled` | BOOLEAN DEFAULT TRUE | cron 存在但暂停时可关闭 |
| `schedule_pipeline` | VARCHAR(255) NULL | 调度时调用的 pipeline 名;NULL 表示全跑 |
| `schedule_mode` | VARCHAR(16) DEFAULT 'incremental' | 透传 `--mode` 给 docupipe |
| `status` | ENUM `project_status` | `active` / `paused` / `archived` |
| `created_by` | UUID | 逻辑引用 `manager.users.id` |
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
| `error_message` | TEXT NULL | 失败时的错误摘要(stderr 末尾 2KB) |
| `created_at` | TIMESTAMPTZ | |

索引:`(project_id, created_at DESC)` 复合索引(列表最常见查询);`status` 单列索引。

不存 per-document 进度(由 docupipe 的 `.state/` 管)。

### ENUM 定义

```sql
CREATE TYPE docupipe_manager.credential_status AS ENUM ('active', 'expired', 'revoked');
CREATE TYPE docupipe_manager.project_status   AS ENUM ('active', 'paused', 'archived');
CREATE TYPE docupipe_manager.run_trigger_type AS ENUM ('manual', 'scheduled');
CREATE TYPE docupipe_manager.run_status      AS ENUM ('pending', 'running', 'succeeded', 'failed', 'cancelled');
```

## §3 配置(Settings)

```python
class Settings(BaseSettings):
    database_url: str
    manager_schema: str = "docupipe_manager"

    data_dir: str = "/var/lib/docupipe-manager"

    dws_cli_path: str = "dws"
    docupipe_python: str = "python"
    docupipe_working_dir: str = ""

    run_timeout_seconds: int = 0                  # 0 = 不限时
    max_concurrent_runs: int = 3
    run_log_max_bytes: int = 10 * 1024 * 1024

    encryption_key: str = ""                      # 必须与 hindsight-manager 对齐
    jwt_secret: str                               # 必须与 hindsight-manager 对齐
    sso_token_expire_seconds: int = 60
    session_expire_hours: int = 24

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
        ├── .state/                     # docupipe 的状态目录
        ├── output/                     # 约定:YAML 里 output_dir 相对路径会落在这下面
        └── runs/
            └── <run_id>.log            # 单次 run 的 stdout+stderr 全量
```

subprocess 启动时 `cwd = data_dir/projects/<slug>/`、`--config config.yaml`、`--state-dir .state` 由 RunnerService 代填。用户 YAML **不要**再写这些路径。

UI 在保存配置前会做"最佳实践提示":若 `output_dir` 是绝对路径,警告"建议相对路径,实际写入 data_dir 下"。这是 lint,非强制。

### 运行限制

- `max_concurrent_runs`:RunnerService 持有 `asyncio.Semaphore(max_concurrent_runs)`,超出的 run 保持 `pending` 等待。
- `run_timeout_seconds`:>0 时,subprocess 用 `asyncio.wait_for` 包,超时发 SIGTERM、宽限 10s 后 SIGKILL,run 标 failed 且 error_message="timeout"。

### 配置同步约束

docupipe-manager 必须跟 hindsight-manager 共享这些 env:

- `HINDSIGHT_MANAGER_DATABASE_URL` ≡ `DOCUPIPE_MANAGER_DATABASE_URL`
- `HINDSIGHT_MANAGER_ENCRYPTION_KEY` ≡ `DOCUPIPE_MANAGER_ENCRYPTION_KEY`
- `HINDSIGHT_MANAGER_JWT_SECRET` ≡ `DOCUPIPE_MANAGER_JWT_SECRET`

### `.env.example`

```bash
DOCUPIPE_MANAGER_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/hindsight
DOCUPIPE_MANAGER_MANAGER_SCHEMA=docupipe_manager

# 必须与 hindsight-manager 的对应项一致
DOCUPIPE_MANAGER_ENCRYPTION_KEY=<32 hex chars>
DOCUPIPE_MANAGER_JWT_SECRET=<same as hindsight-manager>

DOCUPIPE_MANAGER_DATA_DIR=/var/lib/docupipe-manager

DOCUPIPE_MANAGER_DWS_CLI_PATH=/usr/local/bin/dws
DOCUPIPE_MANAGER_DOCUPIPE_PYTHON=python

DOCUPIPE_MANAGER_RUN_TIMEOUT_SECONDS=0
DOCUPIPE_MANAGER_MAX_CONCURRENT_RUNS=3

DOCUPIPE_MANAGER_HOST=0.0.0.0
DOCUPIPE_MANAGER_PORT=8002
DOCUPIPE_MANAGER_BASE_URL=http://localhost:8002
```

## §4 服务层

### §4.1 RunnerService —— 跑管道的核心

```python
class RunnerService:
    def __init__(self, engine, settings: Settings):
        self._engine = engine
        self._settings = settings
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
        ...
```

`start_run` 立即 INSERT run 记录后 `asyncio.create_task(_execute_run(run_id))`,返回 run 实体。

`_execute_run` 完整生命周期:

1. `async with semaphore:` —— 等并发槽
2. UPDATE run SET status=running, started_at=now, pid=...
3. 准备目录:
   - `home_dir = mkdtemp(prefix="dws-home-")` —— 临时 HOME,放 dws 凭证
   - `project_dir = data_dir/projects/<slug>/`
   - `config_path = project_dir/config.yaml`
4. 写 config.yaml(从 DB config_yaml 字段)
5. 解 SM4 取 auth_blob → 写 `<home_dir>/auth.b64`(绝对路径,避免 cwd 漂移)
6. `dws auth import -i <home_dir>/auth.b64 --base64`(env: HOME=<home_dir>)
7. `python -m docupipe run --config config_path [--pipeline NAME] --mode <mode> --state-dir <project_dir>/.state --log-level INFO`(env: HOME=home_dir,cwd=project_dir)
8. stdout/stderr 边读边写到 `log_path`;超出 `run_log_max_bytes` 时保留首尾、截断中段
9. 等 exit code(或 `asyncio.wait_for` 超时)
10. UPDATE run SET status=succeeded/failed, exit_code, completed_at, error_message
11. finally: `shutil.rmtree(home_dir)`(任何路径都要清,避免泄漏 auth.b64)

工程细节:

- subprocess 用 `asyncio.create_subprocess_exec`,不阻塞事件循环
- `error_message`:失败时取 stderr 末尾 2KB
- `pid` 字段:启动后立即写入,UI 可发 SIGTERM
- 取消:running → SIGTERM;pending → 直接改 status 跳过执行
- `_execute_run` 是 fire-and-forget task,所有异常捕获后写 error_message,status 标 failed

### §4.2 SchedulerService —— APScheduler 编排

```python
class SchedulerService:
    def __init__(self, runner: RunnerService, engine, settings):
        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._runner = runner
        ...

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
        project = await session.get(DocpipeProject, project_id)
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

JobStore:MemoryJobStore(默认)。进程重启时所有 cron job 丢失,但 `start()` 时从 DB 重建 —— 重启代价仅"到下一个 cron 触发点的等待"重置,可接受。不选 SQLAlchemyJobStore,因为它会自建表、生命周期跟 `pipeline_runs` 解耦,反而更复杂。

触发器:`CronTrigger.from_crontab(schedule_cron)` 直接解析 5 段标准 cron。v1 不支持秒级。

### §4.3 CredentialService —— dws 设备流 + 凭证管理

```python
class CredentialService:
    async def start_device_login(self, name: str) -> dict:
        """启动 dws auth login --device,返回 verification_url + user_code + session_key。"""
        ...

    async def poll_device_login(self, session_key: str) -> dict:
        """前端轮询:{"status": "pending" | "success" | "failed"}。"""
        ...

    async def finalize_login(self, session_key: str, name: str, user_id: UUID) -> DwsCredential:
        """登录成功后:查 dws auth status + dws auth export --base64 + SM4 加密入库。"""
        ...

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

设备流状态暂存:`{session_key: subprocess_handle + home_dir + name}` 进程内字典。v1 单实例假设。多实例部署是 v2 的事,届时换 Redis 或 Postgres 表,service 接口已预留(session_key 是 opaque string)。

`finalize_login` 后流程:
1. `dws auth status` 读 corp_id / expires_at / refresh_expires_at
2. `dws auth export --base64 -o <tmpfile>` 拿认证包字节
3. SM4 加密入库,status=active
4. 清理临时 HOME(`shutil.rmtree`)

## §5 API 层

所有 `/admin/api/docupipe/*` 端点都 `Depends(require_admin)`(docupipe-manager 自有的 `auth/dependencies.py`)。UI 页面用 `Depends(get_current_user)` + 模板层校验 `user.role == admin`。

### 路由清单

| Method | Path | 功能 |
|---|---|---|
| **Auth** ||
| POST | `/auth/sso` | 接收 hindsight-manager POST 的 SSO token,验签后设自己的 cookie,重定向到 `/docupipe` |
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

### POST /projects 请求体

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

### POST /projects/{id}/trigger 请求体(可选)

```json
{
  "pipeline_name": "download",
  "mode": "incremental"
}
```

不传则用 project 默认(`schedule_pipeline`、`schedule_mode`)。

### GET /runs/{id}/log?tail=N

- 文件不存在 → 404
- Python 读文件反向迭代取末尾 N 行(N 上限 1000,避免 shell 依赖 `tail`)
- 响应:`{"lines": [...], "truncated": bool, "total_bytes": int}`

### cron 变更触发调度器重载

`PUT /projects/{id}` 改到任何 `schedule_*` 字段时,API 层在 DB commit 后立即调 `scheduler_service.schedule_project(id)`。不在事务里,失败只记 log。删除(archived)→ `unschedule_project(id)`。

### 服务层依赖注入

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    init_db(settings)
    engine = create_async_engine(settings.database_url)

    app.state.runner = RunnerService(engine, settings)
    app.state.scheduler = SchedulerService(app.state.runner, engine, settings)
    app.state.credential = CredentialService(engine, settings)
    await app.state.scheduler.start()

    yield

    await app.state.scheduler.stop()
    await engine.dispose()
```

API 路由通过 `Depends` 取 `app.state` 上的 service 单例。

## §6 测试策略

跟 hindsight-manager 惯例对齐:`pytest-asyncio` + `asyncio_mode = "auto"`,mock DB 不打真 Postgres。

### 分层

| 层 | 范围 | 怎么 mock |
|---|---|---|
| 单元测试 | Settings 校验、YAML 校验、cron 校验、临时目录生成、日志截断 | 纯函数 |
| Service 层测试 | RunnerService / SchedulerService / CredentialService 核心流程 | mock DB + monkeypatch `asyncio.create_subprocess_exec` |
| API 层测试 | 所有 router 端点鉴权 / 校验 / 响应 | FastAPI `dependency_overrides`,mock service |
| 集成测试(稀疏) | 真跑 docupipe 一次,验证 subprocess 编排 | 不 mock subprocess,真起 docupipe(localdrive source/dest,无需钉钉);mock `dws auth import` 命令 |

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

**API 层**:所有端点 happy path + 主要错误分支;非 admin 调用 → 403;YAML/cron/slug 无效 → 400/409;run log 不存在 → 404。

### pytest 配置

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["integration: real docupipe runs (slow, skipped by default)"]
addopts = "-m 'not integration'"
```

`pytest -m integration` 才跑集成测试。

### conftest.py

跟 hindsight-manager 对称:env 设默认值(`DOCUPIPE_MANAGER_*`),mock `get_session` 返回 mock AsyncSession。不真连 Postgres。

### 覆盖率目标(v1 不强制阈值,核心 service 建议)

- RunnerService: ≥ 90%
- SchedulerService: ≥ 85%
- CredentialService: ≥ 75%(设备流 mock 难度高)
- API 层: ≥ 70%

## §7 UI 设计要点

### 导航集成

自建 `docupipe_admin_base.html` extends hindsight-manager 的 `base.html`(最顶层骨架),自己写自己的 sidebar。不强行合并 hindsight-manager 的 admin sidebar —— 两个工具的 nav 项本来就不同。

样式与 hindsight-manager 自定义 CSS 对齐(非 Tailwind/Bootstrap)。

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
- **v1 不生成二维码图片**:直接显示 URL 文本 + user_code,用户复制链接到浏览器扫
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

- 状态徽章:跟 hindsight-manager 现有 `admin_task_monitor.html` 风格对齐
- 失败 banner:全局顶栏显眼提示,**只在 `/docupipe/*` 路径下显示**,不污染 hindsight-manager 页面
- cron 输入框下面实时显示"下次运行:YYYY-MM-DD HH:MM"(纯 JS,v1 可选)
- 设备流轮询:`setTimeout` 链而非 WebSocket
- 归档确认:删除项目用二次确认 dialog

## §8 部署与生命周期

### docker-compose 集成

docupipe-manager 自己的 docker-compose.yml,跟 hindsight-manager 的 compose 并列(两个项目分别有自己的 compose)。

```yaml
services:
  docupipe-manager:
    build: .
    ports:
      - "8002:8002"
    env_file: .env
    volumes:
      - ./data:/var/lib/docupipe-manager
      - /tmp:/tmp
    networks:
      - default
      - hindsight_default

networks:
  hindsight_default:
    external: true
```

`hindsight_default` 是 hindsight-manager compose 创建的默认网络。docupipe-manager 加入即可访问 `postgres` service。

### Dockerfile

```dockerfile
FROM python:3.12-slim

RUN curl -fsSL https://raw.githubusercontent.com/DingTalk-Real-AI/dingtalk-workspace-cli/main/scripts/install.sh | sh

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

COPY docupipe_manager ./docupipe_manager

CMD alembic upgrade head && uvicorn docupipe_manager.main:app --host 0.0.0.0 --port 8002
```

v1 不装 MinerU(镜像膨胀 vs PDF OCR 需求 tradeoff)。用户需要 OCR 时自行改 Dockerfile。

### 数据库迁移

`alembic.ini`:`script_location = docupipe_manager/migrations`,`version_table_schema = docupipe_manager`。跟 hindsight-manager 各管各的版本表,不污染 `manager.alembic_version`。

v1 初始迁移创建:
- schema `docupipe_manager`
- 四个 ENUM
- 三张表

启动时自动迁移(FastAPI lifespan 里调 `alembic upgrade head`)。

### 应用生命周期

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    engine = create_async_engine(settings.database_url)

    await loop.run_in_executor(_pool, _run_migrations)
    init_db(settings)

    # 孤儿清理:重启时把 pending/running 改为 failed
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE docupipe_manager.pipeline_runs "
            "SET status='failed', error_message='process restart' "
            "WHERE status IN ('pending', 'running')"
        ))

    runner = RunnerService(engine, settings)
    scheduler = SchedulerService(runner, engine, settings)
    credential = CredentialService(engine, settings)

    await scheduler.start()

    app.state.runner = runner
    app.state.scheduler = scheduler
    app.state.credential = credential
    app.state.settings = settings
    app.state.engine = engine

    yield

    await scheduler.stop()
    await engine.dispose()
```

### 信号处理

进程收到 SIGTERM/SIGINT(docker stop):
1. APScheduler `shutdown(wait=False)`
2. 所有 in-flight subprocess 收到 SIGTERM
3. run 记录由下次启动的孤儿清理修正为 failed

docker stop 默认 10 秒宽限,够 docupipe 接收 SIGTERM 做 `.state/` 落盘,但不保证当前文档处理完成。

### 健康检查

`/health` 返回 `{"status": "ok"}`,跟 hindsight-manager 对称。

### 认证:SSO token 桥接(C1b)

跨服务认证用自包含短 JWT + 共享 `jwt_secret`,无跨服务 HTTP 调用。

**流程**:

```
1. admin 在 hindsight-manager 的 dashboard 点"进入文档管道"
2. 浏览器 POST /auth/sso/docupipe-manager(hindsight-manager)
   → 后端生成 1 分钟有效的 JWT,含 {sub, username, type:"sso"}
   → 返回自动提交的 HTML 表单 → POST 到 http://localhost:8002/auth/sso
3. docupipe-manager 收到 POST 表单 token
   → 用共享 jwt_secret 验签 + 检查 type=sso + 未过期
   → 从 token 提取 user_id,查 manager.users 确认存在且 role=admin
   → 生成新的长 JWT(24h, type=session)
   → 设 cookie docupipe_session(host-only, httponly)
   → 重定向到 /docupipe
4. 后续调用都带这个 cookie,docupipe-manager 自己验签
```

**hindsight-manager 侧改动**(3 处):

1. `auth/session.py`:新增 `create_sso_token(user_id, username, target_service)` —— 1 分钟过期 JWT,含 `type:"sso"` claim
2. `api/auth.py`:新增 `POST /auth/sso/docupipe-manager` —— admin 调用,返回自动提交的 HTML 表单页
3. `templates/dashboard.html` 或 admin_base:新增"进入文档管道"链接

**docupipe-manager 侧**:

1. `auth/session.py`:JWT 编解码(复用 hindsight-manager 同款 `python-jose` HS256)
2. `auth/dependencies.py`:`get_current_user` / `require_admin`,cookie name = `docupipe_session`,自己签发 session JWT
3. `api/auth.py`:`POST /auth/sso` 端点

**为什么不用 hindsight-manager 现有 OTP**:现有 OTP 是 in-memory store + tenant-bound,无法跨进程访问且绑 tenant。自包含 JWT 用共享 `jwt_secret` 验签,无需跨服务 HTTP 调用,docupipe-manager 启动不依赖 hindsight-manager 在线。

## 实现顺序建议

供后续 writing-plans 参考:

1. **项目骨架**:pyproject、目录、Settings、main.py + lifespan、Alembic 初始迁移、Dockerfile、docker-compose
2. **数据模型**:三张表 + 四个 ENUM 的 SQLAlchemy 模型
3. **认证**:hindsight-manager 的 SSO 端点 + docupipe-manager 的 `/auth/sso` + dependencies
4. **CredentialService + 设备流**:dws 集成、SM4 加密入库、UI 凭证页
5. **RunnerService**:subprocess 编排、临时 HOME、日志捕获、取消支持
6. **SchedulerService**:APScheduler + cron 注册 + 重载
7. **Projects API + UI**:CRUD、YAML 编辑、立即触发
8. **Runs API + UI**:列表、详情、日志查看、取消
9. **统计仪表板**:全局 banner + stats 端点
10. **集成测试**:localdrive 真跑一次

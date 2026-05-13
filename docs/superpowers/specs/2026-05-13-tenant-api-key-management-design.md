# 租户 API Key 管理功能设计

## 概述

完善现有 API Key 管理的前端交互，在 Dashboard 租户卡片内展开 API Key 管理区域，支持创建、复制、删除操作。后端 API 无需改动。

## 现状

- 后端：API Key CRUD 接口已完整（POST/GET/DELETE on `/tenants/{tenant_id}/api-keys`）
- 前端：Dashboard 有租户卡片，API Keys 全局页面存在但交互是占位状态
- 缺失：前端创建、复制、删除 API Key 的实际交互功能

## 设计

### 交互流程

1. Dashboard 每个租户卡片底部增加"API Keys"按钮
2. 点击按钮，卡片下方展开 API Key 管理区域
3. 展开时调用 `GET /tenants/{tenant_id}/api-keys` 加载列表
4. 同一时间只展开一个租户的 API Key 区域（展开新的自动折叠旧的）

### API Key 列表

每行显示：
- 名称
- Key 前缀（`hsm_abc...`）
- 创建时间
- 最后使用时间
- 操作按钮
  - 系统 Key：显示"系统"标签，无删除按钮
  - 用户 Key：显示复制前缀按钮 + 删除按钮

### 创建 API Key

1. 点击"创建 API Key"按钮，弹出模态框
2. 模态框内输入 Key 名称
3. 确认创建，调用 `POST /tenants/{tenant_id}/api-keys`
4. 创建成功后模态框切换为结果展示：
   - 显示完整 API Key
   - 复制按钮（可多次复制）
   - 警告提示："关闭后无法再次查看完整 Key"
5. 关闭模态框，新 Key 出现在列表中

### 删除 API Key

1. 点击删除按钮，弹出确认对话框
2. 确认后调用 `DELETE /tenants/{tenant_id}/api-keys/{key_id}`
3. 从列表中移除该 Key

### 空状态

没有用户 Key 时显示引导文案和创建按钮。

## 文件改动

### `templates/dashboard.html`

- 租户卡片底部增加"API Keys"按钮
- 每个卡片后增加展开区域容器 `<div id="api-keys-{tenant_id}" class="api-keys-panel" style="display:none">`
- 页面底部增加创建 API Key 模态框 HTML

### `static/app.js`

新增函数：
- `toggleApiKeys(tenantId)` — 展开/折叠 API Key 列表，展开时加载，折叠时清空
- `loadApiKeys(tenantId)` — 调用 GET 接口，渲染列表 HTML
- `showCreateKeyModal(tenantId)` — 打开创建模态框，重置表单状态
- `createApiKey(tenantId)` — 提交创建请求，成功后切换模态框为结果展示
- `revokeApiKey(tenantId, keyId)` — 确认删除后调用 DELETE 接口，从列表移除
- `copyKey(text)` — 复制文本到剪贴板，显示成功提示

### `static/style.css`

新增样式：
- `.api-keys-panel` — 展开区域容器
- `.api-key-item` — 列表行
- `.api-key-badge-system` — 系统 Key 标签
- `.api-key-modal-result` — 创建结果展示区域
- `.api-key-empty` — 空状态样式
- 展开动画过渡

## 不改动的文件

- 后端 Python 代码（API 接口已完整）
- 数据模型（ApiKey 模型已满足需求）
- 数据库迁移
- `templates/api_keys.html`（旧全局页面，本次不处理）

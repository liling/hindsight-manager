# 共享记忆库（成员管理 UI）设计

## 背景与范围

"共享记忆库"指：将一个 tenant（即 UI 中的"记忆库"）共享给同 tenant 之外的平台用户，使其以 owner 或 member 身份访问该记忆库。

### 现状

- **后端已就绪**：`/tenants/{id}/members` 已提供完整的 GET / POST / DELETE / PATCH 能力，支持 owner/member 二级角色。
- **前端缺失**：dashboard 页面对成员管理完全没有 UI 入口；owner 无法在界面内邀请/移除他人；非 owner 的 member 无法查看还有谁有访问权限。

### 本次范围

**纯前端 UI 暴露现有后端能力**，不改动后端权限模型、不引入新角色、不做邀请链接机制。

### 明确不做（YAGNI）

- 不新增 reader 等只读角色（继续 owner/member）
- 不做邀请链接 / token 机制（仍要求被邀请方已注册，靠用户名添加）
- 不做跨 tenant 数据共享（一个记忆库的 RAG 结果不会被另一个 tenant 检索到）
- 不做单 tenant 多 bank 拆分

## 架构总览

纯前端增量，**后端零改动**。

```
dashboard.html                      app.js                            后端
  tenant 卡片                         toggleMembers()                   (无变更)
   ├─ [进入控制台]                     ├─ GET  /tenants/{id}/members
   ├─ [API Keys]                      ├─ POST /tenants/{id}/members
   ├─ [成员]   ← 新按钮                ├─ DEL  /tenants/{id}/members/{uid}
   └─ [删除]                          └─ PATCH/tenants/{id}/members/{uid}
  members-panel-{id}  ← slide-out
```

### 核心约束

- owner 与 member 都看到"成员"按钮；member 的面板是只读视图（无添加/移除/改角色控件）。
- 复用 `.api-keys-panel` 的 slide-out 视觉与交互模式；同一时刻只能有一个 slide-out 面板展开（API Keys 与 members 互斥）。
- 列表加载、增删改成功后均重新 GET 刷新。

## 涉及文件

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `hindsight_manager/templates/dashboard.html` | 编辑 | 在 API Keys 按钮旁新增"成员"按钮；每个 tenant 卡片下新增 `<div id="members-panel-{id}">` 容器。按钮对 owner 和 member 都渲染（不再限于 owner 块）。 |
| `hindsight_manager/static/app.js` | 编辑 | 新增 `toggleMembers / renderMembersPanel / addMember / removeMember / changeMemberRole`；将 `_activeApiKeysTenantId` 重构为 `_activePanelTenantId`（带 panel type），统一管理 API Keys 与 members 面板的互斥展开。 |
| `hindsight_manager/static/style.css`（或当前内联样式所在文件） | 编辑 | 复用 `.api-keys-panel` 样式到 `.members-panel`；新增 `.role-badge`、`.member-row`、`.member-actions` 等少量类。 |
| `tests/test_members_api.py` | 新建 | 烟雾测试覆盖 GET 权限（owner/member/非成员）、POST 校验（404/409/403）、DELETE/PATCH 403。 |
| `hindsight_manager/api/members.py`、models、migrations | **零改动** | — |

## 数据流

### 初次进入 dashboard

- `GET /tenants` 渲染 tenant 卡片列表（已有逻辑，不变）。
- 每个 `members-panel-{id}` 渲染为空容器，等待按钮点击。

### 点击"成员"按钮（owner 或 member）

```
toggleMembers(tenantId)
  ├─ 如本卡片面板已展开 → 收起，结束
  ├─ 如其他卡片有面板展开（API Keys 或 members） → 先收起那个
  └─ 展开本卡片 members-panel
       └─ renderMembersPanel(tenantId, currentRole)
            ├─ fetch GET /tenants/{id}/members
            ├─ 渲染成员行：用户名 + 角色徽章（owner/member）
            ├─ 若 currentRole === 'owner':
            │    ├─ 每行（自己除外）追加 [改角色]下拉 + [移除]按钮
            │    └─ 底部追加"添加成员"表单（用户名 + 角色下拉 + 提交）
            └─ 若 currentRole === 'member': 纯只读列表
```

### owner 操作

- **添加成员**：表单提交 → `POST /tenants/{id}/members {username, role}` → 成功后 `renderMembersPanel` 刷新；失败按 detail 显示内联错误。表单的角色下拉默认 `member`（owner 通过共享授予的情况罕见，需主动改选）。
- **改角色**：下拉变更 → 立即 `PATCH /tenants/{id}/members/{user_id} {role}` → 刷新。
- **移除成员**：点 [移除] → `confirm("确定移除用户 X？")` → `DELETE /tenants/{id}/members/{user_id}` → 刷新。

### owner 自降级后的视图同步

owner 把自己 PATCH 为 member 后，当前面板的 `currentRole` 已过期。处理方式：PATCH 成功后整页 `window.location.reload()`，重新拉 `/tenants` 渲染卡片（currentRole 从服务端模板重新注入）。这避免在前端手动维护角色状态机的复杂度。

### 约束

- owner 不能移除自己：UI 隐藏自己行的 [移除] 按钮（后端不动，避免范围扩大）。
- owner 把自己降级为 member：UI 允许，但 `confirm("你将失去管理权限，确定？")` 二次确认。
- 最后一个 owner 不允许降级或移除（避免无人管理）：UI 计算当前 owner 数，仅 1 时禁用相应控件并显示提示。

## 错误处理

| 场景 | HTTP | UI 反馈 |
|---|---|---|
| 用户名不存在 | 404 `User not found` | 添加表单下方红字："找不到该用户" |
| 已是成员 | 409 `User is already a member` | 添加表单下方："该用户已是成员" |
| 非 owner 调增删改 | 403 `Owner access required` | 防御性 `alert("无权限")`（UI 理论上不向 member 暴露控件，此处兜底） |
| 网络/5xx | — | `alert("网络错误")`（沿用 `createTenant` 等现有模式） |
| 列表加载失败 | — | 面板内显示"加载失败，[重试]"链接 |
| 移除自己 / 最后一个 owner 降级或移除 | — | UI 层阻止，不发请求 |

### 约定

- 不引入 toast 库；沿用现有 `alert()` + 表单内联错误提示。
- `confirm()` 用于破坏性操作（移除成员、owner 自降级），与 `deleteTenant` 的 confirm 模式一致。

## 测试策略

### 后端烟雾测试（`tests/test_members_api.py`）

后端代码虽不改，但之前 0 覆盖、UI 完全依赖，必须补上：

| 用例 | 验证点 |
|---|---|
| `test_list_members_as_owner` | owner GET 返回完整列表，含自己 |
| `test_list_members_as_member` | member GET 200，可见他人 |
| `test_list_members_as_non_member` | 非 member GET 404 |
| `test_add_member_by_owner` | POST 201，列表多一人 |
| `test_add_member_by_member_forbidden` | member POST → 403 |
| `test_add_nonexistent_user` | POST 不存在用户名 → 404 |
| `test_add_duplicate_member` | POST 已成员 → 409 |
| `test_remove_member_by_owner` | DELETE 204，列表少一人 |
| `test_remove_member_by_member_forbidden` | member DELETE → 403 |
| `test_change_role_by_owner` | PATCH 角色变更生效 |
| `test_change_role_by_member_forbidden` | member PATCH → 403 |

测试风格沿用 `tests/test_integration.py`（async + 现有 mock fixture）。

### 前端

- 项目当前 0 前端自动化测试，本次不引入。
- 改用手动验证清单（实施与 review 时对照）：
  1. owner 看到"成员"按钮、点击后面板出现，控件齐全
  2. owner 添加新成员（合法用户名）→ 列表实时刷新
  3. owner 添加不存在用户名 → 出现"找不到该用户"
  4. owner 添加已是成员的用户 → 出现"该用户已是成员"
  5. owner 改其他成员角色 → 列表立即反映
  6. owner 移除其他成员 → confirm 后刷新
  7. owner 自己行的 [移除] 按钮不出现
  8. owner 自降级 → 弹 confirm → 确认后整页刷新为 member 只读视图
  9. 仅剩 1 个 owner 时，降级/移除被禁用且显示提示
  10. member 进入面板：只读列表，无任何改/删/加控件
  11. 切换到另一个 tenant 的 API Keys 面板时，members 面板自动收起（反之亦然）
  12. 列表加载失败时显示"加载失败，[重试]"

## 非目标 / 未来扩展

- 邀请链接 / 外部邮件邀请
- reader 只读角色
- 跨 tenant 数据共享（一个 tenant 的 RAG 查询检索另一个 tenant 的数据）
- 成员操作审计日志（当前 `audit_log` 已有架构，未来可接入）

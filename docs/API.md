# 包合规 - API 文档

## 基础信息

- **Base URL**: `http://localhost:8000`
- **Content-Type**: `application/json`（除文件上传外）
- **认证方式**: Bearer Token

---

## 认证

所有 API 请求（除 `/health` 和 `/api/auth/login`、`/api/auth/register`）需要在 Header 中携带 Token：

```
Authorization: Bearer <token>
```

### 获取 Token

- 通过 `/api/auth/login` 登录获取
- 通过 `/api/auth/register` 注册获取
- Token 有效期：8 小时（由 `access_token_expire_minutes` 配置）

---

## 通用错误格式

所有 API 在发生错误时返回：

```json
{
  "detail": "错误描述信息"
}
```

HTTP 状态码：

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 / Token 过期 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 409 | 资源冲突（如用户名已存在） |
| 500 | 服务端内部错误 |

---

## 1. 健康检查

### `GET /health`

无需认证。

**响应**:
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## 2. 认证 `api/auth`

### `POST /api/auth/login`

用户登录，返回 JWT Token。

**请求体**:
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**响应** (200):
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "user_id": 1,
  "username": "admin",
  "role": "admin",
  "company": "包合规开发团队"
}
```

**错误** (401):
```json
{ "detail": "用户名或密码错误" }
```

**错误** (403):
```json
{ "detail": "账户已被停用" }
```

**开发默认账户**:
| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | admin |
| user | user123 | user |

---

### `POST /api/auth/register`

用户注册，自动创建账号并返回 JWT Token。

**请求体**:
```json
{
  "username": "newuser",
  "password": "password123",
  "company": "测试招标公司",
  "email": "user@example.com"
}
```

**响应** (200):
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "user_id": 3,
  "username": "newuser",
  "role": "user",
  "company": "测试招标公司"
}
```

**错误** (409):
```json
{ "detail": "用户名已存在" }
```

---

### `GET /api/auth/me`

获取当前登录用户信息。

**响应** (200):
```json
{
  "user_id": 1,
  "username": "admin",
  "role": "admin",
  "company": "包合规开发团队",
  "email": "admin@baohegui.dev"
}
```

---

## 3. 文件上传 `api/upload`

### `POST /api/upload/`

上传招标文件（PDF/DOCX）。

**限制**:
- 支持格式：`.pdf`、`.docx`
- 最大文件大小：50 MB
- 最大页数：无限制

**请求**: `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | PDF 或 DOCX 文件 |

**响应** (200):
```json
{
  "file_id": "a1b2c3d4-...",
  "db_id": 1,
  "filename": "招标文件.pdf",
  "page_count": 45,
  "sections": {
    "招标公告": "第一章 招标公告\n...",
    "招标范围": "第二章 招标范围\n...",
    "资格要求": "第三章 资格要求\n...",
    "评审办法": "第四章 评审办法\n...",
    "投标须知": "第五章 投标须知\n..."
  }
}
```

`sections` 的 key 为归一化后的章节名称（招标公告、招标范围、资格要求、评审办法、投标须知），value 为对应章节的文本内容。

**错误** (400):
```json
{ "detail": "不支持的文件格式: txt，仅支持 pdf, docx" }
```
```json
{ "detail": "文件大小超过限制 (50MB)" }
```
```json
{ "detail": "文件解析失败: ..." }
```

**错误** (500):
```json
{ "detail": "文件存储失败: ..." }
```

---

## 4. 合规检查 `api/check`

### `POST /api/check/{file_id}`

对已上传的文件执行双引擎合规检查。

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| file_id | int | 上传时返回的 `db_id` |

**执行流程**:
1. 规则引擎检查（章节完整性、关键字、禁用词）
2. 大模型语义引擎检查（排他性、倾向性、隐性壁垒）
3. 双引擎结果融合、去重、评分

**响应** (200):
```json
{
  "report_id": 1,
  "total_score": 72.5,
  "total_violations": 5,
  "high_risk_count": 2,
  "medium_risk_count": 2,
  "low_risk_count": 1,
  "section_score": 80.0,
  "keyword_score": 70.0,
  "forbidden_score": 60.0,
  "semantic_score": 80.0,
  "llm_model_used": "mock",
  "llm_tokens_used": 0,
  "llm_cost_yuan": 0.0,
  "llm_error": null
}
```

**错误** (404):
```json
{ "detail": "文件不存在" }
```

**错误** (400):
```json
{ "detail": "文件解析失败: ..." }
```

---

## 5. 报告 `api/report`

### `GET /api/report/{report_id}`

获取合规报告的完整 JSON 数据。

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| report_id | int | 检查后返回的 `report_id` |

**响应** (200): `ComplianceReport` 完整对象

```json
{
  "file_name": "招标文件.pdf",
  "check_time": "2026-06-02 16:30:00",
  "total_score": 72.5,
  "section_score": 80.0,
  "keyword_score": 70.0,
  "forbidden_score": 60.0,
  "semantic_score": 80.0,
  "rule_violations": [
    {
      "rule_id": "CH-001",
      "rule_type": "chapter_required",
      "description": "缺少必备章节：投标须知",
      "location": null,
      "text": null,
      "risk_level": "high",
      "suggestion": "请补充投标须知章节",
      "platform_codes": [{"platform": "广东省公共资源交易平台", "code": "PT-CH-01"}],
      "law_ref": "《招标投标法》第十九条",
      "weight": 25.0
    }
  ],
  "llm_violations": [
    {
      "type": "exclusivity",
      "section": "资格要求",
      "text": "投标人须为本市注册企业",
      "risk_level": "high",
      "reason": "地域限制条款，可能构成以不合理的条件限制潜在投标人",
      "suggestion": "删除地域限制要求，或提供合理合法的说明",
      "law_ref": "《招标投标法实施条例》第三十二条",
      "weight": 30.0
    }
  ],
  "total_violations": 5,
  "high_risk_count": 2,
  "medium_risk_count": 2,
  "low_risk_count": 1,
  "llm_model_used": "mock",
  "llm_tokens_used": 0,
  "llm_cost_yuan": 0.0,
  "llm_error": null,
  "dedup_cross_engine": 1,
  "dedup_intra_engine": 0,
  "rule_count": 2
}
```

**错误** (404):
```json
{ "detail": "报告不存在" }
```

---

### `GET /api/report/{report_id}/pdf`

下载合规报告的 PDF 版本。

**响应**:
- Content-Type: `application/pdf`
- Content-Disposition: `attachment; filename="baohegui_report_{report_id}.pdf"`

**错误** (404):
```json
{ "detail": "报告不存在" }
```

---

### `GET /api/report/list/`

列出最近的合规报告。

**查询参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| limit | int | 否 | 20 | 返回记录数上限 |

**响应** (200):
```json
[
  {
    "id": 1,
    "file_id": 1,
    "total_score": 72.5,
    "violation_count": 5,
    "created_at": "2026-06-02T16:30:00+00:00"
  }
]
```

---

## 6. 规则管理 `api/rules`

### 引擎状态

#### `POST /api/rules/reload`

热加载规则文件，无需重启服务。

**响应** (200):
```json
{
  "message": "规则已重新加载",
  "rule_count": 42
}
```

**错误** (500):
```json
{ "detail": "规则加载失败: ..." }
```

---

#### `GET /api/rules/engine/status`

查看规则引擎当前状态。

**响应** (200):
```json
{
  "total": 42,
  "by_type": {
    "chapter_required": 5,
    "keyword_required": 12,
    "forbidden": 20,
    "format_required": 5
  }
}
```

---

### 平台规则 CRUD

#### `GET /api/rules/platform/list`

列出平台规则，支持搜索和筛选。

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| enabled_only | bool | 否 | 仅返回启用的规则（默认 false） |
| search | string | 否 | 按规则 ID 或描述搜索 |
| platform | string | 否 | 按平台名称筛选 |

**响应** (200):
```json
{
  "total": 35,
  "rules": [
    {
      "rule_id": "CH-001",
      "platform": "广东省公共资源交易平台",
      "platform_code": "PT-CH-01",
      "rule_type": "chapter_required",
      "target": "投标须知",
      "mandatory": true,
      "description": "招标文件必须包含投标须知章节",
      "version": "1.0",
      "effective_date": "2025-01-01",
      "enabled": true,
      "category": "platform"
    }
  ],
  "platforms": ["广东省公共资源交易平台", "自定义"]
}
```

---

#### `GET /api/rules/platform/{rule_id}`

获取单条平台规则详情。

**响应** (200):
```json
{
  "rule_id": "CH-001",
  "platform": "广东省公共资源交易平台",
  "platform_code": "PT-CH-01",
  "rule_type": "chapter_required",
  "target": "投标须知",
  "mandatory": true,
  "description": "招标文件必须包含投标须知章节",
  "version": "1.0",
  "effective_date": "2025-01-01",
  "enabled": true,
  "category": "platform"
}
```

**错误** (404):
```json
{ "detail": "规则不存在" }
```

---

#### `POST /api/rules/platform`

创建新平台规则。

**请求体**:
```json
{
  "rule_id": "CUSTOM-001",
  "platform": "自定义",
  "platform_code": "",
  "rule_type": "forbidden",
  "target": "评分条款",
  "mandatory": true,
  "description": "评分标准不得含有倾向性条款",
  "version": "1.0",
  "effective_date": "2026-01-01",
  "enabled": true,
  "category": "custom"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| rule_id | string | 是 | 规则唯一标识 |
| platform | string | 是 | 平台名称 |
| platform_code | string | 是 | 平台规则代码 |
| rule_type | string | 否 | 规则类型（默认 "unknown"） |
| target | string | 否 | 规则目标/章节 |
| mandatory | bool | 否 | 是否强制（默认 true） |
| description | string | 否 | 规则描述 |
| version | string | 否 | 版本号（默认 "1.0"） |
| effective_date | string | 否 | 生效日期 |
| enabled | bool | 否 | 是否启用（默认 true） |
| category | string | 否 | 分类（默认 "platform"） |

**响应** (200):
```json
{
  "message": "规则已创建",
  "rule": { ... }
}
```

**错误** (400):
```json
{ "detail": "规则 ID 已存在" }
```

---

#### `PUT /api/rules/platform/{rule_id}`

更新平台规则。请求体中的所有字段均为可选，仅传入需要更新的字段。

**请求体** (部分更新):
```json
{
  "description": "更新后的规则描述",
  "enabled": false
}
```

**响应** (200):
```json
{
  "message": "规则已更新",
  "rule": { ... }
}
```

**错误** (400):
```json
{ "detail": "规则不存在" }
```

---

#### `DELETE /api/rules/platform/{rule_id}`

删除平台规则。

**响应** (200):
```json
{ "message": "规则已删除" }
```

**错误** (404):
```json
{ "detail": "规则不存在" }
```

---

#### `POST /api/rules/platform/{rule_id}/toggle`

切换规则的启用/停用状态。

**响应** (200):
```json
{
  "message": "规则已启用",
  "enabled": true
}
```

**错误** (404):
```json
{ "detail": "规则不存在" }
```

---

### 批量导入

#### `POST /api/rules/import`

批量导入规则。

**请求体**:
```json
{
  "rules": [
    {
      "rule_id": "IMP-001",
      "platform": "广东省公共资源交易平台",
      "rule_type": "forbidden",
      "description": "..."
    }
  ]
}
```

**响应** (200):
```json
{
  "imported": 1,
  "skipped": 0,
  "errors": []
}
```

---

### 同步管理

#### `GET /api/rules/sync/status`

同步状态概览。

**响应** (200):
```json
{
  "total_rules": 35,
  "enabled_rules": 30,
  "platforms": ["广东省公共资源交易平台"],
  "rule_engine_loaded": 42,
  "available_platforms": ["广东省公共资源交易平台", "四川省公共资源交易平台"]
}
```

---

#### `POST /api/rules/sync/run`

手动触发平台规则同步。

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| platform | string | 是 | 平台名称 |

**响应** (200):
```json
{
  "status": "success",
  "new_rules": 3,
  "updated_rules": 1,
  "errors": [],
  "retry_count": 0,
  "version": "2026-06-02T16:25:00"
}
```

同步状态枚举值：`success`、`failed`、`partial`

---

#### `GET /api/rules/sync/history`

获取最近的同步记录（最多 20 条）。

**响应** (200):
```json
[
  {
    "id": "SYNC-20260602162500-0",
    "platform": "广东省公共资源交易平台",
    "status": "success",
    "started_at": "2026-06-02 16:25:00",
    "finished_at": "2026-06-02 16:25:05",
    "new_rules": 3,
    "updated_rules": 1,
    "errors": [],
    "retry_count": 0,
    "version": "2026-06-02T16:25:00"
  }
]
```

---

#### `GET /api/rules/sync/diff`

查看与指定平台的规则差异。

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| platform | string | 是 | 平台名称 |

**响应** (200):
```json
{
  "platform": "广东省公共资源交易平台",
  "diffs": [
    {
      "rule_id": "NEW-001",
      "change_type": "new",
      "description": "新增规则描述"
    }
  ]
}
```

---

## 7. 使用统计 `api/stats`

### `GET /api/stats/dashboard`

管理员看板数据。

**权限要求**: 需要认证（任意角色均可访问）。

**响应** (200):
```json
{
  "rules": {
    "total": 42,
    "by_type": {
      "chapter_required": 5,
      "keyword_required": 12,
      "forbidden": 20,
      "format_required": 5
    },
    "chapter_required": 5,
    "keyword_required": 12,
    "forbidden": 20,
    "format_required": 5
  },
  "llm": {
    "total_calls": 15,
    "total_tokens": 45000,
    "total_cost": 0.0,
    "success_rate": 0.93,
    "avg_tokens_per_call": 3000,
    "calls_by_model": {
      "mock": 15
    },
    "recent_calls": [
      {
        "model": "mock",
        "tokens": 3000,
        "duration": 0.05,
        "success": true,
        "timestamp": "2026-06-02T12:00:00"
      }
    ]
  },
  "risk_distribution": {
    "high": 8,
    "medium": 24,
    "low": 10
  },
  "industries": ["通用", "建筑工程", "IT", "医疗"]
}
```

---

## 模型枚举值

### 规则类型 (rule_type)

| 值 | 说明 |
|---|------|
| `chapter_required` | 必需章节检查 |
| `keyword_required` | 必需关键字检查 |
| `forbidden` | 禁用词检查 |
| `format_required` | 格式要求检查 |
| `semantic` | 语义规则 |

### 风险等级 (risk_level)

| 值 | 说明 |
|---|------|
| `high` | 高风险（可能被平台直接拦截） |
| `medium` | 中风险 |
| `low` | 低风险（建议优化） |

### 文件状态 (status)

| 值 | 说明 |
|---|------|
| `uploaded` | 已上传 |
| `parsing` | 解析中 |
| `checking` | 检查中 |
| `completed` | 已完成 |
| `failed` | 失败 |

### 同步状态

| 值 | 说明 |
|---|------|
| `idle` | 空闲 |
| `running` | 运行中 |
| `success` | 成功 |
| `failed` | 失败 |
| `partial` | 部分成功 |

### 用户角色 (role)

| 值 | 说明 |
|---|------|
| `admin` | 管理员（可管理规则） |
| `user` | 普通用户 |

---

## 快速参考

```bash
# 健康检查
curl http://localhost:8000/health

# 登录
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 上传文件（获取 TOKEN 后替换）
TOKEN="eyJhbGci..."
curl -X POST http://localhost:8000/api/upload/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@招标文件.pdf"

# 执行合规检查
curl -X POST http://localhost:8000/api/check/1 \
  -H "Authorization: Bearer $TOKEN"

# 获取报告
curl http://localhost:8000/api/report/1 \
  -H "Authorization: Bearer $TOKEN"

# 下载 PDF 报告
curl -O http://localhost:8000/api/report/1/pdf \
  -H "Authorization: Bearer $TOKEN"
```

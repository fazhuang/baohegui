# 用户注册 & 邮件校验 & 团队模块 — hlgs 可复用资产分析

## 1. 用户模型 (User)

hlgs 的 UserModel 是一个完整的自注册 + 邮箱验证系统：

```python
# users 表 — 13 字段
class UserModel:
    email: str(255)                   # 唯一邮箱
    password_hash: str(255)           # bcrypt 哈希
    display_name: str(100)            # 显示名称
    email_verified: bool              # 邮箱验证状态
    verification_code: str(6)         # 6位数字验证码
    verification_code_expires: DateTime # 30分钟过期
    password_reset_token: str(64)     # 密码重置令牌
    password_reset_expires: DateTime  # 1小时过期
    is_active: bool                   # 账户启用/禁用
    is_admin: bool                    # 管理员标志
```

### 核心亮点
1. **bcrypt 密码哈希**：`bcrypt.hashpw` + `bcrypt.gensalt()`，避免撞库
2. **6位数字验证码**：`random.choices(string.digits, k=6)`，30分钟有效期
3. **密码重置令牌**：`secrets.token_urlsafe(32)`，1小时有效期，验证时不暴露邮箱是否存在
4. **管理员自修复**：`authenticate_user` 内置白名单逻辑（admin@gansu.com / gansu2026），自动创建或修复管理员账户

---

## 2. 邮件服务 (Email)

### 架构设计
```
Sender (统一入口)
  ├── Resend API（优先）─ re_xxx API Key
  │    └── HTTP POST → https://api.resend.com/emails
  └── SMTP（回退）─ starttls + 465/587
       └── smtplib.SMTP → EmailMessage
```

### 配置优先级
```
凭据库 (credential_vault) > settings 环境变量 > localhost(不发送)
```

### 8 种邮件类型
| 函数 | 用途 |
|------|------|
| `send_verification_email` | 注册验证码（6位数字，30分钟有效） |
| `send_welcome_email` | 注册成功后欢迎 |
| `send_password_reset_email` | 密码重置链接（含 token） |
| `send_quota_warning_email` | 额度即将用完预警 |

### 邮件 HTML 模板设计
所有邮件使用内联 CSS，品牌标识统一：
- 灰色背景 `#f0f2f6` + 白色卡片 `#fff` + 圆角 `border-radius:12px`
- 标题：`包合规` (APP_BRAND)
- 主按钮：`#3D5AFE` 蓝色 + `padding:12px 24px`
- 验证码：`#EEF2FF` 背景 + `font-size:32px;letter-spacing:8px` 等宽字体

---

## 3. 用户服务完整流程

### 注册流程
```
POST /api/auth/register
  → 频率检查（IP级别，30次/小时）
  → 重复邮箱检查 → 409 ConflictError
  → bcrypt.hashpw(password) + 生成6位验证码
  → 插入 DB
  → 处理邀请码返利（失败不影响注册）
  → 同步发送验证邮件
  → 记录审计日志 AuditLogModel
  → 返回 {message, email}
```

### 邮箱验证流程
```
POST /api/auth/verify-email {email, code}
  → 查找用户
  → 检查 email_verified 状态（已认证直接返回）
  → 比对 verification_code
  → 检查过期（30分钟）
  → 设置 email_verified=True, verification_code=None
  → 异步线程发送欢迎邮件
```

### 密码重置流程
```
POST /api/auth/forgot-password {email}
  → 频率检查（IP级别，10次/小时）
  → 查找用户（不存在返回 404 但信息模糊）
  → secrets.token_urlsafe(32) 生成令牌
  → 异步线程发送重置邮件

GET /api/auth/reset-password/verify?token=xxx
  → 验证令牌有效期（1小时）
  → 返回脱敏邮箱: "t***@***.com"

POST /api/auth/reset-password {token, password}
  → 验证令牌 + 更新密码 + 清空令牌
```

### 管理员登录自修复
```python
# 当检测到 admin 登录时：
# 1. 如果 admin 用户不存在 → 自动创建
# 2. 如果 admin 用户存在但状态异常 → 自动修复
#    - 重置 is_admin=True
#    - 重置 is_active=True
#    - 重置 email_verified=True
#    - 重置 password_hash
```

---

## 4. 团队模块 (Team)

### 数据模型
```python
class TeamModel:
    name: str(100)        # 团队名称
    owner_id: FK(User)    # 创建者
    invite_code: str(8)   # 8位邀请码（大写字母+数字）

class TeamMemberModel:
    team_id: FK(Team)
    user_id: FK(User)
    role: str(20)         # owner | admin | member
```

### 核心逻辑
- 创建团队 → 创建者自动加入为 owner
- 邀请码生成：`secrets.choice(string.ascii_uppercase + string.digits, k=8)`
- join_team 检查：邀请码有效 + 用户未在团队中 → 以 member 角色加入
- get_user_teams：返回用户所有团队（含角色、成员数）

---

## 5. JWT 认证 (auth.py)

### Token 创建
```python
def create_access_token(data: dict, expires_delta=None) -> str:
    payload = data.copy()
    payload["exp"] = now + (expires_delta or 24h)
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")
```

### 双认证模式
```
get_token_data(token)
  ├── Entra ID 验证（如果 AZURE_ENTRA_ID_ENABLED）
  │    ├── OpenID 元数据获取
  │    ├── JWKS 签名密钥获取（1小时缓存）
  │    └── RS256/RS384/RS512 签名验证
  └── 本地 JWT 验证（HS256）
       └── jwt.decode(token, SECRET_KEY)
```

### get_current_user 装饰器
```python
CurrentUser = Annotated[UserModel, Depends(get_current_user)]
# 任何受保护路由：def my_route(user: CurrentUser):
```

---

## 6. 认证 Schema 设计

```python
UserRegisterRequest   # email + password(8-128) + display_name? + referral_code?
UserVerifyEmailRequest # email + code(6位)
UserLoginRequest      # email + password
UserProfile           # id + email + display_name + email_verified + is_admin + created_at
UserLoginResponse     # access_token + token_type + user(UserProfile)
```

---

## 7. 可复用资产清单

### P0 — 直接可迁移
| 资产 | 描述 | 工作量 |
|------|------|--------|
| bcrypt 密码哈希 + 验证 | 完整实现，直接用 | 0.2天 |
| 邮箱验证码生成 + 过期 | 6位数字+30分钟，直接用 | 0.2天 |
| 密码重置令牌系统 | token_urlsafe(32) + 脱敏显示，直接用 | 0.3天 |
| JWT 创建/验证 | HS256 + exp 过期，直接用 | 0.2天 |
| get_current_user 装饰器 | FastAPI Depends 模式，直接用 | 0.2天 |

### P1 — 需适配
| 资产 | 描述 | 工作量 |
|------|------|--------|
| 邮件发送双通道 | Resend API + SMTP 回退，需配环境变量 | 0.5天 |
| 邮件 HTML 模板 | 4种邮件模板（验证码/欢迎/重置/额度），内联 CSS | 0.5天 |
| 注册频率限制 | 基于 IP 的内存计数器，适合单机部署 | 0.3天 |
| 管理员自修复逻辑 | 硬编码白名单 → 需改为配置化 | 0.2天 |
| 团队邀请码系统 | 8位邀请码 + 加入逻辑，可直接移植 | 0.5天 |
| Entra ID 集成 | Azure AD JWKS 验证，如需企业 SSO | 1-2天 |

### P2 — 可选
| 资产 | 描述 | 工作量 |
|------|------|--------|
| 审计日志写入 | AuditLogModel 记录所有认证事件 | 0.5天 |
| 返利/推荐码系统 | 注册时处理邀请链接 | 1天 |

---

## 8. baohegui 集成建议

### 立即创建的文件
```
backend/app/models/user.py              — UserModel（13字段+bcrypt）
backend/app/models/team.py              — TeamModel + TeamMemberModel（可选）
backend/app/services/user_service.py    — 注册/验证/重置/登录
backend/app/services/email_service.py   — 双通道邮件发送（Resend + SMTP）
backend/app/core/auth.py                — JWT + get_current_user
backend/app/schemas/auth.py             — Pydantic schemas
backend/app/api/auth.py                 — 认证 API 路由
```

### 环境变量需新增
```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@baohegui.com
SMTP_PASSWORD=xxx
SMTP_FROM=noreply@baohegui.com
RESEND_API_KEY=re_xxx        # 可选，优先使用
EMAIL_BACKEND=smtp            # resend_api | smtp
SECRET_KEY=your-secret-key
JWT_EXPIRATION_MINUTES=1440
```

### 前端页面需新增
```
frontend/src/pages/Login.tsx
frontend/src/pages/Register.tsx
frontend/src/pages/ForgotPassword.tsx
frontend/src/pages/ResetPassword.tsx
frontend/src/pages/EmailVerify.tsx
frontend/src/pages/Profile.tsx
```

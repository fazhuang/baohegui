# 订阅管理 & SaaS 商业化模块 — hlgs 可复用资产分析

## 1. 订阅计划模型 (SubscriptionPlan)

```python
# subscription_plans 表
class SubscriptionPlanModel:
    name: str(100)                  # Free / Pro / Enterprise
    plan_id: str(50)                # Unique: free / pro / enterprise
    price_monthly: int              # 分 cent: 29900 = ¥299
    price_yearly: int               # 分 cent
    doc_limit: int                  # -1 = 无限
    compliance_limit: int           # 每月合规审查次数上限
    trial_days: int                 # 试用天数
    features: JSON                  # ["无限文书","AI审查",...]
    stripe_price_id_monthly: str    # Stripe 价格 ID
    stripe_price_id_yearly: str
    is_active: bool
```

### 预置三级计划
| 计划 | 价格(月/年) | 合规审查/月 | 文书 | 核心功能 |
|------|------------|-----------|------|---------|
| Free | ¥0 / ¥0 | 3次 | 10份 | 基础规则引擎、AI审查 |
| Pro | ¥299 / ¥2990 | -1(无限) | -1(无限) | 无线文书、AI审查、参数偏见检测、DOCX导出、优先支持 |
| Enterprise | 定制 | -1(无限) | -1(无限) | 专属规则定制、API接入、SSO、SLA保障 |

---

## 2. 用户订阅模型 (UserSubscription)

```python
# user_subscriptions 表
class UserSubscriptionModel:
    user_id: FK(User) unique
    tenant_id: FK(User) nullable     # 多租户支持（团队订阅）
    plan_id: str(50)                 # free | pro | enterprise
    tier_type: str(30)               # FREE_TRIAL | PAID_MONTHLY | PAID_YEARLY
    status: str(20)                  # trial | active | expired | canceled
    trial_started_at / trial_ends_at
    current_period_start / current_period_end
    docs_generated: int              # 本月已生成文书数
    compliance_checks_used: int      # 本月合规审查次数
    stripe_subscription_id / stripe_customer_id
```

---

## 3. 配额系统 (Quota)

### 配额检查逻辑
```python
def check_doc_quota(db, user_id):
    sub = get_user_subscription(db, user_id)
    if sub.doc_limit == -1:   return True  # 无限
    if sub.docs_generated < sub.doc_limit: return True
    raise QuotaExceededError("本月文书生成额度已用完")

def check_compliance_quota(db, user_id):
    sub = get_user_subscription(db, user_id)
    if sub.compliance_limit == -1: return True
    if sub.compliance_checks_used < sub.compliance_limit: return True
    raise QuotaExceededError("本月合规审查次数已用完")
```

### 月度重置
- `docs_generated` 和 `compliance_checks_used` 按月重置
- 每次操作后 `+= 1`
- 额度用完前发送预警邮件（80%触发）

---

## 4. 付费墙集成点

hlgs 的付费墙渗透在多个 API 层：

```python
# app/api/compliance_review.py
def check_compliance_access(db, user_id):
    sub = get_or_create_subscription(db, user_id)
    # 确定可访问性
    can_full_access = sub.plan_id != "free" or sub.status == "trial"
    # 免费用户只能看到前 3 条违规预览
    ...
```

### 合规审查付费分层
| 层级 | 可见内容 |
|------|---------|
| Free（未付费） | 前 3 条违规 + 摘要报告 |
| Free（试用中） | 完整报告 |
| Pro / Enterprise | 完整报告 + 详细修改建议 + 法规引用 |

---

## 5. 支付模型 (Payment)

```python
class PaymentModel:
    user_id: FK(User)
    subscription_id: FK(UserSubscription)
    amount: int                    # 分 cent
    currency: str = "cny"
    payment_method: str            # stripe | alipay | wechat
    stripe_payment_intent_id / stripe_invoice_id
    status: str                    # pending | succeeded | failed | refunded
    paid_at / refunded_at / receipt_url
```

---

## 6. API Key 模型 (Developer)

```python
class APIKeyModel:
    user_id: FK(User)
    name: str(100)
    key_hash: str(255)             # SHA256 哈希存储
    key_prefix: str(8)             # "sk-" + 前8位明文
    scopes: JSON                   # ["compliance.check","report.read"]
    rate_limit: int                # 每分钟请求上限
    last_used_at / expires_at
    is_active: bool
```

---

## 7. 推荐系统 (Referral)

```python
class ReferralCodeModel:           # 每个用户一个推荐码
    user_id: FK(User) unique
    code: str(8)                   # 8位大写字母+数字
    total_referrals: int

class ReferralModel:               # 推荐记录
    inviter_id: FK(User)
    invited_id: FK(User)
    status: str                    # pending | completed

class ReferralRewardModel:         # 奖励
    user_id: FK(User)
    reward_type: str               # credits | discount | cash
    reward_amount: int             # 分 cent
    is_granted: bool
```

---

## 8. 仪表盘聚合 (Member Dashboard)

`GET /api/member/dashboard` 返回：
```json
{
  "profile": { "display_name", "email", "email_verified", "created_at" },
  "projects": { "total", "by_status", "recent": [...] },
  "compliance": { "total_reports", "passed", "failed", "pass_rate", "monthly_trend": [...] },
  "referral": { "total_invites", "total_rewards", "code" }
}
```

---

## 9. 可复用资产清单

### P0 — 直接可迁移
| 资产 | 描述 | 工作量 |
|------|------|--------|
| `SubscriptionPlanModel` | 三级计划设计 + seed 数据 | 0.3天 |
| `UserSubscriptionModel` | 用户订阅状态 + 配额字段 | 0.3天 |
| 配额检查逻辑 | `check_doc_quota` / `check_compliance_quota` | 0.2天 |
| 付费墙中间件 | `check_compliance_access` 模式 | 0.3天 |
| 额度预警邮件 | 80%触发邮件提醒 | 0.2天 |

### P1 — 需适配
| 资产 | 描述 | 工作量 |
|------|------|--------|
| 支付集成 | Stripe + 支付宝 + 微信 | 3-5天 |
| API Key 管理 | SHA256 哈希 + 范围 + 限流 | 1-2天 |
| 推荐系统 | 邀请码 + 返利逻辑 | 1-2天 |
| 仪表盘聚合 API | 多表联查 + 月度趋势 | 1天 |
| 月度配额重置 | Cron job 或 惰性重置 | 0.5天 |

### P2 — 可选
| 资产 | 描述 | 工作量 |
|------|------|--------|
| Stripe Webhook | 支付事件回调处理 | 1-2天 |
| 发票管理 | 发票生成/下载 | 1天 |
| 多租户团队订阅 | tenant_id 订阅共享 | 2-3天 |

---

## 10. baohegui 集成建议

### 数据模型 (`backend/app/models/`)
```
backend/app/models/subscription.py  — SubscriptionPlan + UserSubscription
backend/app/models/payment.py       — Payment（可选）
```

### 服务层 (`backend/app/services/`)
```
backend/app/services/subscription_service.py — 订阅管理 + 配额检查
backend/app/services/quota_service.py        — 配额消费 + 月度重置
```

### API 路由 (`backend/app/api/`)
```
backend/app/api/subscription.py   — 订阅 API（查询/升级/取消）
backend/app/api/member.py         — 仪表盘聚合
```

### 合规引擎集成
```
backend/app/engine/ 中所有审查入口都需要注入配额检查
- rule_engine.py  → check_compliance_quota
- llm_engine.py   → check_compliance_quota
```

### 前端页面
```
frontend/src/pages/Pricing.tsx         — 定价页（Free/Pro/Enterprise 对比）
frontend/src/pages/Subscription.tsx    — 订阅管理（当前计划/升级/取消）
frontend/src/pages/Dashboard.tsx       — 仪表盘（用量统计 + 趋势图）
```

### 环境变量需新增
```
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

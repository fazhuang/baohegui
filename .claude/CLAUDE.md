# 包合规（baohegui）- 招标文件发布前合规自检系统

## 项目概述
包合规是一个面向招标代理机构和政府采购部门的招标文件发布前合规自检工具。
帮助用户在正式提交至公共资源交易平台前完成合规审查，降低平台拦截和返工风险。

## 核心用户
- 招标代理机构（中小型为主，10-30人团队）
- 政府采购业务部门

## 核心功能
1. 文件上传（PDF/Word，≤50MB）
2. 章节抽取与结构化（招标公告、招标范围、资格要求、评审办法、投标须知）
3. 双引擎合规审查
   - 规则引擎：章节完整性、关键字合规、禁用词检查
   - 大模型语义引擎：排他性检测、倾向性判断、隐性壁垒识别、质疑风险预判
4. 合规报告生成（含平台规则代码映射、法律风险预警、整改建议）

## 双引擎架构 → 升级为五层审查流水线
审查架构参考 hlgs（华招国际）项目并进行了增强，形成从"零成本预筛"到"确定性结论"的递进式审查链路：

**第 0 层：零 Token 路由审查**（待实现：`engine/routing.py`）
  - 仅通过预算金额、采购方式等结构化字段做快速判断
  - 输出绿/黄/红交通灯 + LLM 任务列表，零 LLM Token 消耗

**第 1 层：确定性规则引擎**（`engine/rule_engine.py`）
  - 支持 7 种规则类型：required, pattern_required, forbidden_pattern, numeric_range, date_interval, conditional, semantic_required
  - 支持条件表达式（AND/OR/NOT/比较运算），精准适配不同采购模式
  - 正文证据链定位（evidence_text + start_offset/end_offset）
  - 规则来源：rules/compliance_rules.json（40+条结构化规则，5大类：资格条件/评标标准/商务条款/程序合规/法规冲突）

**第 2 层：参数倾向性检测**（待实现：`engine/parameter_bias.py`）
  - 基于 558 个甘肃政府采购投诉案例提炼的 9 种违规模式
  - 核心检测：品牌锁定、厂家授权锁、组合参数整体指向性（最高级别的隐性排他）

**第 3 层：LLM 语义引擎**（`engine/llm_engine.py`）
  - 17 个隐含合规风险维度（AI-BRAND, AI-AUTH, AI-LAB, AI-PATENT, AI-COMBINE, AI-STD, AI-SCORE-VAGUE, AI-PRICE-WEIGHT, AI-SCORE-SUBJ, AI-QUAL-LEVEL, AI-QUAL-RESTRICT, AI-QUAL-CERT, AI-REJECT, AI-COMPLAINT, AI-SME, AI-CREDIT, AI-GREEN）
  - 三重校验：Schema 校验 → rule_id 合法性校验 → 法规依据校验 → 无证据降级为疑似风险

**第 4 层：解析质量评估**（`services/parser.py`）
  - 评估文档解析可信度对审查结论的影响
  - 状态：ok / text_layer / ocr / partial / failed

**汇总层：四路风险合并器**（待实现：`engine/fusion.py`）
  - 合并规则引擎、参数倾向性、AI 审查、解析质量四路结果
  - 输出：final_passed / final_risk_level / review_status / requires_human_review
  - 分组风险：confirmed（确定违规）/ high_risk（高风险）/ needs_review（待人工确认）/ advisory（提示关注）

### 复核状态机
```
auto_passed ──→ (结束)
auto_failed ──→ (等待人工复核)  
needs_review ──→ reviewed_passed ──→ (结束)
            ──→ reviewed_failed ──→ (结束)
```

## 产品边界
✅ 招标文件发布前合规自检
✅ 硬性规则+大模型语义双驱动
✅ 同步公共资源交易平台审查规则
✅ 合规报告生成与下载
✅ 基本权限管理与操作审计
✅ 用户注册登录+邮箱验证+密码重置
✅ 警示公告（违规案例通报）+ 政策法规模块
✅ 订阅管理（Free/Pro/Enterprise 三级计划 + 配额）
✅ Docker单机部署 / SaaS

❌ 投标文件分析与审查
❌ 为交易中心构建AI审查引擎
❌ 批量API对接、自动化流水线
❌ 质疑/投诉答复生成
❌ 完整的OA/ERP集成
❌ 分布式高可用集群、GPU推理

## 核心指标
- 单份文件审查时间 ≤ 3分钟
- 规则引擎准确率 ≥ 95%
- 大模型语义审查召回率 ≥ 85%
- 大模型误报率 ≤ 15%
- 平台拦截预测准确率 ≥ 90%

## 技术栈
- 后端: Python 3.13, FastAPI, SQLAlchemy, spaCy, WeasyPrint
- 前端: React 19, TypeScript, Vite, Ant Design
- 存储: PostgreSQL, MinIO (S3兼容)
- 大模型: API接口（国产大模型，如Qwen/DeepSeek）
- 部署: Docker Compose

## 目录结构
```
baohegui/
├── .claude/CLAUDE.md          # 项目上下文（本文件）
├── backend/                    # Python 后端
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── api/               # API 路由
│   │   │   ├── upload.py      # 文件上传
│   │   │   ├── check.py       # 合规检查
│   │   │   ├── report.py      # 报告
│   │   │   ├── rules.py       # 规则管理
│   │   │   ├── auth.py        # 用户认证（注册/登录/验证/重置密码）
│   │   │   ├── announcements.py  # 警示公告（违规案例通报）
│   │   │   ├── policies.py    # 政策法规模块
│   │   │   ├── member.py      # 会员仪表盘
│   │   │   └── subscription.py # 订阅管理 + 配额
│   │   ├── core/              # 核心配置
│   │   │   ├── config.py      # 配置管理
│   │   │   ├── security.py    # 认证权限（JWT + bcrypt）
│   │   │   ├── auth.py        # get_current_user 依赖注入
│   │   │   └── audit.py       # 审计日志
│   │   ├── engine/            # 合规引擎
│   │   │   ├── routing.py      # 第0层：零Token路由审查
│   │   │   ├── rule_engine.py  # 第1层：规则引擎（7种类型+条件表达式）
│   │   │   ├── parameter_bias.py  # 第2层：参数倾向性检测（9种违规模式）
│   │   │   ├── llm_engine.py   # 第3层：LLM语义引擎（17维隐含风险）
│   │   │   └── fusion.py       # 汇总层：四路风险合并器+复核路由
│   │   ├── models/            # 数据模型
│   │   │   ├── user.py        # 用户模型（email + bcrypt + 验证码 + 密码重置令牌）
│   │   │   ├── announcement.py # 警示公告模型（severity 四级分色）
│   │   │   ├── policy.py      # 政策法规模型（slug + 草稿/发布分离）
│   │   │   ├── subscription.py # 订阅计划 + 用户订阅状态 + 配额
│   │   │   └── project.py     # 项目模型
│   │   ├── services/          # 服务层
│   │   │   ├── parser.py      # 文档解析
│   │   │   ├── rule_sync.py   # 规则同步
│   │   │   ├── report_gen.py  # 报告生成
│   │   │   ├── user_service.py # 用户注册/验证/密码重置
│   │   │   ├── email_service.py # 双通道邮件（Resend API + SMTP）
│   │   │   ├── announcement_service.py  # 公告 CRUD + 全网采集合成
│   │   │   ├── policy_service.py        # 政策 CRUD + 全文检索 + slug
│   │   │   ├── subscription_service.py  # 订阅管理 + 配额检查
│   │   │   └── quota_service.py         # 配额消费 + 月度重置
│   │   └── db/                # 数据库
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   ├── components/
│   │   ├── services/api.ts
│   │   └── types/index.ts
│   ├── package.json
│   └── Dockerfile
├── rules/
│   ├── compliance_rules.json  # 结构化合规规则库（从 hlgs 提取，5大类40+条）
│   ├── base_rules.json
│   ├── platform_rules.json
│   ├── forbidden_words.json   # 禁用词库（融合 hlgs 模式，12大类50+模式）
│   ├── parameter_bias_rules.json  # 参数倾向性检测（558个投诉案例提炼）
│   ├── project_categories.json    # 项目分类+字段→规则映射
│   ├── industry/
│   ├── prompts/
│   │   ├── compliance_check.txt   # 主审查 Prompt（规则+17维AI ID+参数倾向）
│   │   ├── document_parse.txt     # 文档结构化解析 Prompt
│   │   └── exclusivity_check.txt  # 专项排他性检测 Prompt
│   └── versions/
├── docs/
│   ├── module-announcement-policy.md  # 警示公告+政策法规模块设计
│   ├── module-auth-email.md           # 用户注册+邮件校验模块设计
│   └── module-subscription.md         # 订阅管理+SaaS商业化设计
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## 关键规则路径
规则引擎的规则存储在 rules/ 目录下：
- rules/compliance_rules.json —— **结构化合规规则库（5大类40+条，从 hlgs 提取）**
- rules/base_rules.json —— 基础法规规则（章节完整性、关键字、格式等）
- rules/platform_rules.json —— 平台规则代码映射
- rules/forbidden_words.json —— **禁用词与违规模式库（12大类50+模式，融合 hlgs 模式）**
- rules/parameter_bias_rules.json —— **参数倾向性检测规则（基于558个投诉案例）**
- rules/project_categories.json —— **项目分类体系 + 字段→规则映射表**
- rules/industry/ —— 行业细分规则
- rules/prompts/ —— LLM Prompt 模板（compliance_check / document_parse / exclusivity_check）
- rules/manifest.json —— 规则清单
- rules/versions/ —— 规则版本管理

规则热加载：规则更新后无需重启服务，引擎会检测文件变化并自动重新加载。

## 规则引擎支持的规则类型
从 hlgs 提取并增强，支持 7 种规则类型：
| 类型 | 说明 | 示例规则 |
|------|------|---------|
| `required` | 必填字段非空 | R001 资质要求不得为空 |
| `pattern_required` | 正则正匹配（值必须包含） | R007 技术参数需包含指标/规格描述 |
| `forbidden_pattern` | 正则负匹配（值不得包含） | R101 不得出现"厂家授权""指定品牌" |
| `numeric_range` | 数值范围 | 预算金额范围校验 |
| `date_interval` | 日期区间 | 投标截止日期校验 |
| `conditional` | 条件表达式触发 | `budget > 400 AND evaluation_method IN ['询价']` |
| `semantic_required` | 语义关键词匹配 | 废标条件必须包含保证金/资质/文件关键词 |

条件表达式引擎支持 AND/OR/NOT/比较运算（==, !=, >=, <=, >, <）和 IN 运算符。

## 参考项目：hlgs（华招国际）
本项目审核模块的设计和规则资产大量借鉴了 hlgs 项目（`/Users/likeming/projects/hlgs`）：

### 审核引擎
- **规则库**：rules/compliance_rules.json 从 hlgs config/rules/*.json 提取并适配
- **禁用词库**：rules/forbidden_words.json 融合了 hlgs 全部 forbidden_pattern 模式
- **参数倾向性**：rules/parameter_bias_rules.json 移植自 hlgs config/rules/parameter_bias_rules.json
- **AI Prompt**：rules/prompts/compliance_check.txt 合并了 hlgs app/ai/prompts/compliance.txt 的 17 维隐含风险体系
- **架构设计**：五层审查流水线、四路风险合并器、复核状态机等架构模式均参考 hlgs
- **项目分类**：rules/project_categories.json 移植自 hlgs config/project_categories.json

### 业务模块
- **警示公告**：docs/module-announcement-policy.md — hlgs app/models/announcement.py + app/services/announcement_service.py
  - severity 四级分色系统（info/warning/danger/critical）
  - 全网通报采集合成（去重+自动入库）
- **政策法规**：docs/module-announcement-policy.md — hlgs app/models/policy.py + app/services/policy_service.py
  - 草稿/发布分离 + slug 自动生成
  - 全文检索（title/summary/content/interpretation 四字段）
- **用户注册+邮件**：docs/module-auth-email.md — hlgs app/models/user.py + app/services/user_service.py + email_service.py
  - bcrypt 密码哈希 + 6位数字验证码 + 密码重置令牌
  - 双通道邮件（Resend API → SMTP 回退）
  - 管理员自修复逻辑
- **订阅管理**：docs/module-subscription.md — hlgs app/models/subscription.py + subscription_service.py
  - Free/Pro/Enterprise 三级计划 + 配额系统
  - 付费墙中间件 + 月度重置

hlgs 的核心架构文件参考：
- app/rules/engine.py — 规则引擎（条件表达式求值器）
- app/services/risk_aggregator.py — 四路风险合并器
- app/services/review_service.py — 复核路由+状态机
- app/services/compliance_router.py — 零 Token 路由审查
- app/models/user.py — 用户模型（bcrypt + 验证码 + 密码重置）
- app/services/email_service.py — 邮件双通道（Resend + SMTP）
- app/models/subscription.py — 订阅 + 配额模型
- app/models/announcement.py — 公告模型（severity 分色）
- app/models/policy.py — 政策模型（slug + 草稿分离）

## 开发命令
```bash
# 后端（从 backend/ 目录）
uv sync
uv run uvicorn app.main:app --reload
uv run pytest

# 前端（从 frontend/ 目录）
npm install
npm run dev

# Docker 部署（从项目根目录）
docker compose up -d --build
```

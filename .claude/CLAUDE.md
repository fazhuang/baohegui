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
3. 五层审查流水线（路由→规则引擎→参数倾向→LLM语义→风险合并）
4. 合规报告生成（含平台规则代码映射、法律风险预警、整改建议）

## 五层审查流水线
审查架构参考 hlgs（华招国际）项目并进行了增强，形成从"零成本预筛"到"确定性结论"的递进式审查链路：

**第 0 层：零 Token 路由审查**（`backend/app/engine/routing.py`）
  - 仅通过预算金额、采购方式等结构化字段做快速判断
  - 输出绿/黄/红交通灯 + LLM 任务列表，零 LLM Token 消耗

**第 1 层：确定性规则引擎**（`backend/app/engine/rule_engine.py`）
  - 支持 7 种规则类型：required, pattern_required, forbidden_pattern, numeric_range, date_interval, conditional, semantic_required
  - 支持条件表达式（AND/OR/NOT/比较运算），精准适配不同采购模式
  - 正文证据链定位（evidence_matcher.py）
  - 规则来源：rules/compliance_rules.json（40+条结构化规则，5大类：资格条件/评标标准/商务条款/程序合规/法规冲突）

**第 2 层：参数倾向性检测**（`backend/app/engine/parameter_bias.py`）
  - 基于 558 个甘肃政府采购投诉案例提炼的 9 种违规模式
  - 核心检测：品牌锁定、厂家授权锁、组合参数整体指向性

**第 3 层：LLM 语义引擎**（`backend/app/engine/llm_engine.py`）
  - 17 个隐含合规风险维度
  - 三重校验：Schema 校验 → rule_id 合法性校验 → 法规依据校验 → 无证据降级为疑似风险

**第 4 层：解析质量评估**（`backend/app/services/parser.py`）
  - 评估文档解析可信度对审查结论的影响
  - 状态：ok / text_layer / ocr / partial / failed

**汇总层：四路风险合并器**（`backend/app/engine/fusion.py`）
  - 合并规则引擎、参数倾向性、AI 审查、解析质量四路结果
  - 输出：final_passed / final_risk_level / review_status / requires_human_review
  - 分组风险：confirmed（确定违规）/ high_risk（高风险）/ needs_review（待人工确认）/ advisory（提示关注）

**增强引擎模块**：
  - `platform_rules.py` — 平台规则加载与匹配
  - `semantic_chunking.py` — 语义分块，按章节语义边界切分文档
  - `shared_types.py` — 引擎间共享类型定义
  - `template_fingerprint.py` — 模板指纹检测，识别招标文件模板
  - `variable_marker.py` — 变量标记，识别可替换参数位

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
✅ 合规报告生成与下载（PDF + Excel）
✅ 基本权限管理与操作审计
✅ 用户注册登录+邮箱验证+密码重置
✅ 警示公告（违规案例通报）+ 政策法规模块
✅ 订阅管理（Free/Pro/Enterprise 三级计划 + 配额）
✅ Docker 单机部署 / Railway + Cloudflare Pages

❌ 投标文件分析与审查
❌ 为交易中心构建AI审查引擎
❌ 质疑/投诉答复生成
❌ 分布式高可用集群、GPU推理

## 核心指标
- 单份文件审查时间 ≤ 3分钟
- 规则引擎准确率 ≥ 95%
- 大模型语义审查召回率 ≥ 85%
- 大模型误报率 ≤ 15%
- 平台拦截预测准确率 ≥ 90%

## 技术栈
- 后端: Python 3.13, FastAPI, SQLAlchemy, spaCy, WeasyPrint
- 前端: React 19, TypeScript, Vite, Ant Design 5, zustand, React Router 7
- 存储: PostgreSQL, MinIO (S3兼容)
- 大模型: API接口（国产大模型，如Qwen/DeepSeek）
- 部署: Docker Compose / Railway + Cloudflare Pages
- 测试: vitest + @testing-library/react (前端), pytest (后端)

## 目录结构
```
baohegui/
├── .claude/CLAUDE.md              # 项目上下文（本文件）
├── backend/                        # Python 后端
│   ├── app/
│   │   ├── main.py                # FastAPI 入口
│   │   ├── api/                   # API 路由
│   │   │   ├── upload.py          # 文件上传
│   │   │   ├── check.py           # 合规检查
│   │   │   ├── report.py          # 报告 + 反馈
│   │   │   ├── rules.py           # 规则管理 + 同步
│   │   │   ├── auth.py            # 用户认证（注册/登录/验证/重置密码）
│   │   │   ├── admin.py           # 管理后台（用户/审计/文件对比/计费）
│   │   │   ├── announcements.py   # 警示公告
│   │   │   ├── categories.py      # 项目分类
│   │   │   ├── crawler.py         # 爬虫管理
│   │   │   ├── knowledge_graph.py # 知识图谱
│   │   │   ├── member.py          # 会员仪表盘
│   │   │   └── stats.py           # 系统统计
│   │   ├── core/                  # 核心配置
│   │   │   ├── config.py          # 配置管理
│   │   │   ├── security.py        # 认证权限（JWT + bcrypt）
│   │   │   ├── permissions.py     # RBAC 权限枚举 + 角色映射 (admin/user)
│   │   │   ├── audit.py           # 审计日志
│   │   │   └── metrics.py         # 指标收集
│   │   ├── engine/                # 合规引擎（五层流水线）
│   │   │   ├── routing.py         # 第0层：零Token路由审查
│   │   │   ├── rule_engine.py     # 第1层：规则引擎（7种类型+条件表达式）
│   │   │   ├── parameter_bias.py  # 第2层：参数倾向性检测（9种违规模式）
│   │   │   ├── llm_engine.py      # 第3层：LLM语义引擎（17维隐含风险）
│   │   │   ├── fusion.py          # 汇总层：四路风险合并器+复核路由
│   │   │   ├── evidence_matcher.py     # 证据链匹配
│   │   │   ├── platform_rules.py       # 平台规则加载与匹配
│   │   │   ├── semantic_chunking.py    # 语义分块
│   │   │   ├── shared_types.py         # 引擎间共享类型
│   │   │   ├── template_fingerprint.py # 模板指纹检测
│   │   │   └── variable_marker.py      # 变量标记
│   │   ├── models/                # 数据模型
│   │   │   ├── user.py            # 用户模型（bcrypt + 验证码 + 密码重置）
│   │   │   ├── announcement.py    # 警示公告（severity 四级分色）
│   │   │   ├── subscription.py    # 订阅计划 + 配额
│   │   │   ├── document.py        # 文档 / 文件记录
│   │   │   ├── rule.py            # 规则模型
│   │   │   ├── complaint_case.py  # 投诉案例
│   │   │   └── knowledge_graph.py # 知识图谱
│   │   ├── services/              # 服务层
│   │   │   ├── parser.py          # 文档解析 + 解析质量评估
│   │   │   ├── rule_sync.py       # 规则同步
│   │   │   ├── report_gen.py      # 报告生成
│   │   │   ├── excel_exporter.py  # Excel 导出
│   │   │   ├── prompt_manager.py  # Prompt 模板管理
│   │   │   ├── email_service.py   # 双通道邮件（Resend API + SMTP）
│   │   │   ├── minio_service.py   # MinIO 对象存储（含本地回退）
│   │   │   ├── announcement_service.py  # 公告 CRUD + 全网采集合成
│   │   │   ├── quota_service.py         # 配额消费 + 月度重置
│   │   │   ├── crawler_service.py       # 爬虫服务
│   │   │   ├── browser_crawler.py       # 浏览器爬虫
│   │   │   ├── mof_crawler.py           # 财政部爬虫
│   │   │   ├── sync_scheduler.py        # 同步调度器
│   │   │   ├── knowledge_graph.py       # 知识图谱服务
│   │   │   ├── feedback_service.py      # 反馈服务
│   │   │   ├── clause_generator.py      # 条款生成
│   │   │   ├── rule_miner.py            # 规则挖掘
│   │   │   └── usage_tracker.py         # 用量追踪
│   │   └── db/                    # 数据库
│   │       ├── database.py        # SQLAlchemy 连接
│   │       └── migrations/        # Alembic 迁移
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                       # React 前端
│   ├── src/
│   │   ├── App.tsx                # 应用根组件（仅 theme + ConfigProvider）
│   │   ├── main.tsx               # ReactDOM 入口（包裹 ErrorBoundary）
│   │   ├── pages/                 # 页面（编排层，≤500行）
│   │   │   ├── Login.tsx          # 登录/注册
│   │   │   ├── Dashboard.tsx      # 按角色路由至 dashboards/
│   │   │   ├── Upload.tsx         # 文件上传 + 五层审查
│   │   │   ├── Report.tsx         # 合规报告详情
│   │   │   ├── History.tsx        # 审查历史
│   │   │   ├── AdminPanel.tsx     # 用户管理/审计/对比/计费
│   │   │   ├── AdminRules.tsx     # 规则列表/同步/反馈/看板
│   │   │   ├── ReviewCenter.tsx   # 审查中心容器（Tab 导航）
│   │   │   ├── RulesCenter.tsx    # 规则中心容器
│   │   │   ├── ReportCenter.tsx   # 报告中心容器
│   │   │   ├── KnowledgeBase.tsx  # 知识库容器
│   │   │   ├── Announcements.tsx  # 警示公告容器
│   │   │   ├── UserCenter.tsx     # 用户中心容器
│   │   │   ├── SystemManage.tsx   # 系统管理容器
│   │   │   ├── OpsCenter.tsx      # 运维中心容器
│   │   │   ├── SuperAdmin.tsx     # 超管看板
│   │   │   ├── dashboards/        # 按角色拆分的仪表盘
│   │   │   └── rules-admin/       # 规则管理子页面
│   │   ├── components/            # 通用组件
│   │   │   ├── ErrorBoundary.tsx   # 全局异常边界
│   │   │   ├── AuthInitializer.tsx # Session 恢复
│   │   │   ├── ShellLayout        # 无，见 layouts/
│   │   │   ├── PageHeader.tsx     # 页面标题 + 面包屑
│   │   │   ├── DataTable.tsx      # 通用表格
│   │   │   ├── EmptyState.tsx     # 空态组件
│   │   │   ├── StatusTag.tsx      # 状态标签
│   │   │   ├── SearchBar.tsx      # 搜索栏
│   │   │   ├── DetailDrawer.tsx   # 详情抽屉
│   │   │   ├── RequireRole.tsx    # @deprecated — 路由守卫已由 RouteGuard 统管
│   │   │   ├── business/          # 业务组件
│   │   │   ├── charts/            # 图表组件
│   │   │   ├── common/            # 通用组件（ComingSoonPage）
│   │   │   └── dashboard/         # 仪表盘组件（KpiCard/RecentActivity/RiskDistribution/TrendChart）
│   │   ├── features/              # 功能模块（hooks + components）
│   │   │   ├── report/            # 报告模块
│   │   │   ├── upload/            # 上传模块（useUploadQueue）
│   │   │   ├── admin/             # 管理模块（useUserManage/useAuditLog/useBilling）
│   │   │   ├── rules/             # 规则模块（useRuleList/useSyncManager/useDashboardTab）
│   │   │   └── history/           # 历史模块（useReportHistory）
│   │   ├── layouts/               # 布局组件
│   │   │   ├── ShellLayout.tsx     # 顶层壳（Header + Sider + Content + Footer）
│   │   │   ├── Sidebar.tsx         # 左侧菜单（从 routeConfig 派生）
│   │   │   └── MobileNav.tsx       # 移动端底部 Tab 栏
│   │   ├── routes/                # 统一路由系统
│   │   │   ├── routeConfig.tsx     # 路由/菜单/权限 单一数据源
│   │   │   ├── types.ts           # RouteConfig 类型定义
│   │   │   ├── renderRoutes.tsx    # routeConfig → React Router <Route> 树
│   │   │   ├── AppRoutes.tsx       # AppRoutes 组件（MemoryRouter/BrowserRouter）
│   │   │   ├── RouteGuard.tsx      # 路由权限守卫（403/跳转登录）
│   │   │   ├── NotFoundPage.tsx    # 404 页面
│   │   │   └── __tests__/          # 路由测试
│   │   ├── stores/                # Zustand 状态管理
│   │   │   ├── authStore.ts        # 用户身份 + 登录/登出/session恢复
│   │   │   ├── permissionStore.ts  # 权限集合
│   │   │   └── menuStore.ts        # 菜单状态（从 routeConfig 派生）
│   │   ├── services/              # API 服务层
│   │   │   ├── http.ts            # 统一 HTTP 客户端（axios + 拦截器）
│   │   │   └── api.ts             # 所有 API 函数（页面禁止直接调用 axios/fetch）
│   │   ├── types/                 # TypeScript 类型定义
│   │   │   ├── index.ts           # 核心类型（UserRole/admin/user, 报告, 规则, 计费...）
│   │   │   └── admin-types.ts     # 管理后台类型
│   │   ├── permissions/           # 权限工具函数
│   │   │   └── permissions.ts     # hasPermission / isAdminLike / isSuperAdminLike
│   │   ├── utils/                 # 工具函数
│   │   │   ├── error.ts           # getErrorMessage（类型安全的错误提取）
│   │   │   └── logger.ts          # 日志工具（仅 dev 输出）
│   │   └── test/                  # 测试基础设施
│   │       └── setup.ts           # vitest setup（localStorage mock, matchMedia, scrollTo）
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts             # Vite + vitest 配置（manualChunks + test）
│   └── Dockerfile
├── rules/                          # 规则资产
│   ├── compliance_rules.json      # 结构化合规规则库（5大类40+条）
│   ├── base_rules.json            # 基础法规规则
│   ├── platform_rules.json        # 平台规则代码映射
│   ├── forbidden_words.json       # 禁用词库（12大类50+模式）
│   ├── parameter_bias_rules.json  # 参数倾向性检测规则
│   ├── project_categories.json    # 项目分类 + 字段→规则映射
│   ├── section_affinity.json      # 章节亲和度配置
│   ├── template_fingerprints.json # 模板指纹库
│   ├── manifest.json              # 规则清单
│   ├── case_study_reports/        # 投诉案例分析报告
│   ├── industry/                  # 行业细分规则（19个行业）
│   ├── platforms/                 # 平台规则（甘肃/广东/江苏/四川/浙江）
│   ├── prompts/                   # LLM Prompt 模板（11个 prompt 文件）
│   └── versions/                  # 规则版本快照
├── docs/                          # 设计文档
├── tests/                         # 项目级集成测试（前端+后端）
├── nginx/                         # Nginx 配置
├── docker-compose.yml
└── README.md
```

## 前端 RBAC 权限模型

**后端真实角色**：`admin` / `user`（`backend/app/core/permissions.py`）

**前端角色**：与后端完全一致。不再存在 `super_admin` / `reviewer` / `agent` / `enterprise`。

**权限判断唯一来源**：`/api/auth/me` 返回的 `permissions` 数组 + `role` 字段。

**isSuperAdmin**：来自后端 `is_super_admin` 字段（当前后端未落地，前端默认 `false`）。
禁止从 `permissions` 数组推导超管身份。超管入口（`/ops` 等）全部隐藏，直至后端支持该字段。

**核心文件**：
- `stores/authStore.ts` — zustand store，统一管理登录/session恢复/登出/权限查询
- `routes/routeConfig.tsx` — 每个路由声明 `requiredRoles: ['admin'] | ['admin', 'user'] | []`
- `routes/RouteGuard.tsx` — 渲染层守卫，`requiredRoles=[]` 返回 403

## 前端路由体系

**单一数据源**：`routes/routeConfig.tsx`

```
routeConfig.tsx ── 单一数据源
    │
    ├── renderRoutes.tsx → React Router <Route> 树
    ├── extractMenuItems() → Sidebar 菜单
    ├── flattenRoutes() → 权限检查 / 测试
    └── RouteGuard → 统一 403 / 跳转登录
```

**路由配置项**：
- `path` — URL 路径
- `element` — lazy import 页面组件
- `requiredRoles` — undefined=公开, []=禁止访问(403), ['admin']=仅管理员
- `redirect` — 重定向目标
- `menu` — 菜单显示配置（不声明则不在菜单出现）
- `children` — 嵌套子路由

**已删除的旧文件**：`config/menu.tsx`、`config/rbac.tsx`、`contexts/PermissionContext.tsx`

## 规则引擎支持的规则类型
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

## 规则热加载
规则更新后无需重启服务，引擎会检测文件变化并自动重新加载。

## 开发命令
```bash
# 后端（从 backend/ 目录）
uv sync
uv run uvicorn app.main:app --reload
uv run pytest

# 前端（从 frontend/ 目录）
npm install
npm run dev
npm run build     # tsc + vite build
npm run test      # vitest run

# Docker 部署（从项目根目录）
docker compose up -d --build
```

## 参考项目：hlgs（华招国际）
本项目审核模块的设计和规则资产大量借鉴了 hlgs 项目（`/Users/likeming/projects/hlgs`）。

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

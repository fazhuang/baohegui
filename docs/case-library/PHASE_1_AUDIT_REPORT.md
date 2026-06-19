# 包合规知识库模块复核审计报告与深度优化方案

> 审计日期：2026-06-19  
> 代码基线：`3f3a36e2`（`fix(case-library): 采集-KG闭环增强 + 索引迁移 + 管理可见性`）  
> 审计对象：知识图谱、案例采集、案例库、法规库、规则资产、RAG、管理端和相关测试  
> 复核结论：**有条件允许内部验证，但不能据此认定知识库模块已生产就绪**

---

## 0. 执行摘要

Claude 原报告覆盖面较完整，但存在多处事实错误、未经复现的数据量、风险定级失真和优化顺序倒置。最关键的修正如下。

| 原报告结论 | 复核结果 |
|---|---|
| `compliance_rules.json` 已缺失 | **错误**。文件存在，当前含 88 条规则 |
| 规则引擎有 7 种规则类型 | **错误**。当前执行模型只有 4 种：`chapter_required`、`keyword_required`、`forbidden`、`format_required` |
| 活跃案例 71 条、KG 约 95 个节点 | **无法成立**。本机 PostgreSQL 实测：`complaint_cases=0`、`kg_nodes=714`、`kg_edges=1520` |
| KG case 节点约 75 个，多数未审核 | **错误**。本机实测 case 节点 20 个，全部 `verified`，且没有 `CC-*` 采集同步节点 |
| 财政部存在 closed-client bug | **当前代码不存在**。财政部抓取仍发生在 `AsyncClient` 上下文内 |
| `_case_history` 无长度限制 | **错误**。当前限制为 50 条 |
| Playwright 未安装时静默失败 | **不准确**。代码会记录 warning，但没有结构化告警和健康状态 |
| 三个 Base 导致不能 JOIN | **错误**。SQLAlchemy 查询能跨表 JOIN；真实问题是多 Base 增加迁移遗漏和 schema 漂移风险 |
| 采集案例应自动提升 trust 并直接进 RAG | **危险建议**。应保留未审核隔离，建设审核和质量门禁，不能用自动提权绕过可信边界 |
| 向量化是当前第一优先级 | **顺序错误**。当前优先级应是数据闭环、访问控制、采集可靠性和检索评测；向量化必须由评测结果驱动 |

当前模块的真实状态是：

1. 规则资产、KG 模型、可信 RAG 过滤和前端查询骨架已经形成。
2. 本地数据库没有采集案例，说明“采集 → 案例表 → KG → 审核 → RAG”的运营闭环尚未在当前环境跑通。
3. 普通用户默认可以看到 `unreviewed` 和 `flagged` KG 节点，案例详情接口还会返回原始正文和当事方字段，知识发布边界不完整。
4. RAG 当前主要依赖图关系和 SQL `ILIKE`，没有可量化的召回率、准确率和回归基准。
5. 现有测试能证明权限和 KG 可信过滤的部分契约，但没有覆盖采集安全、真实数据源、脱敏、检索质量和生产迁移一致性。

---

## 1. 审计方法与证据边界

本次复核采用以下证据：

- 静态代码检查：模型、API、服务、迁移、前端路由和页面。
- 规则资产解析：直接读取 JSON 并统计实际条目。
- 规则引擎实例化：验证真正加载到执行引擎中的规则数和类型。
- 本机 PostgreSQL 只读查询：核验案例、KG、边和数据库规则数量。
- 自动化测试：
  - 后端知识库相关测试：88 项通过。
  - 前端 Vitest：85 项通过。
  - 前端生产构建：通过。

本次没有执行真实外网采集，也没有将开发机数据库等同于生产数据库。因此，所有动态数据量均明确标注为“本机 PostgreSQL 实测”，不外推为生产数据。

---

## 2. 当前模块结构

### 2.1 实际结构图

```text
前端
├── /kg
│   ├── KGGraph.tsx       搜索、筛选、统计、关联节点、Seed、待审核数量
│   ├── KGCases.tsx       KG case 节点查询和详情
│   └── KGLegal.tsx       KG regulation 节点查询和详情
├── /rules                规则看板、编辑、版本和同步
└── 当前缺口
    ├── 没有完整的 KG 节点审核工作台
    ├── 没有案例采集运营页面
    └── 没有案例详情脱敏/原文分级查看

FastAPI API
├── /api/kg/*
│   ├── search / related / stats
│   ├── regulation / cases / similar-cases / rag-context
│   └── seed / node CRUD / audit / edge
├── /api/crawler/*
│   ├── trigger / status
│   ├── cases / cases/{id} / stats
│   └── analyze
├── /api/rules/*
└── /api/check/*          审查主链路中调用 KG RAG

服务层
├── knowledge_graph.py    KG 搜索、种子、同步、关系和 RAG
├── crawler_service.py    CCGP、宁夏、陕西、财政部采集编排
├── browser_crawler.py    陕西 Playwright；Scrapling 仍为占位
├── mof_crawler.py        财政部列表抓取
├── sync_scheduler.py     内存调度和最近 50 条历史
└── rule_miner.py         基于硬编码模式分析案例，不写入正式规则

数据层
├── complaint_cases       采集案例原始/结构化记录
├── kg_nodes / kg_edges   检索和关系投影
├── rules                 数据库规则表
└── rules/*.json          当前主要规则资产和版本资产
```

### 2.2 RAG 实际链路

```text
规则引擎产生 violation
        │
        ▼
build_rag_context(rule_id, violation_desc)
        │
        ├── 可信 rule 节点
        │   条件：verified 且 trust >= 0.3
        │
        ├── references → regulation
        │   条件：目标节点非 rejected，trust >= 0.3
        │
        ├── demonstrated_by → 关联节点
        │   当前没有强制目标必须是 case
        │
        └── 无直接案例边时
            find_similar_cases()
            使用 SQL ILIKE 对完整描述做子串匹配
        │
        ▼
拼接 node_id / source / trust / 内容摘要
        │
        ▼
llm_engine.analyze(..., kg_context=...)
```

可信节点过滤是当前链路中做得较好的部分。主要短板是检索召回弱、关系类型约束不完整、检索效果不可测。

---

## 3. 数据模型与 ER 关系

```text
uploaded_files 1 ─── N document_sections
       │
       └──────────── 1 ─── N compliance_reports

complaint_cases
├── 采集案例事实表
├── source_url 由迁移创建唯一索引
└── 通过 metadata_json.complaint_case_id 投影到 kg_nodes
    当前不是数据库外键

kg_nodes 1 ─── N kg_edges.source_id
kg_nodes 1 ─── N kg_edges.target_id

rules 1 ─── N rule_mappings
rules     ─── rule_versions

compliance_reports ─── feedback_records ─── rule_confidences
```

### 3.1 模型复核结论

| 项目 | 结论 |
|---|---|
| `ComplaintCase` 与 `KGNode` 的 Base | 两者实际都来自 `app.models.document.Base`，不存在跨 Base 无法 JOIN 的问题 |
| 多 Base 架构 | `DocumentBase`、`RuleBase`、`AuditBase` 等并存；可以查询，但迁移注册和建表路径更容易漂移 |
| Alembic metadata | `env.py` 只显式合并 Document、Rule、Audit；应建立统一模型注册测试，避免新增模型漏入迁移 |
| 案例到 KG 的关系 | 只存在 `metadata_json` 中的逻辑引用，没有 FK、级联或一致性约束 |
| `source_url` 唯一性 | 唯一索引只在迁移中表达，ORM 模型未声明；仅运行 `create_all()` 的环境可能缺少该约束 |
| `complaint_types` | 模型注释为 JSON，但采集器写入 `str(list)`；同步器优先 `json.loads`，失败后会把整个 repr 当成一个标签 |
| `decision_date` | 使用字符串而不是日期类型，排序、范围查询和格式约束较弱 |

### 3.2 建议的数据职责

必须先确定每类数据的唯一事实源：

| 数据 | 建议事实源 | 其他存储角色 |
|---|---|---|
| 采集案例 | `complaint_cases` | `kg_nodes` 仅作为发布后的检索投影 |
| 法规 | 独立 `legal_documents/legal_articles` | KG 为关系和检索投影 |
| 规则 | Phase 1 继续以版本化 JSON 为事实源 | DB/KG 为查询、运营和关联投影 |
| 模板 | 独立模板元数据和对象存储 | 指纹文件只承担识别，不承担模板内容库 |
| 术语 | 独立 glossary 表 | KG concept 为关系投影 |

不要继续让 JSON、数据库规则、KG 节点三方都像“主数据”。每个投影都应有 `origin_type`、`origin_id`、`content_hash`、`sync_version` 和 `last_synced_at`。

---

## 4. 当前数据与资产基线

### 4.1 本机 PostgreSQL 实测

查询时间：2026-06-19。

| 对象 | 实测值 |
|---|---:|
| `complaint_cases` | 0 |
| `kg_nodes` | 714 |
| `kg_edges` | 1520 |
| 数据库 `rules` | 0 |
| KG rule 节点 | 487 |
| KG regulation 节点 | 207 |
| KG case 节点 | 20 |
| KG verified 节点 | 714 |
| `rule_id like 'CC-%'` 的采集案例节点 | 0 |

这组数据说明：

- 当前本机库主要是 Seed 生成的 KG 数据。
- 采集案例闭环没有在当前数据库形成可验证的数据。
- 原报告中的“CCGP 21 + 宁夏 40 + 财政部 10”不是当前数据库事实，报告也未提供可复现查询。
- 数据库 `rules=0` 不代表规则引擎无规则，因为当前引擎以文件资产为主。

### 4.2 规则资产实测

| 资产 | 实测值 |
|---|---:|
| `rules/manifest.json` 声明总量 | 370 |
| `base_rules.json` | 52 |
| `compliance_rules.json` | 88 |
| `platform_rules.json` mappings | 26 |
| `forbidden_words.json` 顶层 patterns | 18 |
| `parameter_bias_rules.json` patterns | 25 |
| 行业文件 | 18 |
| 地方平台文件 | 5 |
| Prompt 文件 | 11 |
| 模板指纹 | 2631 |
| 版本快照文件 | 27 |
| `rules/versions/manifest.json` 当前版本记录 | 7 |

`RuleEngine()` 实际加载 214 条执行规则：

| 类型 | 数量 |
|---|---:|
| `keyword_required` | 114 |
| `forbidden` | 85 |
| `chapter_required` | 8 |
| `format_required` | 7 |

来源分布：

| 来源 | 加载数 |
|---|---:|
| `compliance_rules.json` | 88 |
| `forbidden_words.json` 派生规则 | 74 |
| `base_rules.json` | 52 |

因此，`manifest total_rules=370` 是资产口径，不是当前规则引擎的有效执行规则数。后续报告必须区分“资产总量、引擎加载量、启用量、数据库量、KG 投影量”。

### 4.3 当前采集源对照

| 来源 | 当前实现 | 复核状态 | 主要问题 |
|---|---|---|---|
| 中国政府采购网 CCGP | HTTPX 列表页 + 详情解析 | 已实现，未做本次真实外网验证 | TLS 被关闭、页面结构硬编码、响应无大小限制 |
| 宁夏政府采购网 | HTTPX 列表页，复用详情解析 | 已实现，未做本次真实外网验证 | 与 CCGP 共用解析器，来源差异处理不足 |
| 陕西政府采购网 | Playwright 获取列表，HTTPX 拉详情 | 原型 | 依赖浏览器环境、缺 fixture 和结构化健康状态 |
| 财政部国库司 | HTTPS 优先、HTTP fallback | 原型 | 明文降级、解析规则有限 |
| 青海 | `crawl_with_scrapling()` 占位 | 未实现 | 只有日志和返回 0 |
| 新疆 | `crawl_with_scrapling()` 占位 | 未实现 | 只有日志和返回 0 |
| 甘肃 | 无专用适配器 | 未实现 | 需先确认稳定、合规的数据入口 |
| 全国公共资源交易平台 | 无代码 | 未实现 | 不应在当前闭环未稳定时扩源 |

采集源数量不是近期核心指标。近期应优先要求每个已接入来源具备：固定 fixture、连续 canary、来源健康度、失败原因、字段完整率和可重放能力。

---

## 5. 能力矩阵

| 能力 | 当前状态 | 复核判断 |
|---|---|---|
| 规则资产版本化 | 已实现 | 资产较丰富，但多口径和版本资产一致性需继续治理 |
| KG 节点/边 | 已实现 | 模型和 API 可用，关系完整性约束不足 |
| KG 查询 | 已实现 | 支持分页和过滤；`ILIKE` 在规模增长后会退化 |
| KG 管理 API | 已实现 | CRUD、审核、Seed 和边管理存在 |
| KG 管理前端 | 部分实现 | 可搜索、Seed、看待审核数量；不能完成批量审核和编辑闭环 |
| 法规库 | 部分实现 | 有 regulation 节点，但缺法规层级、条文结构和效力状态 |
| 案例采集 | 部分实现 | 4 个适配路径，Scrapling 仍占位，未验证真实源健康度 |
| 案例事实表 | 已实现 | 字段有限，数据格式和状态模型不完整 |
| 案例到 KG 同步 | 已实现 | 幂等更新基本成立，但缺强一致性、失败队列和发布状态 |
| 案例审核 | API 级实现 | 新案例默认隔离是正确设计；缺运营工作台和 SLA |
| RAG 法规关系检索 | 已实现 | 有可信过滤和溯源字段 |
| RAG 相似案例检索 | 弱实现 | SQL 子串匹配，不是语义相似 |
| 混合检索 | 未实现 | 无 FTS/BM25 与向量融合 |
| Reranker | 未实现 | 需要先建立评测集再决定 |
| 向量存储 | 未实现 | 不是当前第一阻塞项 |
| 检索评测 | 未实现 | 没有 Recall@K、MRR、nDCG 或业务命中率 |
| 案例规则挖掘 | 原型 | 硬编码模式分析，结果不进入正式候选规则工作流 |
| 术语库 | 未形成产品 | concept 类型存在，但没有独立事实模型和运营能力 |
| 模板库 | 未形成产品 | 指纹资产不等于可浏览、可维护的模板知识库 |
| 审计和可观测性 | 部分实现 | 有操作日志；采集和索引任务仍以进程内状态为主 |

### 5.1 成熟度结论

不建议再用缺乏权重定义的“48/100”作为结论。按可交付状态划分更准确：

| 领域 | 状态 |
|---|---|
| 规则资产和确定性检查 | 可内部使用，需继续做版本一致性治理 |
| KG 数据模型和可信 RAG 骨架 | 可内部验证 |
| 案例采集和案例运营 | 原型阶段 |
| 法规知识管理 | 数据投影阶段 |
| 检索质量 | 未达到可验收状态 |
| 管理后台 | 不完整 |
| 生产安全和可靠性 | 未达标 |

---

## 6. 主要发现与风险

### 6.1 P0：当前没有证据支持直接定为 P0 的远程可利用漏洞

原报告将 `verify=False` 直接定性为 P0 SSRF。当前采集入口不是用户任意 URL，不能等同于开放式 SSRF。它仍然是必须修复的高风险传输和出站访问问题，但风险描述应准确。

### 6.2 P1：生产前必须解决

| 编号 | 问题 | 证据与影响 |
|---|---|---|
| P1-01 | TLS 校验被关闭 | `crawler_service.py` 和 `browser_crawler.py` 使用 `httpx.AsyncClient(verify=False)`，允许中间人篡改采集内容 |
| P1-02 | HTTP 降级源 | `mof_crawler.py` 保留明文 HTTP fallback，可能引入被篡改内容 |
| P1-03 | 重定向和出站边界未校验 | `follow_redirects=True`，没有逐跳校验 scheme、域名、解析 IP 和私网地址 |
| P1-04 | 响应体无大小限制 | `_fetch_text()` 直接读取 `resp.text`，缺少流式上限和内容类型约束 |
| P1-05 | 案例详情暴露原始内容 | 任意认证用户可读取 `complainant`、`respondent` 和 `raw_content`，缺少脱敏和角色分级 |
| P1-06 | 未审核知识默认可见 | KG 搜索默认只排除 `rejected`，普通用户可以看到 `unreviewed`、`flagged`，并可显式筛选 |
| P1-07 | 采集数据没有可验证闭环 | 本机 `complaint_cases=0`、`CC-*` 节点为 0，无法证明当前定时采集能稳定产出和发布 |
| P1-08 | 采集任务状态可能误报成功 | `scrape_cases()` 即使 `stats.errors` 非空仍设置 `SUCCESS`，没有转为 `PARTIAL` |
| P1-09 | 关系类型约束不完整 | `references` 强制指向 regulation，但 `demonstrated_by` 未强制指向 case，错误边可能污染 RAG 案例上下文 |
| P1-10 | 检索效果不可验收 | 没有离线评测集和质量指标，无法证明 RAG 提升了审查召回而非增加噪声 |
| P1-11 | Schema 创建路径可能漂移 | 唯一索引只存在于迁移；`create_all()` 路径与 Alembic 路径可能产生不同 schema |

### 6.3 P2：影响质量、运营和扩展

| 编号 | 问题 | 影响 |
|---|---|---|
| P2-01 | `complaint_types` 使用 Python repr | 标签拆分失败、查询和统计不可靠 |
| P2-02 | 案例列表 `total` 契约错误 | `/api/crawler/cases` 把统计字典作为 `total` 返回，且没有按筛选条件计算总数 |
| P2-03 | 分析审计字段名不匹配 | API 审计读取 `analyzed_count/rules_generated`，服务实际返回 `analyzed/new_pattern_candidates`，日志可能恒为 0 |
| P2-04 | 采集适配器脆弱 | HTML 选择器硬编码，缺 fixture 回归、源版本和健康评分 |
| P2-05 | Playwright 缺失仅记录日志 | 没有在管理状态页暴露依赖缺失和源降级 |
| P2-06 | `ILIKE` 全表扫描 | 节点增长后搜索性能和中文检索质量会下降 |
| P2-07 | `get_related()` 存在 N+1 查询 | 每条边单独查询目标节点，边数增长后延迟放大 |
| P2-08 | 调度历史只在内存 | 重启丢失，无法形成运营审计、失败重放和 SLA |
| P2-09 | rule miner 不是正式工作流 | 只标记 `is_analyzed` 并返回候选，缺候选表、审核、版本和回滚 |
| P2-10 | 管理前端没有审核闭环 | 只能看到待审核数量，不能批量审核、比较原文、拒绝原因或追踪处理人 |

### 6.4 不应采用的“修复”

以下做法会让系统更不可信：

- 不得把所有采集节点自动设为 `verified`。
- 不得只因来源域名在白名单内就把案例直接注入 RAG。
- 不得在没有检索评测集时以“上向量库”代替质量验证。
- 不得让 rule miner 直接写生产规则并热加载。
- 不得把公开网页上的个人信息等同于可在产品内无差别传播。

---

## 7. 测试复核

### 7.1 本次实测结果

后端命令：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache \
BHG_DATABASE_URL=sqlite:////private/tmp/bhg_case_audit.db \
/Users/likeming/.local/bin/uv run pytest \
  tests/test_knowledge_graph.py \
  tests/test_crawler_sync.py \
  tests/security/test_kg_admin_auth.py \
  tests/security/test_crawler_auth.py -q
```

结果：**88 passed**。

前端：

```bash
npm test
npm run build
```

结果：

- Vitest：**5 files / 85 tests passed**。
- TypeScript + Vite production build：**通过**。

### 7.2 现有测试实际覆盖

- 匿名、普通用户、管理员的 KG 基础权限。
- KG Seed 幂等性。
- 可信 rule/target 的 RAG 过滤。
- rejected 和低 trust 节点不进入 RAG。
- concept 不得作为 regulation 进入 references。
- ComplaintCase 到 KG 的基本同步和幂等更新。
- 采集编排的 mock 闭环。
- 前端路由和 RBAC 基础契约。

### 7.3 关键缺口

| 缺口 | 必需测试 |
|---|---|
| TLS 与重定向安全 | 证书失败、HTTP 降级、跨域重定向、私网 IP、DNS rebinding |
| 响应资源限制 | 超大 Content-Length、chunked 超限、非 HTML、压缩炸弹 |
| 案例数据权限 | 普通用户不得读原始正文和敏感字段，管理员读取必须审计 |
| KG 发布边界 | 普通用户默认只读 published/verified；flagged/unreviewed 仅管理员 |
| 关系完整性 | 每种 relation 的合法 source/target 类型矩阵 |
| 数据格式 | `complaint_types` JSON、日期格式、content hash、重复案例 |
| 任务状态 | 部分失败必须是 PARTIAL；重启后任务状态可追溯 |
| 真实采集源 | 每个来源保存脱敏 fixture，做解析契约测试和定期 canary |
| 检索质量 | 固定查询集，统计 Recall@5、MRR、无依据率和人工相关性 |
| RAG 对审查的增益 | 同一评测集做 RAG on/off 对照，统计召回、误报、成本和延迟 |
| 迁移一致性 | 空库 Alembic upgrade、旧库 upgrade、ORM metadata 与数据库 schema 对照 |
| 前端运营流程 | 审核、拒绝、发布、批量操作、失败重试和权限的浏览器测试 |

当前测试通过只能支持“内部继续开发”，不能支持“案例采集和知识库已生产可用”。

---

## 8. 深度优化目标架构

### 8.1 案例数据流水线

```text
Source Adapter
    │
    ▼
Fetch Raw
  TLS / allowlist / redirect guard / size limit / checksum
    │
    ▼
Normalize
  UTF-8 / HTML清理 / 日期统一 / JSON字段 / 来源元数据
    │
    ▼
Deduplicate
  source_url + canonical_url + content_hash + 标题相似度
    │
    ▼
Extract
  规则提取 + 可选 LLM 结构化抽取
    │
    ▼
Quality Gate
  完整性 / 来源可信 / 内容长度 / PII / 解析置信度
    │
    ├── 不合格 → quarantine / retry / manual review
    │
    ▼
Review & Publish
  pending_review → verified → published
    │
    ▼
Index Projection
  KG / FTS / optional vector
    │
    ▼
RAG Retrieval
  权限过滤 → 候选召回 → 重排 → 引用校验
```

### 8.2 推荐状态机

`complaint_cases` 至少增加：

```text
fetched
  → normalized
  → extracted
  → pending_review
  → verified
  → published

异常分支：
  duplicate / rejected / parse_failed / quarantined / archived
```

状态变更必须记录：

- 操作人或自动任务 ID。
- 前后状态。
- 原因。
- 时间。
- 质量评分。
- 使用的抽取器和版本。
- 内容 hash。

### 8.3 发布边界

建议把“审核状态”和“发布状态”分开：

- `review_status`：内容是否被确认可信。
- `publish_status`：是否允许普通用户和 RAG 使用。

只有 `review_status=verified` 且 `publish_status=published` 的节点可以进入生产 RAG。自动发布只能用于满足严格条件的白名单来源，并且需要抽样审计和可回滚。

---

## 9. 分阶段优化方案

### Phase 0：基线固化与错误修正（2–3 人天）

目标：先让“数据量、规则量、测试量和状态”可重复验证。

| 任务 | 交付 |
|---|---|
| 修正当前 API 契约错误 | 案例列表 `total` 为筛选后整数；分析审计字段正确 |
| 统一统计口径 | 资产数、引擎加载数、启用数、DB 数、KG 投影数分别输出 |
| 增加知识库诊断命令 | 一条命令输出案例状态、KG 类型/状态、孤儿投影、重复边 |
| 建立数据快照文档生成 | 报告中的数据表由脚本生成，禁止手填约数 |
| 增加 schema 一致性测试 | Alembic、ORM metadata、关键索引和约束一致 |

验收：

- 同一 commit 上重复运行统计结果一致。
- 报告中不再出现 `XX行`、未经查询的约数或不存在文件。

### Phase 1：安全、数据隔离与采集可靠性（7–10 人天）

目标：让采集源不能轻易污染知识库，让未审核数据不越权暴露。

| 任务 | 关键要求 |
|---|---|
| 启用 TLS 校验 | 删除 `verify=False`；不允许静默降级 |
| 出站请求策略 | HTTPS、域名白名单、逐跳重定向校验、DNS/IP 私网拦截 |
| 下载限制 | 流式读取、最大字节数、Content-Type、连接/读取超时 |
| 数据分级 | 普通用户只看脱敏发布内容；原文仅管理员按需查看并审计 |
| KG 可见性 | 普通用户默认只见 published/verified；审核队列仅管理员 |
| 关系约束 | 建立 relation source/target 类型矩阵并在 API 和服务层校验 |
| 任务状态 | 有来源失败即 PARTIAL；错误按来源持久化 |
| 采集适配器测试 | 每个来源保存 HTML fixture 和解析契约 |
| 依赖健康 | Playwright/浏览器缺失在状态接口和管理端明确显示 |

验收：

- 安全测试覆盖恶意重定向、私网地址、超大响应和证书失败。
- 普通用户无法读取原始案例正文、敏感字段、未审核节点。
- 单一来源失败不影响其他来源，但任务状态准确为 PARTIAL。

### Phase 2：案例运营闭环（12–18 人天）

目标：从“有采集代码”提升为“管理员每天能运营”。

| 任务 | 关键要求 |
|---|---|
| 扩展案例模型 | canonical_url、source_type、case_no、city、review/publish status、quality_score、content_hash、sanitized_content |
| 规范字段 | `complaint_types` 和 `legal_basis` 使用 JSON/JSONB；日期使用 Date |
| 去重 | URL、内容 hash、标题/项目号相似度分层去重 |
| 审核工作台 | 原文/脱敏文对照、字段编辑、通过/拒绝、批量操作、审核理由 |
| 任务中心 | 采集历史、来源健康、失败重试、单条重放、处理耗时 |
| LLM 抽取 | 只生成结构化候选，不直接发布；保存模型、Prompt、置信度和原始证据 |
| KG 投影 | 发布成功后异步投影；失败可重试；投影有 origin 和 sync_version |
| 候选规则流 | 独立 candidate_rules 表，必须人工审核后进入版本化规则资产 |

验收：

- 管理员可完成“采集 → 去重 → 抽取 → 审核 → 发布 → KG 可见”全流程。
- 任一步骤失败可重试，不产生重复案例或重复边。
- 100 条人工标注样本上，字段抽取准确率达到预设门槛。

### Phase 3：检索质量工程（10–16 人天）

目标：先证明检索增益，再决定向量层规模。

### 第一步：低复杂度混合检索

优先使用现有 PostgreSQL：

- `pg_trgm` 支持中文标题/短文本模糊检索。
- PostgreSQL FTS 或预切词字段支持关键词召回。
- 对 `node_type`、`audit_status`、`trust_level`、`jurisdiction` 建联合索引。
- 批量查询关联节点，消除 N+1。

### 第二步：建立评测集

至少准备：

- 100 个真实审查问题。
- 每个问题的相关法规、案例和规则标注。
- 困难负样本：同名法规、相似项目、已废止法规、驳回案例。

指标：

- Recall@5。
- MRR@10。
- nDCG@10。
- 无依据回答率。
- 错引法规率。
- RAG 增量召回。
- P95 检索延迟。
- 单份审查增加的 Token 和成本。

### 第三步：按评测决定是否引入向量

如果关键词/图关系召回达不到目标，再在现有 PostgreSQL 内引入 `pgvector`，避免单机 Docker 增加独立向量数据库。

候选方案：

- 中文/多语言 Embedding：以实际评测选择 BGE-M3 等本地或国内 API 模型。
- 召回：关系检索 + FTS/trigram + vector。
- 融合：RRF 或可解释的加权融合。
- 重排：只有在 Recall 提升但 Top-K 精度不足时再引入 reranker。

验收建议：

- Recall@5 ≥ 0.85。
- MRR@10 ≥ 0.75。
- 错引法规率 ≤ 2%。
- RAG 相比无 RAG 的高风险条款召回提升 ≥ 10 个百分点。
- 误报率不得因 RAG 增加超过 3 个百分点。
- P95 检索延迟 ≤ 500ms（不含外部 LLM）。

### Phase 4：法规、术语和模板产品化（20–30 人天）

目标：在案例闭环和检索质量稳定后，再扩展知识库品类。

| 子模块 | 关键建设 |
|---|---|
| 法规库 | 法规版本、效力状态、发布/生效/失效日期、章/节/条、修订关系、引用关系 |
| 术语库 | 标准名、别名、定义、适用范围、来源、反例和关联规则 |
| 模板库 | 模板元数据、对象存储、适用项目、版本、风险标注；指纹只作为识别索引 |
| 知识图谱 | 增加法规修订、案例引用、相似案例、规则来源等受约束关系 |
| 知识问答 | 只基于 published 数据，答案必须返回引用和可验证来源 |

不要把力导向图作为高优先级。图可视化只有在能支持调查、规则溯源或审核决策时才有产品价值。

---

## 10. 性能与可观测性优化

### 10.1 数据库

- 为搜索建立适合查询模式的索引，不只依赖普通 B-tree。
- `get_related()` 改为一次 JOIN 批量取节点。
- 统计接口用聚合查询，避免多次 count。
- 大字段 `raw_content` 与列表查询分离。
- 所有投影写入使用幂等键和事务。

### 10.2 任务系统

当前进程内 scheduler 适合原型，不适合可靠运营。单机 Docker 阶段不必引入复杂分布式系统，可采用：

- PostgreSQL 持久化 job 表。
- 数据库 advisory lock 防止重复任务。
- 独立 worker 进程。
- 重试次数、退避、dead-letter 状态。
- 每个来源的 success rate、last success、items fetched、items published。

### 10.3 指标

建议增加：

- `crawler_source_success_total{source}`。
- `crawler_source_failure_total{source,reason}`。
- `crawler_items_fetched/published/duplicate/quarantined`。
- `knowledge_review_queue_size`。
- `knowledge_publish_latency_seconds`。
- `rag_retrieval_latency_seconds`。
- `rag_empty_context_total`。
- `rag_citation_rejected_total`。
- `kg_orphan_projection_total`。

---

## 11. 预计工作量与实施顺序

| 阶段 | 人天 | 是否阻塞下一阶段 |
|---|---:|---|
| Phase 0 基线固化 | 2–3 | 是 |
| Phase 1 安全和可靠性 | 7–10 | 是 |
| Phase 2 案例运营闭环 | 12–18 | 是 |
| Phase 3 检索质量工程 | 10–16 | 否，可与 Phase 2 后半段并行 |
| Phase 4 知识库产品化 | 20–30 | 否 |
| 合计 | 51–77 | |

建议按一个后端主力、一个前端/测试协同计算，完成 Phase 0–3 约需 6–9 周。Phase 4 应按真实客户使用反馈拆分，不宜一次性全做。

---

## 12. 发布门槛

### 允许内部验证

满足以下最低条件后，可继续内部业务验证：

- Phase 0 完成。
- 普通用户不再看到未审核/已标记知识。
- 案例原文和敏感字段完成分级。
- TLS 校验和响应大小限制完成。
- 采集部分失败状态准确。
- 至少一个真实来源 canary 连续稳定运行 7 天。

### 允许生产试点

还必须满足：

- 案例审核和发布工作台可用。
- 任务、失败和重试持久化。
- 数据迁移在空库和升级库均通过。
- 检索评测达到 Phase 3 门槛。
- RAG on/off 对照证明有净收益。
- 关键安全和浏览器流程测试通过。
- 数据回滚、下架和审计链路可用。

---

## 13. 最终结论

知识库模块不是空壳：规则资产、KG 模型、可信过滤、RAG 注入和前端查询已经具备较好的工程基础。但原报告高估了案例采集闭环、数据规模、管理成熟度和测试覆盖，并把向量化放在了过早的位置。

当前最重要的不是“尽快上向量库”，而是完成三件事：

1. 建立可信的数据发布边界，避免未审核和原始敏感数据直接暴露。
2. 让真实采集任务、案例审核、KG 投影和 RAG 使用形成可追踪、可重试、可回滚的闭环。
3. 建立检索评测集，用指标决定 FTS、向量和重排的投入。

**审计判定：有条件允许内部验证；知识库模块尚未达到生产试点门槛。**

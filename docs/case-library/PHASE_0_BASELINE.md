# Phase 0 — 现状审计与基线冻结

> 基线时间: 2026-06-18
> Git commit: `01e4db40`
> 分支: `main` (clean)
> 数据库: PostgreSQL 16 (Docker, 12 MB)

---

## 1. 当前文件结构（采集/案例相关）

```
backend/
├── app/
│   ├── api/crawler.py                          # 爬虫 API 路由 (134 行)
│   ├── api/knowledge_graph.py                  # KG API 路由 (含 /seed, /search 等)
│   ├── models/complaint_case.py                # ComplaintCase 数据模型 (29 行)
│   ├── services/crawler_service.py             # 主爬虫服务 (398 行)
│   ├── services/browser_crawler.py             # Playwright 浏览器爬虫 (93 行)
│   ├── services/mof_crawler.py                 # 财政部爬虫 (75 行)
│   ├── services/sync_scheduler.py              # 定时调度器 (322 行)
│   ├── services/rule_miner.py                  # 案例分析/规则挖掘 (202 行)
│   ├── services/knowledge_graph.py             # 知识图谱服务 (1288 行)
│   ├── core/config.py                          # 配置 (含 case_scrape_*)
│   ├── core/permissions.py                     # 权限定义
│   └── db/migrations/versions/
│       ├── 20260602_1622_initial_schema.py     # 初始迁移
│       ├── 20260617_1830_kg_nodes_v3.py        # KG v3 迁移
│       └── 20260618_1000_complaint_cases.py    # complaint_cases 补迁
├── tests/
│   ├── security/test_crawler_auth.py           # 爬虫鉴权测试 (7 个)
│   ├── security/test_kg_admin_auth.py          # KG 鉴权测试 (16 个)
│   └── test_knowledge_graph.py                 # KG 测试 (59 个)
frontend/
├── src/
│   ├── pages/KGCases.tsx                       # 案例库页面 (303 行)
│   ├── pages/KGGraph.tsx                       # 知识图谱概览
│   ├── pages/KGLegal.tsx                       # 法规库页面
│   ├── pages/KnowledgeBase.tsx                 # 知识库 Tab 容器
│   ├── services/api.ts                         # API 服务层 (crawler 调用数: 0)
│   └── types/index.ts                          # PermissionKey 含 crawler:read/trigger
rules/
├── case_study_reports/
│   └── gov_procurement_complaints_analysis.md  # 558 条甘肃投诉案例分析报告 (318 行)
```

## 2. 当前数据库结构

### 2.1 complaint_cases 表

| 列 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK | NOT NULL | auto | 自增主键 |
| province | VARCHAR(32) | NOT NULL | — | 省份标签 |
| source_url | VARCHAR(512) | NULL | — | 源 URL |
| title | VARCHAR(255) | NOT NULL | — | 公告标题 |
| project_name | VARCHAR(255) | NULL | — | 采购项目名称 |
| project_number | VARCHAR(128) | NULL | — | 项目编号 |
| complainant | TEXT | NULL | — | 投诉人信息（未脱敏） |
| respondent | TEXT | NULL | — | 被投诉人（未使用） |
| decision_date | VARCHAR(16) | NULL | — | 决定日期 |
| decision_type | VARCHAR(16) | NOT NULL | — | upheld/rejected/partial/dismissed |
| complaint_types | TEXT | NULL | — | JSON 字符串 (Python list repr) |
| legal_basis | TEXT | NULL | — | 法规依据（未使用） |
| summary | TEXT | NULL | — | 处理结果摘要 |
| raw_content | TEXT | NULL | — | 原始全文 (≤5000 字，未脱敏) |
| is_analyzed | INTEGER | NULL | — | 0=未分析 1=已分析 2=已提炼规则 |
| created_at | TIMESTAMP | NULL | — | 创建时间 |

**索引**: 仅有主键索引 `complaint_cases_pkey(id)`.

**缺失索引**:
- `source_url` — `_save_case()` 每次去重全表扫描
- `decision_type` — 统计查询无索引
- `province` — 按省份筛选无索引
- `is_analyzed` — 规则挖矿无索引
- `created_at` — 排序无索引

**缺失字段** (与目标模型相比):
- 无 `case_no` / `city` / `source_name` / `source_type`
- 无 `procurement_type` / `complaint_points` / `facts`
- 无 `authority_opinion` / `decision_result` / `compliance_insights`
- 无 `risk_level` / `quality_score` / `content_hash` / `source_url_hash`
- 无 `review_status` / `reviewed_by` / `reviewed_at` / `published_at` / `updated_at`
- 无 `sanitized_content` / `sanitization_status`
- 无 `extraction_status` / `extraction_version`

**缺失关联表**:
- 无 `case_sources` / `case_tags` / `case_tag_relations`
- 无 `crawl_jobs` / `crawl_job_items`
- 无 `case_rule_candidates` / `case_duplicate_candidates`

### 2.2 数据量

| 表 | 记录数 |
|---|---|
| `complaint_cases` | **0** |
| `kg_nodes` (case) | **20** (全部硬编码) |
| `kg_edges` (case 相关) | **12** (rule→case: demonstrated_by) |

### 2.3 配置项

```python
# backend/app/core/config.py L117-120
case_scrape_enabled: bool = True       # BHG_CASE_SCRAPE_ENABLED
case_scrape_interval_hours: int = 168  # BHG_CASE_SCRAPE_INTERVAL_HOURS (7d)
ccgp_base_url: str = "https://www.ccgp.gov.cn"
```

---

## 3. 当前 API 清单

### 3.1 爬虫 API (`/api/crawler`)

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/crawler/trigger` | admin | 手动触发采集 → `sync_scheduler.scrape_cases()` |
| GET | `/api/crawler/status` | user/admin | 调度器状态 (running/completed/next) |
| GET | `/api/crawler/cases` | user/admin | 分页列表 (province/decision_type 筛选) |
| GET | `/api/crawler/cases/{id}` | user/admin | 单条详情（含 raw_content） |
| POST | `/api/crawler/analyze` | admin | 规则分析 → `analyze_all_unanalyzed()` |
| GET | `/api/crawler/stats` | user/admin | 统计 (total/upheld/rejected/partial) |

### 3.2 知识图谱 API (`/api/kg`)

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/kg/search` | user/admin | 多维度搜索 (node_type/tags/jurisdiction) |
| GET | `/api/kg/related/{id}` | user/admin | 关联节点查询 (方向过滤) |
| GET | `/api/kg/cases/{rule_id}` | user/admin | 规则关联案例 |
| GET | `/api/kg/rag-context` | user/admin | LLM RAG 上下文 (案例+法规) |
| POST | `/api/kg/seed` | admin | 幂等种子初始化 |
| PUT | `/api/kg/node/{id}/audit` | admin | 审核节点 (trust/status) |
| GET | `/api/kg/nodes/needing-review` | admin | 待审核节点列表 |

### 3.3 权限体系

```
Permission.crawler:read      — 普通用户拥有
Permission.crawler:trigger   — 仅管理员
Permission.kg:read           — 普通用户拥有
Permission.kg:seed           — 仅管理员
```

---

## 4. 当前采集源清单

### 4.1 已实现

| # | 来源 | 域名 | 爬取方式 | 状态 |
|---|---|---|---|---|
| 1 | CCGP 全国 | ccgp.gov.cn | httpx + BeautifulSoup | ✅ 活跃 (2 页列表) |
| 2 | 宁夏 | ccgp-ningxia.gov.cn | httpx + BeautifulSoup | ✅ 活跃 (3 个 Tab 页) |
| 3 | 陕西 | ccgp-shaanxi.gov.cn | Playwright (headless) | ⚠️ 脆弱 — Playwright 可能未安装 |
| 4 | 财政部 | gks.mof.gov.cn | httpx + BeautifulSoup | ⚠️ 仅 HTTP |

### 4.2 未实现（仅有占位）

| # | 来源 | 说明 |
|---|---|---|
| 5 | 青海 | `crawl_with_scrapling()` → 返回 0 |
| 6 | 新疆 | `crawl_with_scrapling()` → 返回 0 |
| 7 | 甘肃 | 无独立爬取器（规则挖掘和案例库覆盖甘肃但无采集入口） |
| 8 | 全国公共资源交易平台 | 无代码 |

### 4.3 安全风险

| 风险 | 文件 | 说明 |
|---|---|---|
| **SSRF: `verify=False`** | `crawler_service.py:280` | `httpx.AsyncClient(verify=False)` — 禁用 TLS 验证 |
| **SSRF: `verify=False`** | `browser_crawler.py:71` | 同上 |
| **HTTP 明文** | `mof_crawler.py:21-22` | 财政部 URL 使用 `http://` 而非 `https://` |
| **无域名白名单** | crawler_service.py | 爬虫直接访问硬编码 URL，未做来源白名单校验 |
| **无响应大小限制** | crawler_service.py | `_fetch_text()` 无 Content-Length 上限 |
| **无重定向验证** | crawler_service.py | `follow_redirects=True` 但未验证重定向目标 |
| **raw_content 未脱敏暴露** | api/crawler.py:107 | `/api/crawler/cases/{id}` 返回 raw_content 给普通用户 |
| **调度器内存泄漏** | sync_scheduler.py:83 | `_case_history` 限制 50 条但有 `_history` 两个列表未限制 |

---

## 5. 知识图谱同步路径

```
complaint_cases 表 (空)  ──无自动同步──▶  kg_nodes 表 (20 条硬编码)
                                     │
                                     │ 仅通过 POST /api/kg/seed 手动触发
                                     │ Phase 9: 查询 complaint_cases →
                                     │   创建 node_type='case', audit_status='unreviewed', trust=0.55
                                     ▼
                               kg_nodes (case 节点)
                                     │
                                     │ RAG 信任门槛: verified + trust >= 0.3
                                     │ 爬虫同步的节点 trust=0.55 但 audit_status='unreviewed'
                                     │ → **无法进入 RAG** (RAG 强制要求 verified)
                                     ▼
                              前端 /kg/cases 页面
                              (排除 rejected，包含 unreviewed)
```

**关键发现**:
1. 从 `complaint_cases` 同步到 `kg_nodes` **不自动发生** — 必须手动调用 `POST /api/kg/seed`
2. 爬虫同步的案例 `audit_status='unreviewed'`，RAG 强制 `verified` → **永久不可被 RAG 引用**，直到管理员审核
3. 20 个硬编码案例 `audit_status='verified'`，直接参与 RAG

---

## 6. RAG 引用案例现状

### 6.1 RAG 调用链

```
check.py (合规审查)
  → llm_engine.py (LLM 语义引擎)
    → knowledge_graph.build_rag_context(rule_id, violation_desc)
      → find_regulation_for_rule()    — 法规依据 (仅 verified)
      → find_cases_for_rule()         — 规则关联案例 (仅 verified + trust>=0.3)
      → find_similar_cases()          — 相似案例检索 (仅 verified + trust>=0.3)
```

### 6.2 信任门槛

```python
TRUST_MIN_ENRICHMENT = 0.3  # RAG 最低可信度
```

- 硬编码案例: `trust_level=0.65`, `audit_status='verified'` → ✅ 进入 RAG
- 爬虫同步案例: `trust_level=0.55`, `audit_status='unreviewed'` → ❌ 不进入 RAG
- 拒绝案例: `audit_status='rejected'` → ❌ 不进入 RAG

### 6.3 RAG 大模型引用格式

```
- [case] {标题} ({内容摘要}...)
  [来源: {source}, 节点#{node_id}, 可信度:{trust_level:.0%}]
```

---

## 7. 前端案例库真实功能

### 7.1 路由

| 路径 | 页面 | 菜单 | 访问权限 |
|---|---|---|---|
| `/kg` | KGGraph | 知识图谱 | 认证用户 |
| `/kg/cases` | KGCases | 案例库 | 认证用户 |
| `/kg/legal` | KGLegal | 法规库 | 认证用户 |

### 7.2 KGCases.tsx 功能

- 搜索框 + 标签筛选 (品牌锁定/参数排他/厂家授权/资质超标/业绩要求/评分标准/投诉成立/参数指向/中小企业/异常低价)
- 省份筛选 (甘肃/宁夏/四川/全国)
- 分页 (50 条/页)
- 详情抽屉 (来源/管辖/可信度/审核状态/内容/关联规则)
- 从 `GET /api/kg/search?node_type=case` 加载数据

### 7.3 缺失功能

- 无案例提交/反馈入口
- 无审核队列界面 (管理员)
- 无采集管理界面
- 无重复案例合并界面
- 无脱敏状态展示
- 无质量评分展示

---

## 8. 案例数量统计

| 来源 | 类型 | 数量 | 状态 |
|---|---|---|---|
| `complaint_cases` 表 (爬虫采集) | 结构化案例 | **0** | 爬虫从未执行 |
| `kg_nodes` (硬编码 seed) | 知识图谱节点 | 20 | verified, trust=0.65 |
| `rules/case_study_reports/` | 分析报告 (MD) | 1 | 558 条甘肃投诉分析 |

**KG 中的 20 个硬编码案例分布**:

| 管辖 | 案例数 | 示例 |
|---|---|---|
| 宁夏 | 7 | PACS 存储/手术麻醉/医疗设备等 |
| 甘肃 | 4 | 品牌锁定/授权/业绩/评分 |
| 陕西 | 3 | 内部型号/参数排他/机器人手术 |
| 四川 | 3 | 参数排斥/检测报告/评审扣分 |
| 青海 | 2 | 废止标准/评分不匹配 |
| 全国 | 1 | (无) |

---

## 9. 测试结果

### 9.1 爬虫鉴权测试 (7/7 通过)

```
PASSED test_anonymous_cannot_trigger_crawler
PASSED test_normal_user_cannot_trigger_crawler
PASSED test_anonymous_cannot_trigger_analysis
PASSED test_normal_user_cannot_trigger_analysis
PASSED test_normal_user_can_list_cases
PASSED test_anonymous_cannot_list_cases
PASSED test_admin_can_trigger_crawler
```

### 9.2 KG 鉴权测试 (16/16 通过)

```
PASSED test_normal_user_cannot_update_node
PASSED test_normal_user_cannot_delete_node
PASSED test_normal_user_cannot_audit_node
PASSED test_normal_user_cannot_get_needing_review
PASSED test_normal_user_cannot_create_edge
PASSED test_normal_user_can_search_kg
PASSED test_anonymous_cannot_search_kg
PASSED test_normal_user_can_get_stats
PASSED test_normal_user_can_get_related
PASSED test_normal_user_can_get_rag_context
... (16 total)
```

### 9.3 知识图谱测试 (59/59 通过)

含: RAG 链路可追溯、concept 排除、分页、边校验、complaint_case 同步、信任过滤

---

## 10. 已知安全风险

### 10.1 严重 (P0)

1. **SSRF**: `httpx.AsyncClient(verify=False)` 在两处使用，禁用 TLS 验证
2. **未脱敏数据暴露**: `/api/crawler/cases/{id}` 返回 `raw_content` (含供应商/个人/联系方式) 给普通认证用户
3. **HTTP 明文**: 财政部爬虫使用 HTTP 协议，存在中间人攻击风险

### 10.2 高危 (P1)

4. **无域名白名单**: 无 SSRF 防御，爬虫只依赖硬编码 URL
5. **无响应大小限制**: `_fetch_text()` 可下载任意大小内容
6. **无限重定向**: `follow_redirects=True` 无次数或目标域名限制
7. **硬编码 user-agent 和 headers**: 容易被反爬虫机制误封
8. **缺少 source_url 唯一索引**: 去重仅靠 ORM 查询，无数据库级约束

### 10.3 中危 (P2)

9. **调度器内存泄漏**: 两个历史列表持续增长
10. **无采集审计**: 无 `crawler_trigger`/`crawler_analyze` 审计记录（虽然代码写入审计但测试中看不到记录）
11. **Playwright 依赖脆弱**: 浏览器未安装时静默跳过，无告警机制

---

## 11. 数据迁移风险

### 11.1 已有数据

- `complaint_cases` 为空 → **无数据丢失风险**
- `kg_nodes` 含 20 条硬编码案例 → 扩展 `complaint_cases` 字段后，Phases 须处理 KG 种子数据的回填

### 11.2 兼容性风险

| 风险 | 说明 |
|---|---|
| ComplaintCase 继承 `Base` 自 `document.py` | 修改 Base 模型可能影响 documents 表 |
| `complaint_types` 存为 Python `str(list)` 非 JSON | 格式 `['参数', '品牌']` 非标准 JSON |
| 迁移链 `8b1e3f95c2d4` 已达 HEAD | 新增迁移需正确设置 `down_revision` |
| KG Phase 9 同步依赖 `is_analyzed >= 0` 和 `rule_id='CC-{id}'` | 扩展字段后需验证去重逻辑仍有效 |

### 11.3 测试数据

- conftest.py 的 `TABLE_NAMES` 含 `complaint_cases` → 测试 fixture 每次清空
- KG 测试含 `TestComplaintCaseSync` → Phase 1 扩展后需更新

---

## 12. 差距清单

| 差距 | 当前状态 | 目标状态 | 阶段 |
|---|---|---|---|
| 无状态机和审核流程 | 无 review_status | 10 状态状态机 | P1 |
| 无脱敏机制 | raw_content 直接暴露 | 多层脱敏+审计 | P2 |
| 无质量评分 | 无 | 百分制 + 门槛 | P2 |
| 无去重框架 | 仅 source_url 查询 | 5 层去重 | P2 |
| 采集覆盖不足 | 仅 4 省 (含 2 占位) | 甘肃/陕西/宁夏/青海/新疆 | P3 |
| 无安全采集框架 | verify=False | 域名白名单+响应限制 | P3 |
| 无 LLM 结构化抽取 | 正则+关键词 | Pydantic Schema + 证据链 | P4 |
| 无审核工作台 | 管理员手动 curl | 前端审核界面 | P5 |
| 无检索系统 | 仅 KG text search | PostgreSQL FTS + pgvector | P6 |
| complaint_cases → KG 非自动 | 手动 /api/kg/seed | 自动同步 | P1 |
| 采集数据未进入 RAG | unreviewed 被排除 | 审核后自动参与 | P5/P6 |
| 无规则候选管理 | rule_miner 写死 6 种 | case_rule_candidates 表 | P7 |
| 前端无管理界面 | 无采集/审核/来源 UI | 完整管理界面 | P5 |

---

## 13. 后续迁移风险

1. **complaint_cases 字段扩展** — 新增 NOT NULL 列的 migration 需 default 值
2. **旧数据回填** — complaint_cases 为空所以无风险; kg_nodes 的 20 条硬编码案例需保持不变
3. **API 兼容** — 旧 `/api/crawler/*` 端点需保留作为过渡; 新 `/api/cases/*` 端点需逐步引入
4. **权限平滑过渡** — 新增 `case:*` 权限需同时授予现有 admin 角色
5. **前端无破坏性变更** — KGCases.tsx 继续使用 KG API; 新增页面不应删除现有页面

---

## Codex 验收请求

READY_FOR_CODEX_PHASE_0_AUDIT

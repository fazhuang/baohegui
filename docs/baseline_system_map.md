# 包合规（baohegui）系统基线模块清单

> **生成日期**: 2026-07-05
> **基线范围**: 完整代码库扫描，仅记录代码事实，禁止优化/重构/修复
> **验证方式**: 逐一文件读取 + 逐一签名验证

---

## 1. 真实模块枚举

### 1.1 engine/ — 12 个源文件

| 文件 | 主要类/函数 | 模块级单例 |
|------|-----------|----------|
| `shared_types.py` | `Violation`, `RuleEngineResult`, `TrafficLight`(enum), `RoutingResult`, `BiasFinding`, `ParameterBiasResult` | 无 |
| `routing.py` | `ComplianceRouter` — `route(self, budget: Optional[float]=None, procurement_method: str="", project_type: str="") -> RoutingResult` | `compliance_router = ComplianceRouter()` |
| `rule_engine.py` | `RuleEngine`, `LiveRuleMonitor`, `RuleDefinition` | `rule_engine = RuleEngine()` (行 1156)；导入时启动 `LiveRuleMonitor` 线程 (行 1158-1162) |
| `parameter_bias.py` | `ParameterBiasDetector` — `run(self, sections: dict[str, str]) -> ParameterBiasResult` | 无单例（每次 new） |
| `llm_engine.py` | `LLMEngine` — `analyze(...) -> LLMEngineResult`, `ModelRouter`, `OpenAICompatibleProvider`, `OllamaProvider` | `llm_engine = LLMEngine()` |
| `evidence_matcher.py` | `EvidenceMatcher` (全 staticmethod) | `evidence_matcher = EvidenceMatcher()` |
| `fusion.py` | `FusionEngine` — `merge(...) -> ComplianceReport`, `FourWayRiskMerger` — `merge(...) -> MergeResult`, `MergedRiskItem`, `MergeResult` | `fusion_engine = FusionEngine()`, `four_way_merger = FourWayRiskMerger()` |
| `platform_rules.py` | `PlatformRuleEngine` — `get_platform()`, `get_threshold_overrides()`, `get_additional_rules()`, `list_platforms()` | `platform_rule_engine = PlatformRuleEngine()` |
| `semantic_chunking.py` | `SemanticChunkingEngine` — `chunk(...) -> list[dict]`, `SectionAffinityMatrix`, `OverlapManager`, `AffinityGroup`, `OverlapConfig` | 无单例；便捷函数 `chunk_sections()` |
| `template_fingerprint.py` | `TemplateFingerprintDB`, `TemplateFingerprint`, `SectorFingerprints` | `_fingerprint_db: Optional[TemplateFingerprintDB] = None` (懒加载单例) |
| `variable_marker.py` | `VariableMarker` — `mark(...) -> MarkedDocument`, `HeuristicMarker`, `MarkedDocument`, `TextSpan` | `variable_marker = VariableMarker()` |
| `case_state_machine.py` | `CaseStatusStateMachine` (全 staticmethod), `CaseStatus`(enum), `PublishStatus`(enum), `VALID_TRANSITIONS` | 无单例 |

### 1.2 services/ — 28 个源文件

| 文件 | 主要类/函数入口 | 模块级单例 |
|------|---------------|----------|
| `parser.py` | `DocumentParser` — `parse(self, filepath: str) -> ParsedDocument`, `parse_pdf()`, `parse_docx()` | `parser = DocumentParser()` |
| `report_gen.py` | `ReportGenerator` — `generate_html(self, report: ComplianceReport) -> str`, `generate_pdf(self, report: ComplianceReport, output_dir: str="/tmp") -> str` | `report_generator = ReportGenerator()` |
| `excel_exporter.py` | `export_report_to_excel(report_data: dict[str, Any], violations: list[dict[str, Any]]) -> BytesIO`, `build_violation_rows(report_data: dict[str, Any]) -> list[dict[str, Any]]` | 无 |
| `minio_service.py` | `MinioService` — `upload()`, `upload_from_path()`, `download()`, `delete()`, `ensure_bucket()`, `local_path()` (contextmanager) | `minio_service = MinioService()` |
| `rule_sync.py` | `RuleSyncService` — `get_all_rules()`, `sync_from_platform()`, `import_rules()`; `RuleVersionManager` — `snapshot()`, `rollback()` | `rule_sync_service = RuleSyncService()`, `rule_version_manager = RuleVersionManager()` |
| `prompt_manager.py` | `PromptManager` — `get_prompt()`, `render()`, `list_prompts()`, `get_dimension_prompts()` | `prompt_manager = PromptManager()` |
| `knowledge_graph.py` | `KnowledgeGraphService` — 全 staticmethod: `search()`, `build_rag_context()`, `find_regulation_for_rule()`, `find_cases_for_rule()`, `find_similar_cases()`, `seed_builtin_knowledge()`, `sync_complaint_cases()` | `knowledge_graph = KnowledgeGraphService()` |
| `email_service.py` | `send_verification_email(email: str) -> tuple[str, bool]`, `send_password_reset_email(email: str) -> tuple[str, bool]`, `_send_via_resend()`, `_send_via_log()` | 无 |
| `quota_service.py` | `check_quota(db, user_id) -> dict`, `consume_file(db, user_id) -> bool`, `consume_tokens(db, user_id, tokens, cost_yuan) -> bool`, `get_or_create_quota(db, user_id, plan) -> UserQuota` | 无 |
| `rule_miner.py` | `analyze_case(case, db) -> dict`, `analyze_all_unanalyzed(db) -> dict`, `mine_to_candidates(db, case_ids, auto_write) -> dict`, `promote_candidate_to_rule(db, candidate_id, reviewer_id, promoted_rule_id, note) -> dict` | 无 |
| `clause_generator.py` | `ClauseGenerator` — `generate(self, original_text, rule_description, suggestion, project_type, budget, industry) -> dict` | `clause_generator = ClauseGenerator()` |
| `feedback_service.py` | `FeedbackService` — 全 staticmethod: `submit_feedback()`, `get_rule_confidence()`, `get_rules_needing_review()` | `feedback_service = FeedbackService()` |
| `usage_tracker.py` | `LLMUsageTracker` — `record()`, `record_call()`, `get_stats()`, `get_recent()`, `get_by_file()`, `get_by_user()`, `get_failures()` | `usage_tracker = LLMUsageTracker()` |
| `browser_crawler.py` | `crawl_shaanxi_with_playwright() -> list[dict]`, `crawl_shaanxi() -> dict`, `crawl_with_scrapling(url, province) -> int` | 无 |
| `crawler_service.py` | `crawl_all() -> dict`, `crawl_ccgp_list()`, `crawl_ccgp_detail()`, `_save_case()`, `query_cases()`, `count_cases()` | 无 |
| `mof_crawler.py` | `fetch_gks_list(fetcher) -> list[dict]`, `fetch_ccgp_gg_list(fetcher) -> list[dict]` | 无 |
| `sync_scheduler.py` | `SyncScheduler` — `start()`, `stop()`, `sync()`, `scrape_cases()`, `get_status()`, `get_history()` | `sync_scheduler = SyncScheduler(...)` |
| `announcement_service.py` | `seed_announcements(db: Session) -> int` | 无 |
| `case_extraction.py` | `CaseExtractionService` — 全 staticmethod: `extract(case, db) -> dict`, `extract_batch(db, case_ids, limit) -> dict` | `case_extraction = CaseExtractionService()` |
| `crawl_job_store.py` | `CrawlJobStore` — 全 staticmethod: `create_job()`, `create_item()`, `complete_item()`, `complete_job()`, `get_recent_jobs()`, `get_job_items()`, `get_last_scrape_status()`, `get_job_detail()` | `crawl_job_store = CrawlJobStore()` |
| `dedup_service.py` | `DedupService` — 全 staticmethod: `compute_hash()`, `find_duplicates()`, `check_before_save()`, `bulk_dedup_check()` | `dedup_service = DedupService()` |
| `kg_projection.py` | `KGProjectionService` — 全 staticmethod: `project_case()`, `unproject_case()`, `project_all_published()`, `remove_unpublished()` | `kg_projection = KGProjectionService()` |
| `parse_contract.py` | `parse_ccgp_list_html()`, `parse_ningxia_list_html()`, `parse_shaanxi_list_html()`, `parse_mof_list_html()`, `parse_detail_html()`, `extract_field()`, `extract_decision_type()`, `_compute_completeness()` | 无 |
| `query_expansion.py` | `expand_query(query_text, tags, max_terms) -> str`, `expand_query_text(query_text, tags) -> str` | 无 |
| `safe_fetcher.py` | `SafeFetcher` — `get(url, source) -> str`, `fetcher_for_source(source) -> SafeFetcher`, `SafeFetchError`, `FetchErrorType`(enum) | 无 |
| `semantic_reranker.py` | `rerank_merged_results(nodes, query, tags, top_k) -> list[dict]` | 无 |
| `source_health_service.py` | `update_source_health()`, `get_all_source_health()`, `get_source_health()`, `ensure_all_sources_exist()`, `compute_health_status()`, `_record_daily_snapshot()` | 无 |
| `task_status_aggregator.py` | `aggregate_job_status(source_statuses, task_errors, total_saved) -> str`, `SourceStatus`(enum), `JobStatus`(enum) | 无 |

### 1.3 api/ — 14 个路由模块

| 文件 | 前缀 | 真实端点 | 认证依赖 |
|------|------|---------|---------|
| `auth.py` | `/api/auth` | `POST /login`, `POST /register`, `POST /send-verification`, `POST /verify-email`, `POST /forgot-password`, `POST /reset-password`, `GET /me` | 公开(6) + `Depends(get_current_user)`(1, /me) |
| `upload.py` | `/api/upload` | `POST /`, `GET /{file_id}/status` | `Depends(get_current_user)`(2); status 端点后接内联 `if db_file.user_id != int(user["sub"]) and user.get("role") != "admin" → 403` |
| `check.py` | `/api/check` | `POST /{file_id}`, `GET /{file_id}/status` | `Depends(get_current_user)`(2); POST /{file_id} 额外 `assert_resource_access(db, db_file, user)`; GET /{file_id}/status 后接内联 owner/admin 判断 |
| `report.py` | `/api/report` | `GET /{report_id}`, `GET /{report_id}/pdf`, `GET /{report_id}/export`, `GET /list/`, `POST /feedback`, `GET /feedback/rules-needing-review`, `POST /generate-clause` | `Depends(get_current_user)`(6) + `Depends(PermissionService.require_permission(Permission.RULES_READ))`(1, /feedback/rules-needing-review)。GET /{report_id}, GET /{report_id}/pdf, GET /{report_id}/export, POST /feedback 认证后额外 `assert_resource_access` |
| `rules.py` | `/api/rules` | `POST /reload`, `GET /engine/status`, `GET /platforms`, `GET /platforms/{platform_id}`, `GET /platform/list`, `GET /platform/{rule_id}`, `POST /platform`, `PUT /platform/{rule_id}`, `DELETE /platform/{rule_id}`, `POST /platform/{rule_id}/toggle`, `POST /import`, `GET /sync/status`, `POST /sync/run`, `GET /sync/history`, `GET /sync/diff`, `GET /versions`, `POST /versions/rollback`, `GET /effectiveness`, `POST /batch/toggle`, `GET /stats` | `Depends(get_current_user)`(11: /engine/status, /platforms, /platforms/{platform_id}, /platform/list, /platform/{rule_id}, /sync/status, /sync/history, /sync/diff, /versions, /effectiveness, /stats) + `Depends(require_admin)`(9: /reload, /platform, /platform/{rule_id}, /platform/{rule_id}/toggle, /import, /sync/run, /versions/rollback, /batch/toggle, DELETE /platform/{rule_id}) |
| `admin.py` | `/api/admin` | `GET /users`, `POST /users`, `PUT /users/{user_id}`, `DELETE /users/{user_id}`, `GET /audit`, `GET /compare`, `GET /billing/threshold`, `PUT /billing/threshold`, `GET /billing/status` | `Depends(require_admin)`(9) |
| `announcements.py` | `/api/announcements` | `GET ""` | 公开，无认证依赖 |
| `categories.py` | `/api/categories` | `GET /`, `GET /groups`, `GET /groups/{group_id}/categories` | 公开，无认证依赖 |
| `knowledge_graph.py` | `/api/kg` | `GET /search`, `GET /related/{node_id}`, `GET /regulation/{rule_id}`, `GET /cases/{rule_id}`, `GET /similar-cases`, `GET /template/{rule_id}`, `GET /rag-context`, `GET /stats`, `POST /seed`, `PUT /node/{node_id}/audit`, `GET /nodes/needing-review`, `POST /node`, `PUT /node/{node_id}`, `DELETE /node/{node_id}`, `POST /edge` | `Depends(get_current_user)`(8: /search, /related/{node_id}, /regulation/{rule_id}, /cases/{rule_id}, /similar-cases, /template/{rule_id}, /rag-context, /stats) + `Depends(require_admin)`(7: /seed, /node/{node_id}/audit, /nodes/needing-review, /node, /node/{node_id}, DELETE /node/{node_id}, /edge) |
| `crawler.py` | `/api/crawler` | `POST /trigger`, `GET /source-health`, `GET /status`, `GET /jobs`, `GET /jobs/{job_id}`, `GET /cases`, `GET /cases/{case_id}`, `POST /analyze`, `GET /stats` | `Depends(require_admin)`(4: /trigger, /jobs, /jobs/{job_id}, /analyze) + `Depends(get_current_user)`(5: /source-health, /status, /cases, /cases/{case_id}, /stats) |
| `stats.py` | `/api/stats` | `GET /dashboard` | `Depends(PermissionService.require_permission(Permission.STATS_DASHBOARD))` |
| `member.py` | `/api/member` | `GET /dashboard` | `Depends(get_current_user)` |
| `case_review.py` | `/api/admin/cases` | `GET /review-queue`, `GET /review-queue/stats`, `GET /{case_id}`, `PUT /{case_id}`, `POST /review`, `POST /dedup-check`, `POST /bulk-dedup`, `GET /public/list`, `GET /public/{case_id}` | `Depends(require_admin)`(7: /review-queue, /review-queue/stats, /{case_id} GET+PUT, /review, /dedup-check, /bulk-dedup) + `Depends(get_current_user)`(2: /public/list, /public/{case_id}) |
| `candidate_rules.py` | `/api/admin/candidate-rules` | `GET ""`, `GET /stats`, `GET /{candidate_id}`, `POST /review` | `Depends(require_admin)`(4) |

### 1.4 models/ — 10 个模型文件

| 文件 | 模型 | 所属 Base |
|------|------|---------|
| `document.py` | `UploadedFile`, `DocumentSection`, `ComplianceReport` | `document.Base` |
| `user.py` | `User` | `document.Base` |
| `rule.py` | `Rule`, `RuleMapping`, `RuleVersion` | 文件内本地 `Base` |
| `candidate_rule.py` | `CandidateRule` | 文件内本地 `Base` |
| `crawl_job.py` | `CrawlJob`, `CrawlJobItem` | 文件内本地 `Base` |
| `crawl_source_health.py` | `CrawlSourceHealth`, `DailyHealthSnapshot` | `document.Base` |
| `knowledge_graph.py` | `KGNode`, `KGEdge` | `document.Base` |
| `complaint_case.py` | `ComplaintCase` | `document.Base` |
| `subscription.py` | `UserQuota` | `document.Base` |
| `announcement.py` | `Announcement` | `document.Base` |

**当前代码事实**: 代码库使用 5 个独立 `declarative_base()` (document.Base, rule.py 本地 Base, candidate_rule.py 本地 Base, crawl_job.py 本地 Base, audit.AuditBase)。所有模型表通过显式 `ForeignKey` 约束但无 SQLAlchemy `relationship()` 声明。`init_db()` 逐个调用各 Base 的 `create_all()`，存在冗余调用 (AnnouncementBase, ComplaintCaseBase 重复调用)。Alembic `env.py` 手动合并 6 个 Base 到 `combined_metadata`，但未显式加载 `SubscriptionBase`。

### 1.5 core/ — 5 个文件

| 文件 | 核心输出 |
|------|---------|
| `config.py` | `Settings(BaseSettings)` — 55 字段，前缀 `BHG_`，模块级单例 `settings`。**导入时修改 `os.environ`**（第 9-47 行）进行 Vercel/Railway 检测 |
| `security.py` | `hash_password()`, `verify_password()`, `create_access_token()`, `decode_token()`, `get_current_user()`, `require_admin()`, `assert_resource_access()`, `get_current_user_id()` |
| `permissions.py` | `Permission` 枚举 (16 个权限), `PermissionService` 类 (RBAC), `ROLE_PERMISSIONS` 映射 |
| `audit.py` | `AuditService` — 独立引擎 + Session，`log()` 吞异常返回 None，`query()` 支持按 user_id 过滤 |
| `metrics.py` | Prometheus 指标 — HTTP 请求、LLM 调用、合规检查、文件上传 |

### 1.6 db/ — 数据库层

| 路径 | 说明 |
|------|------|
| `database.py` | `engine` (pool_pre_ping=True), `SessionLocal` (sessionmaker), `get_db()` 生成器, `init_db()` |
| `migrations/env.py` | Alembic 配置, 手动合并 6 个 Base metadata |
| `migrations/versions/` | 8 个迁移版本 (20260602 → 20260621) |

---

## 2. 真实函数签名（逐一验证）

### engine/ 公开入口

```
ComplianceRouter.route(self, budget: Optional[float] = None, procurement_method: str = "", project_type: str = "") -> RoutingResult
RuleEngine.__init__(self, rules_dir: str | Path | None = None, industry: str | None = None, industries: list[str] | None = None)
RuleEngine.run(self, sections: dict[str, str], full_text: str = "", marked_doc: Any | None = None) -> RuleEngineResult
RuleEngine.check_sections(self, parsed_sections: dict[str, str] | None = None, full_text: str = "") -> list[Violation]
RuleEngine.check_keywords(self, sections: dict[str, str], marked_doc: Any | None = None) -> list[Violation]
RuleEngine.check_forbidden_words(self, sections: dict[str, str], marked_doc: Any | None = None) -> list[Violation]
RuleEngine.check_format_keywords(self, sections: dict[str, str]) -> list[Violation]
RuleEngine.set_active_industries(self, industries: list[str]) -> dict[str, int]
RuleEngine.load_industry_rules(self, industry: str) -> int
RuleEngine.reload(self) -> None
RuleEngine._load_rules(self, industry: str | None = None) -> None
RuleEngine._load_compliance_rules(self) -> int
ParameterBiasDetector.run(self, sections: dict[str, str]) -> ParameterBiasResult
LLMEngine.analyze(self, sections: dict[str, str], rule_violations: list[Violation] | None = None, file_id: Optional[int] = None, user_id: Optional[int] = None, target_section_types: set[str] | None = None, marked_doc: Any | None = None, industry_descriptions: str = "", kg_context: Optional[str] = None) -> LLMEngineResult
EvidenceMatcher.best_match(evidence: str, full_text: str, max_edit: int = 2, min_similarity: float = 0.85) -> dict  # @staticmethod
EvidenceMatcher.exact_match(evidence: str, full_text: str) -> Optional[dict]  # @staticmethod
EvidenceMatcher.fuzzy_match(evidence: str, full_text: str, max_edit: int = 2, min_similarity: float = 0.85) -> Optional[dict]  # @staticmethod
FusionEngine.merge(rule_result: RuleEngineResult, llm_result: Optional[LLMEngineResult] = None, bias_violations: Optional[list[Violation]] = None, file_name: str = "", check_time: str = "") -> ComplianceReport  # @staticmethod
FusionEngine.deduplicate(rule_violations: list[Violation], llm_violations: list[LLMViolation]) -> tuple[list[Violation], list[LLMViolation]]  # @staticmethod
FusionEngine.calculate_total_score(rule_result: RuleEngineResult, llm_result: Optional[LLMEngineResult] = None) -> dict  # @staticmethod
FourWayRiskMerger.merge(self, routing_result: Optional[RoutingResult] = None, rule_engine_result: Optional[RuleEngineResult] = None, parameter_bias_result: Optional[ParameterBiasResult] = None, llm_result: Optional[LLMEngineResult] = None, parse_quality: str = "ok") -> MergeResult
```

### services/ 公开入口

```
DocumentParser.parse(self, filepath: str) -> ParsedDocument
DocumentParser.parse_pdf(self, filepath: str) -> ParsedDocument
DocumentParser.parse_docx(self, filepath: str) -> ParsedDocument
ReportGenerator.generate_pdf(self, report: ComplianceReport, output_dir: str = "/tmp") -> str
ReportGenerator.generate_html(self, report: ComplianceReport) -> str
export_report_to_excel(report_data: dict[str, Any], violations: list[dict[str, Any]]) -> BytesIO
MinioService.upload(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> str
MinioService.upload_from_path(self, object_key: str, file_path: str, content_type: str = "application/octet-stream") -> str
MinioService.download(self, object_key: str, target_path: str) -> str
MinioService.delete(self, object_key: str) -> None
MinioService.local_path(self, storage_path: str)  # contextmanager
KnowledgeGraphService.build_rag_context(db: Session, rule_id: str, violation_desc: str = "", max_regulations: int = 3, max_cases: int = 3) -> list[dict]  # @staticmethod
KnowledgeGraphService.search(db: Session, query: str, ...) -> tuple  # @staticmethod
async send_verification_email(email: str) -> tuple[str, bool]
async send_password_reset_email(email: str) -> tuple[str, bool]
check_quota(db: Session, user_id: int) -> dict
consume_file(db: Session, user_id: int) -> bool
consume_tokens(db: Session, user_id: int, tokens: int, cost_yuan: float = 0.0) -> bool
analyze_case(case: ComplaintCase, db: Session) -> dict
mine_to_candidates(db: Session, case_ids: Optional[list[int]] = None, auto_write: bool = True) -> dict
```

---

## 3. 规则资产枚举

| 路径 | 文件数 | 说明 |
|------|--------|------|
| `rules/compliance_rules.json` | 1 | 140KB, 40+ 结构化规则 |
| `rules/base_rules.json` | 1 | 20KB, 基础法规规则 |
| `rules/platform_rules.json` | 1 | 10KB, 平台规则代码映射 |
| `rules/forbidden_words.json` | 1 | 31KB, 禁用词库 |
| `rules/parameter_bias_rules.json` | 1 | 21KB, 参数倾向检测规则 |
| `rules/project_categories.json` | 1 | 16KB, 项目分类 |
| `rules/section_affinity.json` | 1 | 5KB, 章节亲和度 |
| `rules/template_fingerprints.json` | 1 | 1.6MB, 模板指纹库 |
| `rules/manifest.json` | 1 | 3KB, 规则清单 |
| `rules/prompts/` | 11 个文件 | LLM prompt 模板 |
| `rules/industry/` | 18 个文件 | 行业细分规则 |
| `rules/platforms/` | 5 个文件 | 平台规则 (甘肃/广东/江苏/四川/浙江) |
| `rules/versions/` | 33 个 `rules_*.json` 文件 | 规则版本快照 |

---

## 4. 基础设施

| Docker Compose 服务 | 镜像 | CPU 限制 | 内存限制 | 重启策略 |
|---------------------|------|---------|---------|---------|
| nginx | nginx:alpine | 0.5 | 256M | unless-stopped |
| backend | ./backend/Dockerfile | 1.0 | 2G | unless-stopped |
| frontend | ./frontend/Dockerfile | 0.5 | 512M | unless-stopped |
| db | postgres:16-alpine | 1.0 | 1G | unless-stopped |
| minio | minio/minio:latest | 0.5 | 512M | unless-stopped |
| crawler | ./backend/Dockerfile | 0.5 | 512M | no (仅手动/调度触发) |
| certbot | certbot/certbot:latest | - | - | profile: certbot |
| playwright | ./tests/playwright/Dockerfile | - | - | profile: test |

**共 8 个服务** (6 个默认 + 2 个 profile)，非 7 个。

---

## 5. 测试基线

- **测试文件数**: 42
- **测试函数/方法数**: 845
- **测试分组**: `tests/` (27 文件), `tests/security/` (14 文件), `tests/eval/` (1 文件)

---

## 6. 数据模型声明基类

代码中 `declarative_base()` 调用位置 (通过 `rg -n "declarative_base" backend/app` 验证)：

| # | 文件 | 变量名 |
|---|------|--------|
| 1 | `backend/app/models/document.py:9` | `Base` |
| 2 | `backend/app/models/rule.py:8` | `Base` |
| 3 | `backend/app/models/candidate_rule.py:15` | `Base` |
| 4 | `backend/app/models/crawl_job.py:16` | `Base` |
| 5 | `backend/app/core/audit.py:15` | `AuditBase` |

**共 5 个独立 Base**，非 6 个。

---

## 7. 前端基线

### 路由: 35 条定义 (单一源 `routes/routeConfig.tsx`，sed 统计首 330 行中 `path:` 数量)
- 3 公开, 12 条仅 admin (rules 5条 + manage 3条 + reports/feedback + announcements/manage), 16 条 admin+user, 4 重定向
- 6 条路由指向 `ComingSoonPage` (reports/feedback, announcements 2条, account 2条, rules/industry)

### 状态: 3 个 Zustand store
- `authStore` — user, loading, error; login/register/restoreSession/logout/hasPerm/isAdmin/role
- `menuStore` — items, groups; 从 routeConfig 派生
- `permissionStore` — permissions: string[]; hasPermission/hasAnyPermission

### API: 69 个函数 (services/api.ts，计数口径: `rg -c '^export async function '`)
- HTTP 客户端: baseURL `/api`, timeout 300s, localStorage Bearer token 注入
- 401 拦截器: 清除 localStorage token → `window.location.href = '/login'` (硬重定向)
- 无 token 刷新机制

### 权限模型
- `undefined` → 公开访问
- `[]` → 已认证但禁止 (403)
- `['admin']` → 仅管理员
- `['admin', 'user']` → 任何已登录用户

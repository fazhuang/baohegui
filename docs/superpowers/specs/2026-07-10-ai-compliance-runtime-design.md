# AI 合规执行内核架构升级 — 设计规格书

**日期**: 2026-07-10
**状态**: 设计中
**范围**: Phase 5–10

---

## 1. 目标

将包合规系统从"业务功能型审查系统"升级为"可编排、可审计、可重放、可治理、可扩展的 AI 合规执行 Runtime"。

## 2. 核心原则

1. **第一性原理** — 每个模块必须回答：输入是什么、处理逻辑是什么、输出是什么、如何验证、如何回放、如何审计、如何失败恢复
2. **不重建系统** — 不推翻现有 FastAPI / Worker / Rule Engine / LLM Engine / PolicyKernel / Replay Engine
3. **不抽象自嗨** — 每个架构概念落到代码路径、数据模型、API、测试、文档
4. **不绕过 PolicyKernel** — 所有最终审查结论必须经过 PolicyKernel
5. **不绕过 Replay** — 所有执行链必须可重放
6. **Feedback 隔离** — Feedback 只能进入 Candidate / Policy 审批路径

## 3. 关键架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| DAG 并行度 | 轻度并行 — 仅 RULE_CHECK ∥ LLM_CHECK | 唯一真实并行缺口；全并行在没有消息队列时是自制调度器反模式 |
| 节点类型区分 | 配置字段，不继承 | 11 种节点只有字段值不同，继承树是空类 |
| Contract 注册 | 集中式，启动时炸 | 手动维护，一目了然；服务起不来而非 log 警告 |
| AuditTrace 演进 | 升级为动态步骤序列，按实际执行顺序 | 不兼容旧格式但完整保留 DAG 信息 |
| Job 队列 | DB 驱动，SELECT FOR UPDATE SKIP LOCKED | 零新依赖，重启不丢 |
| Policy-as-Code | PolicyKernel 的上游输入源 | PolicyKernel 不动，PolicyEvaluator 输出注入 UX/TENANT/PLATFORM 层 |
| 证据/审计存储 | 独立表，证据去重，审计不可变追加 | 边界清晰，hash 去重 |
| API 模式 | 提交返回 job_id，轮询 | 不允许 HTTP 请求内执行完整审查 |

## 4. Phase 5: Execution Graph Runtime

### 4.1 文件清单

```
backend/app/runtime/
    __init__.py
    node_types.py              # NodeType 枚举
    execution_node.py          # ExecutionNode dataclass + RetryPolicy
    execution_graph.py         # ExecutionGraph + build()
    execution_runtime.py       # ExecutionRuntime + 拓扑排序 + 执行
```

### 4.2 ExecutionNode

```python
@dataclass
class ExecutionNode:
    node_id: str                           # 唯一标识
    node_type: NodeType                    # 枚举
    input_schema: dict                     # JSON Schema
    output_schema: dict                    # JSON Schema
    dependencies: list[str]                # 依赖的 node_id 列表
    timeout: float                         # 超时秒数
    retry_policy: RetryPolicy              # max_retries, backoff_seconds, backoff_multiplier
    deterministic: bool                    # RULE_CHECK=True, LLM_CHECK=False
    audit_required: bool                   # 默认 True
    replay_required: bool                  # 默认 True
    execute: Callable                      # 实际执行函数，指向现有引擎
```

### 4.3 11 种标准 NodeType

| NodeType | 包装函数 | 输入 | 输出 |
|---|---|---|---|
| FILE_PARSE | parser.parse() | file_path | ParsedDocument |
| OCR | ocr_pipeline.extract() | file_path | OCRResult |
| TEXT_NORMALIZE | 新增 ~30 行 | ParsedDocument | NormalizedText |
| SECTION_SPLIT | semantic_chunking.chunk() | NormalizedText | Section[] |
| RULE_CHECK | rule_engine.run() | Section[], MarkedDocument | RuleEngineResult |
| LLM_CHECK | llm_engine.analyze() | Section[], RuleEngineResult | LLMResult |
| FUSION | fusion_engine.merge() | RuleEngineResult, LLMResult, BiasResult | MergeResult |
| POLICY_KERNEL | policy_kernel.decide() | DecisionInput | PolicyDecision |
| EVIDENCE_MAPPING | evidence_mapper.locate_many() | LLMResult, OCRResult | EvidenceRecord[] |
| REPORT_BUILD | report_gen.generate() | MergeResult, PolicyDecision | ComplianceReport |
| FEEDBACK_SNAPSHOT | feedback_service.snapshot() | ComplianceReport | FeedbackSnapshot |

### 4.4 DAG 结构

```
FILE_PARSE ──→ OCR
    │            │
    ▼            ▼
TEXT_NORMALIZE  (不阻塞主链)
    │
    ▼
SECTION_SPLIT
    │
    ├──→ RULE_CHECK ──────────────────┐
    │                                  │
    └──→ LLM_CHECK ───→ EVIDENCE_MAPPING
                                       │
                                       ▼
                                     FUSION
                                       │
                                       ▼
                                  POLICY_KERNEL
                                       │
                                       ▼
                                  REPORT_BUILD
                                       │
                                       ▼
                                FEEDBACK_SNAPSHOT
```

唯一的并行点：RULE_CHECK 和 LLM_CHECK 独立消费 SECTION_SPLIT 的输出，无彼此依赖。
FEEDBACK_SNAPSHOT 是叶子节点，失败不影响 job 最终状态（best-effort 语义）。

### 4.5 ExecutionRuntime 执行要点

- 按拓扑序执行节点
- `asyncio.gather()` 调度 RULE_CHECK ∥ LLM_CHECK
- 每个节点输出写入 AuditTrace（动态追加步骤）
- 每个节点生成输入 hash 和输出 hash
- 节点失败记录 NodeFailure 对象（含堆栈、node_id）
- 高风险节点失败不得输出"通过"结论：POLICY_KERNEL 失败 → 整体 FAILED
- OCR 低置信度 → 传递风险标记到下游节点

### 4.6 AuditTrace 升级

从硬编码 8 步序列升级为动态步骤列表：

```python
class AuditTrace:
    steps: list[TraceStep]          # 动态追加，按实际执行顺序
    root_hash: str                  # 初始输入的 hash
    leaf_hash: str                  # 最终输出的 hash

@dataclass
class TraceStep:
    sequence: int
    node_id: str
    node_type: NodeType
    input_hash: str
    output_hash: str
    previous_hash: str              # 链上前一步的 output_hash
    deterministic: bool
    duration_ms: int
    error: str | None
```

## 5. Phase 6: Node Contract Registry

### 5.1 文件清单

```
backend/app/runtime/
    contract_registry.py           # NodeContract + ContractRegistry
    contracts/
        __init__.py                # 集中式注册表 REGISTRY dict
```

### 5.2 NodeContract

```python
@dataclass
class NodeContract:
    node_type: NodeType
    input_schema: dict               # JSON Schema
    output_schema: dict              # JSON Schema
    cacheable: bool
    retryable: bool
    deterministic: bool
    replay_required: bool
    degradable: bool                 # 是否允许降级
    security_level: SecurityLevel    # STANDARD | HIGH | CRITICAL
    execute_fn: Callable             # 实际执行函数引用
```

### 5.3 关键契约规则

| NodeType | SecurityLevel | degradable | deterministic |
|---|---|---|---|
| RULE_CHECK | HIGH | **false** (不可跳过) | true |
| POLICY_KERNEL | **CRITICAL** | **false** (必须最后参与) | true |
| LLM_CHECK | HIGH | true (可降级为仅规则引擎) | false |
| OCR | STANDARD | true | false |

### 5.4 防御层次

1. **启动时** — `ContractRegistry.validate()` 遍历 REGISTRY，校验所有 execute_fn 存在且签名一致。失败 → RuntimeError，服务起不来
2. **构建图时** — `ContractRegistry.validate_graph(graph)` 校验所有节点的 node_type 已注册，节点字段不违反 contract
3. **执行时** — 每个节点执行前后校验输入/输出 schema

### 5.5 禁止事项

- RULE_CHECK 不允许被跳过（degradable=false）
- POLICY_KERNEL 必须最后参与最终结论（degradable=false, 拓扑序强制最后）
- LLM_CHECK 输出不得直接成为最终结论（中间节点，必须经 FUSION → POLICY_KERNEL）
- OCR 低置信度必须传递风险标记（contract 要求 output 含 confidence 字段）

## 6. Phase 7: Commercial Job Orchestrator

### 6.1 文件清单

```
backend/app/runtime/
    job_models.py                  # JobStatus 枚举, Job 数据类
    job_store.py                   # JobStore — PostgreSQL 驱动
    job_orchestrator.py            # JobOrchestrator
```

### 6.2 Job 状态机

```
PENDING ──→ RUNNING ──→ SUCCEEDED
                │
                ├──→ NODE_FAILED ──→ RUNNING  (retry_node)
                │         │
                │         └──→ FAILED  (重试耗尽)
                │
                ├──→ CANCELLED
                │
                └──→ FAILED  (未捕获异常)

SUCCEEDED ──→ REPLAYING ──→ SUCCEEDED  (验证重放)
```

### 6.3 DB Schema

```sql
CREATE TABLE jobs (
    job_id        TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    file_id       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'PENDING',
    current_node  TEXT,
    graph_json    JSONB NOT NULL,
    error_json    JSONB,
    result_json   JSONB,
    trace_json    JSONB,
    replay_from   TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    completed_at  TIMESTAMPTZ
);
CREATE INDEX idx_jobs_tenant_status ON jobs(tenant_id, status);
CREATE INDEX idx_jobs_status_created ON jobs(status, created_at);
```

### 6.4 JobOrchestrator

```python
class JobOrchestrator:
    def __init__(self, job_store: JobStore, runtime: ExecutionRuntime):
        self._running: dict[str, asyncio.Task] = {}
        self.max_concurrent_per_tenant: int = 3

    async def submit(file_id, options) -> JobRef
    async def cancel(job_id)
    async def retry_node(job_id, node_id)
    async def replay(job_id)
    async def status(job_id) -> JobStatus
    async def _run(job_id)                              # asyncio.create_task()
    async def _on_step(job_id) -> callback              # 更新 current_node
    def _check_tenant_quota(tenant_id)                  # 复用现有 quota_service
    def _check_concurrency(tenant_id)                   # 同租户并行上限
```

### 6.5 API 改动

```
POST /api/check/{file_id}   → 返回 {"job_id": "...", "status": "PENDING"}
GET  /api/jobs/{job_id}     → 返回 job 状态 + current_node + error
POST /api/jobs/{job_id}/cancel
POST /api/jobs/{job_id}/retry/{node_id}
POST /api/jobs/{job_id}/replay
```

### 6.6 取消 & 死信

- 取消：`task.cancel()` → CancelledError，httpx 的 LLM 调用会被中断
- 死信：不建独立死信表。重试耗尽后 job 状态 FAILED，error_json 含完整堆栈。管理员从 jobs 表查询 FAILED job 手动重试

## 7. Phase 8: Policy-as-Code Layer

### 7.1 文件清单

```
backend/app/policy/
    __init__.py
    policy_definition.py           # PolicyDefinition model + DB table
    policy_evaluator.py            # PolicyEvaluator
    policy_actions.py              # PolicyAction 枚举
```

### 7.2 与 PolicyKernel 的关系

Policy-as-Code 是 PolicyKernel 的**上游输入源**。PolicyKernel 本身不动：

```
PolicyDefinition[] → PolicyEvaluator.evaluate()
    → PolicyAction[]
    → PolicyKernel.decide() 的 UX/TENANT/PLATFORM 层输入
```

### 7.3 DB Schema

```sql
CREATE TABLE policy_definitions (
    policy_id       TEXT PRIMARY KEY,
    policy_type     TEXT NOT NULL,       -- UX | TENANT | PLATFORM
    scope           TEXT NOT NULL,       -- global | tenant:{id} | industry:{code}
    priority        INT NOT NULL,
    condition       JSONB NOT NULL,      -- 复用 ConditionalExpressionEngine 语法
    action          TEXT NOT NULL,       -- PolicyAction 枚举值
    effective_from  TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    approved_by     TEXT,
    version         INT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### 7.4 PolicyAction 枚举

```python
class PolicyAction(str, Enum):
    # 风险升级 — 只能升级不能降级
    ESCALATE_TO_YELLOW = "escalate_to_yellow"
    ESCALATE_TO_RED = "escalate_to_red"

    # 审查行为
    REQUIRE_HUMAN_REVIEW = "require_human_review"
    SKIP_LLM_FOR_INDUSTRY = "skip_llm_for_industry"

    # 规则调整
    ADD_EXTRA_RULES = "add_extra_rules"
    WEAKEN_RULE_THRESHOLD = "weaken_rule_threshold"

    # 报告
    SUPPRESS_FINDING_IN_REPORT = "suppress_finding_in_report"
    ADD_TENANT_DISCLAIMER = "add_tenant_disclaimer"
```

注意：没有 `DISABLE_HARD_RULE` — policy 不可关闭硬规则。

### 7.5 PolicyEvaluator

- 复用现有 `ConditionalExpressionEngine`（AND/OR/NOT/比较运算），不做新 DSL
- ~60 行，评估所有匹配 PolicyDefinition，输出 PolicyAction 列表
- 冲突裁决：同类型 policy 按 priority 字段排序，数字小的胜出
- ESCALATE_TO_RED 和 ESCALATE_TO_YELLOW 共存 → RED 胜

### 7.6 禁止事项（通过设计保证）

1. ~~在业务代码中散落 if tenant_policy~~ → 统一入口 PolicyEvaluator.evaluate()
2. ~~在 LLM prompt 中隐式塞策略~~ → PolicyAction 在 PolicyKernel 层参与裁决，不进 prompt
3. ~~让 policy 直接关闭 hard rule~~ → 无 DISABLE_HARD_RULE 枚举值

## 8. Phase 9: Evidence Lake & Audit Lake

### 8.1 文件清单

```
backend/app/audit/
    __init__.py
    audit_models.py                # AuditEvent, EvidenceRecord, EvidenceLink
    evidence_lake.py               # EvidenceLake
    audit_lake.py                  # AuditLake + AuditQueryService
```

### 8.2 DB Schema

```sql
CREATE TABLE evidence_records (
    evidence_hash    TEXT PRIMARY KEY,
    evidence_text    TEXT NOT NULL,
    source_file      TEXT NOT NULL,
    page             INT,
    bbox             JSONB,
    block_ids        TEXT[],
    confidence       FLOAT,
    parser_version   TEXT NOT NULL,
    ocr_version      TEXT NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE evidence_links (
    id               SERIAL PRIMARY KEY,
    evidence_hash    TEXT NOT NULL REFERENCES evidence_records(evidence_hash),
    finding_id       TEXT NOT NULL,
    job_id           TEXT NOT NULL REFERENCES jobs(job_id),
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE audit_events (
    event_id         TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL REFERENCES jobs(job_id),
    node_id          TEXT NOT NULL,
    node_type        TEXT NOT NULL,
    sequence         INT NOT NULL,
    input_hash       TEXT NOT NULL,
    output_hash      TEXT NOT NULL,
    previous_hash    TEXT NOT NULL,
    actor            TEXT NOT NULL DEFAULT 'system',
    tenant_id        TEXT NOT NULL,
    parser_version   TEXT,
    ocr_version      TEXT,
    engine_version   TEXT,
    error            TEXT,
    duration_ms      INT NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_audit_events_job ON audit_events(job_id, sequence);
CREATE INDEX idx_audit_events_tenant ON audit_events(tenant_id, created_at);
CREATE INDEX idx_evidence_links_job ON evidence_links(job_id);
CREATE INDEX idx_evidence_links_finding ON evidence_links(finding_id);
```

### 8.3 查询 API

```
GET /api/audit/jobs/{job_id}/chain       — 完整审计链 + hash 链校验
GET /api/audit/reports/{report_id}/evidence  — 某报告的全部证据
GET /api/audit/findings/{finding_id}/evidence — 某发现的具体证据
```

### 8.4 安全约束

- evidence_records 只存证据片段（几十字），不存完整文档
- audit_events 只存 hash，不存文档内容
- 完整文档在 MinIO，通过 source_file 引用，按原权限访问
- 日志不得泄露完整招标文件正文

## 9. Phase 10: Commercial Readiness Hardening

### 9.1 文件清单

```
tests/commercial/
    __init__.py
    test_isolation.py              # 1-4 安全边界
    test_replay_integrity.py       # 5-7 可重放性
    test_resilience.py             # 8-10 韧性
docs/commercial_readiness_report.md
```

### 9.2 验证矩阵

#### 安全边界（4 项 — 必须全部通过）

| # | 验证项 | 测试方法 |
|---|---|---|
| 1 | 多租户隔离 | 租户 A 查询租户 B 的 job_id，断言 404 |
| 2 | Runtime 绕过 | 未注册 NodeType → ContractViolationError |
| 3 | PolicyKernel 绕过 | 绕过 POLICY_KERNEL 节点 → audit_events 链不完整，audit_incomplete=true |
| 4 | Feedback 隔离 | Feedback 产物注入 pipeline → ContractViolationError |

#### 可重放性（3 项）

| # | 验证项 | 测试方法 |
|---|---|---|
| 5 | Replay 一致性 | 同 job replay 3 次，audit_events 序列一致，LLM output_hash 可不同但 final_decision 一致 |
| 6 | LLM 非确定性边界 | mock LLM 下 hash 一致；真实 LLM 下 decision_hash 一致 |
| 7 | OCR 低置信度 | OCRResult(confidence=0.3)，验证 finding 置信度降低，final_risk_level ≠ PASS |

#### 韧性（3 项）

| # | 验证项 | 测试方法 |
|---|---|---|
| 8 | Worker 中断恢复 | task.cancel() → 重试 → 完成，中断前后输入 hash 一致 |
| 9 | 50MB 边界 | 45MB 正常，55MB → FileSizeExceededError |
| 10 | 审计链完整性 | 每个 node_type 至少出现一次，hash 链无断裂，根 hash 可追溯 |

### 9.3 报告输出

商用内核架构基线验证报告，包含：
- 通过计数 / 阻塞项列表
- 架构防御能力评级：PASS / CONDITIONAL / FAIL
- 已知风险清单（影响范围 + 缓解措施）
- 未覆盖项（含不需要的原因：如高并发、网络分区、GPU 故障切换）

## 10. 测试要求

- 所有 Phase 5-9 单元测试放在 `tests/runtime/`，`tests/policy/`，`tests/audit/`
- Phase 10 商用验证放在 `tests/commercial/`
- 原有测试（60+ 文件）不得破坏
- 每个新增模块至少一个 `test_*.py`

## 11. 产出物清单

### Phase 5
- `backend/app/runtime/node_types.py`
- `backend/app/runtime/execution_node.py`
- `backend/app/runtime/execution_graph.py`
- `backend/app/runtime/execution_runtime.py`
- `tests/runtime/test_execution_graph.py`
- `tests/runtime/test_execution_runtime.py`
- `docs/runtime/execution_graph_runtime.md`

### Phase 6
- `backend/app/runtime/contract_registry.py`
- `backend/app/runtime/contracts/__init__.py`
- `tests/runtime/test_contract_registry.py`
- `docs/runtime/node_contract_registry.md`

### Phase 7
- `backend/app/runtime/job_models.py`
- `backend/app/runtime/job_store.py`
- `backend/app/runtime/job_orchestrator.py`
- `tests/runtime/test_job_orchestrator.py`
- `docs/runtime/job_orchestrator.md`

### Phase 8
- `backend/app/policy/policy_definition.py`
- `backend/app/policy/policy_evaluator.py`
- `backend/app/policy/policy_actions.py`
- `tests/policy/test_policy_as_code.py`
- `docs/policy/policy_as_code.md`

### Phase 9
- `backend/app/audit/audit_models.py`
- `backend/app/audit/evidence_lake.py`
- `backend/app/audit/audit_lake.py`
- `tests/audit/test_evidence_lake.py`
- `tests/audit/test_audit_chain.py`
- `docs/audit/evidence_audit_lake.md`

### Phase 10
- `tests/commercial/test_isolation.py`
- `tests/commercial/test_replay_integrity.py`
- `tests/commercial/test_resilience.py`
- `docs/commercial_readiness_report.md`

# Evidence Lake & Audit Lake

## 概述

Evidence Lake 和 Audit Lake 是 Runtime 的持久化记录层，分别管理证据片段和不可变审计事件。

## Evidence Lake

### 数据模型

`EvidenceRecord` — 从文档中提取的单个证据片段。只存证据文本（几十字），不存完整文档。完整文档在 MinIO，通过 source_file 引用。

`EvidenceLink` — 将证据关联到 finding 和 job，支持多对多查询。

### DB Schema

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

CREATE INDEX idx_evidence_links_job ON evidence_links(job_id);
CREATE INDEX idx_evidence_links_finding ON evidence_links(finding_id);
```

### 去重

证据按内容 hash 去重。相同文本来自不同文档或不同 finding 时，共用一个 EvidenceRecord 行。

### API

```python
lake = EvidenceLake(db_session_factory)

# 存储
hash = await lake.store("证据文本", "file.pdf", page=3, bbox=(x0,y0,x1,y1))

# 关联
await lake.link(hash, finding_id="f1", job_id="j1")

# 查询
record = await lake.get_by_hash(hash)
records = await lake.get_by_finding("f1")
records = await lake.get_by_job("j1")
```

## Audit Lake

### 数据模型

`AuditEvent` — 审计链上单个节点执行事件。只存 hash，不存文档内容。

### DB Schema

```sql
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
```

### Hash 链校验

`get_chain_validated(job_id)` 返回完整审计链 + 完整性校验结果：

```python
{
    "events": [...],
    "chain_intact": True / False,
    "broken_at": None | <sequence_number>
}
```

链上每个事件的 `previous_hash` 必须匹配前一事件的 `output_hash`。

### API

```python
lake = AuditLake(db_session_factory)

# 记录单条事件
event = await lake.record_event(
    job_id="j1", node_id="n1", node_type="RULE_CHECK",
    sequence=0, input_hash="in", output_hash="out",
    previous_hash="root", tenant_id="t1", duration_ms=100,
)

# 查询
chain = await lake.get_chain("j1")
result = await lake.get_chain_validated("j1")
events = await lake.get_by_tenant("t1", limit=100)
```

## 安全约束

- evidence_records 只存证据片段（<5000 字符），不存完整文档
- audit_events 只存 hash，不存文档内容
- 完整文档在 MinIO，通过 source_file 引用，按原权限访问
- 日志不得泄露完整招标文件正文

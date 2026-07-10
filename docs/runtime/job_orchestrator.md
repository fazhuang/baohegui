# Job Orchestrator

## 概述

JobOrchestrator 管理合规检查任务的全生命周期，使用 asyncio.create_task() 进行后台执行，PostgreSQL 进行持久化。

## 状态机

PENDING → RUNNING → SUCCEEDED
RUNNING → NODE_FAILED → RUNNING (retry_node)
NODE_FAILED → FAILED (重试耗尽)
RUNNING → FAILED (未捕获异常)
RUNNING → CANCELLED
SUCCEEDED → REPLAYING → SUCCEEDED (验证重放)

## API

- `POST /api/check/{file_id}` → `{"job_id": "...", "status": "PENDING"}`
- `GET /api/jobs/{job_id}` → job 状态 + 当前节点 + 错误信息
- `POST /api/jobs/{job_id}/cancel`
- `POST /api/jobs/{job_id}/retry/{node_id}`
- `POST /api/jobs/{job_id}/replay`

## 并发控制

- 同租户最多 3 个并行 job
- 超额提交 → 429 Too Many Requests

## 重试

- 节点失败后可通过 retry_node 从失败节点重试
- 中断前节点输入 hash 与恢复后一致 → 幂等安全

## 死信

不建独立死信表。重试耗尽的 job 标记为 FAILED，error_json 含完整堆栈。管理员可查询 FAILED job 并手动重试。

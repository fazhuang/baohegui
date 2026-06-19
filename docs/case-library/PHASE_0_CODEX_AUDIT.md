# Phase 0 — Codex 基线审计

> 审计时间: 2026-06-18
> 基线提交: `01e4db40`
> 审计对象: `docs/case-library/PHASE_0_BASELINE.md`
> 结论: `PHASE_0_ACCEPTED_WITH_CORRECTIONS`

## 1. 已核验事实

- PostgreSQL 16 容器健康，数据库大小为 12 MB。
- `alembic_version` 为 `8b1e3f95c2d4`。
- `complaint_cases` 为 0 条，仅有主键索引。
- `kg_nodes(node_type='case')` 为 20 条，案例相关边为 12 条。
- 爬虫案例同步到 KG 后使用 `audit_status='unreviewed'`、`trust_level=0.55`。
- RAG 仅接受 `verified` 且 `trust_level >= 0.3` 的案例。
- 前端案例库使用 KG 搜索接口，支持 `limit/offset` 分页，默认排除 `rejected`。

## 2. 基线文档需要纠正的事实

### 2.1 财政部采集当前不可用

`crawler_service.crawl_all()` 在 `httpx.AsyncClient` 上下文退出后，继续把已关闭的
`client` 传给 `fetch_gks_list()` 和 `crawl_ccgp_detail()`。财政部路径会进入异常分支，
不能标记为“已实现且活跃”。

此外，`cases_saved` 在财政部采集之前计算，即使财政部路径修复，统计仍不会包含
`stats["mof"]`。

### 2.2 风险分类不准确

- `verify=False` 是 TLS 证书校验关闭，直接风险是中间人攻击，不等同于 SSRF。
- 当前请求 URL 主要来自硬编码源站，但开启自动重定向且不校验重定向目标，仍存在
  被重定向到非白名单或内网地址的 SSRF 路径。
- httpx 自动重定向存在默认次数上限，不能描述为“无限重定向”；真实缺口是没有逐跳
  校验目标协议、域名和 IP。
- 硬编码 User-Agent 是可维护性和反爬稳定性问题，不是独立安全漏洞。

### 2.3 调度器历史列表描述相反

规则同步 `_history` 已按 `_max_history=50` 截断；案例采集 `_case_history` 没有截断。
需要限制的是 `_case_history`。

### 2.4 权限模型尚未真正落到案例 API

虽然权限枚举中存在 `crawler:read` 和 `crawler:trigger`，`/api/crawler/*` 当前实际使用
的是 `get_current_user` 和 `require_admin`，没有通过细粒度权限依赖执行授权。

### 2.5 运行态不是完整健康状态

审计时 Compose 状态：

- `db`: running / healthy
- `frontend`: running
- `nginx`: running / unhealthy
- `minio`: created，未运行
- `backend`: 容器不存在

因此数据库统计可作为基线，但不能把当前 Compose 环境视为完整可用系统。

## 3. 审计期间发现并修复的回归

运行测试后，真实 `rules/` 再次出现 61 条测试规则、2 个未追踪快照，证明原有
“逐测试 monkeypatch 写方法”的隔离方案不完整：测试会修改模块级规则缓存，后续任一
未隔离写操作即可把整份污染缓存落盘。

已改为全局目录隔离：

- pytest 启动时复制生产规则到 `backend/tests/.test_tmp/rules`。
- 设置 `BHG_RULES_DIR` 指向测试副本。
- `RuleSyncService` 统一读取 `settings.rules_dir`，不再绕过配置直接定位仓库规则目录。
- 已恢复被污染的生产规则文件并删除测试快照。

验证：

- E2E、规则管理审计、版本完整性：61 passed。
- 测试结束后 `rules/` 无 Git 变更，无污染标记。

## 4. Phase 1 前置门槛

Phase 1 不应直接进入大规模状态机和表结构扩展。先完成一个安全采集基础阶段：

1. 修复财政部 closed-client 和 `cases_saved` 统计错误。
2. 恢复 TLS 校验，财政部 URL 改为 HTTPS。
3. 建立来源白名单，并逐跳验证重定向目标和解析后的 IP。
4. 对响应头和流式响应设置字节上限。
5. 普通用户详情接口不返回 `raw_content`、投诉人、被投诉人等未脱敏字段。
6. 为 `source_url` 增加数据库唯一约束或稳定哈希唯一约束。
7. 限制 `_case_history` 长度，并让存在采集错误的任务返回 `PARTIAL`。
8. 为以上路径补充无外网依赖的单元测试和安全测试。

完成这些前置项后，再进入案例状态机、审核流、质量评分和 KG 自动同步。

## 5. 门禁结论

`PHASE_0_ACCEPTED_WITH_CORRECTIONS`

现状盘点的主要数据和架构结论可用，但原文不能直接作为 Phase 1 实施依据，必须以本审计
中的纠正项为准。下一实施任务应为“安全采集基础阶段”，而不是直接扩表。

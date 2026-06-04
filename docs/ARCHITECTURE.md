# 包合规 - 系统架构文档

## 整体架构

```
┌────────────────────────────────────────────────────────┐
│                   前端 (React SPA)                      │
│  Upload Page · Report Page · History Page · Login Page │
└──────────────────────┬─────────────────────────────────┘
                       │ HTTP → http://localhost:3000
┌──────────────────────v─────────────────────────────────┐
│              后端 (FastAPI + Python)                    │
│                                                        │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐   │
│  │ 文件服务  │  │ 解析服务  │  │ 合规检查引擎       │   │
│  │ (MinIO)  │  │ (spaCy   │  │                    │   │
│  │          │  │ +PyMuPDF)│  │ 规则引擎 × LLM引擎  │   │
│  └──────────┘  └──────────┘  └──────────┬─────────┘   │
│                                         │              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┴─────────┐   │
│  │ 报告生成  │  │ 规则同步  │  │ 认证与审计        │   │
│  │(WeasyPrint)│  │ 服务     │  │ (JWT + RBAC)      │   │
│  └──────────┘  └──────────┘  └────────────────────┘   │
└──────────────────────┬─────────────────────────────────┘
                       │
┌──────────────────────v─────────────────────────────────┐
│               数据层                                     │
│  PostgreSQL (元数据/用户/审计/规则)                     │
│  MinIO (原始文件/PDF报告)                                │
└─────────────────────────────────────────────────────────┘
```

## 核心业务流程

```
用户上传文件 → 文档解析(PDF/Word)
    ↓ 章节结构化抽取
    ↓
规则引擎检查 → 章节完整性、关键字、禁用词
    ↓
AI大模型审查 → 排他性、倾向性、隐性壁垒、质疑风险
    ↓
结果融合 → 去重、评分、生成合规报告
    ↓
PDF报告下载 / 前端展示
```

## 双引擎架构

### 规则引擎
- 基于配置化规则 JSON 文件
- 支持热加载
- 覆盖：章节完整性、关键字、禁用词
- 准确率 ≥ 95%

### 大模型语义引擎
- API 调用方式（支持国产大模型 Qwen/DeepSeek）
- 开发阶段使用 mock 模式
- 覆盖：排他性、倾向性、隐性壁垒、质疑风险
- 召回率目标 ≥ 85%
- 成本控制：抽检策略（仅对规则引擎未覆盖或高风险部分调用）

## 数据模型

### uploaded_files
- id, user_id, filename, file_size, file_hash, page_count, storage_path, status, created_at

### document_sections
- id, file_id, section_type, section_number, title, content, page_start, page_end

### compliance_reports
- id, file_id, total_score, section_score, keyword_score, forbidden_score, semantic_score, violation_count, report_data(JSON), created_at

### rules
- id, rule_id, rule_type, target, description, weight, law_ref, suggestion, enabled, version

### rule_mappings
- id, rule_id, platform, platform_code, platform_desc, enabled

## 安全设计

- TLS 传输加密
- JWT Token 认证
- RBAC 权限控制
- 审计日志（操作记录追踪）
- 文件完整性校验（SHA-256）

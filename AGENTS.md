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

## 双引擎架构
规则引擎（轻量、确定）→ 硬性合规检查
  - 章节完整性、关键字存在性、禁用词匹配、格式合规、平台规则对齐
大模型语义引擎（深度、泛化）→ 语义级审查
  - 排他性语义检测、倾向性判断、评分权重合理性、隐性壁垒条款识别、法律合规风险评估、质疑风险预判
  - 成本策略：仅对规则引擎无法覆盖或标记为高风险的段落调用大模型

## 产品边界
✅ 招标文件发布前合规自检
✅ 硬性规则+大模型语义双驱动
✅ 同步公共资源交易平台审查规则
✅ 合规报告生成与下载
✅ 基本权限管理与操作审计
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
├── .Codex/AGENTS.md          # 项目上下文（本文件）
├── backend/                    # Python 后端
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── api/               # API 路由
│   │   │   ├── upload.py      # 文件上传
│   │   │   ├── check.py       # 合规检查
│   │   │   ├── report.py      # 报告
│   │   │   └── rules.py       # 规则管理
│   │   ├── core/              # 核心配置
│   │   │   ├── config.py      # 配置管理
│   │   │   ├── security.py    # 认证权限
│   │   │   └── audit.py       # 审计日志
│   │   ├── engine/            # 合规引擎
│   │   │   ├── rule_engine.py # 规则引擎
│   │   │   ├── llm_engine.py  # 大模型引擎
│   │   │   └── fusion.py      # 结果融合
│   │   ├── models/            # 数据模型
│   │   ├── services/          # 服务层
│   │   │   ├── parser.py      # 文档解析
│   │   │   ├── rule_sync.py   # 规则同步
│   │   │   └── report_gen.py  # 报告生成
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
│   ├── base_rules.json
│   ├── platform_rules.json
│   ├── forbidden_words.json
│   ├── industry/
│   └── prompts/
├── docs/
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## 关键规则路径
规则引擎的规则存储在 rules/ 目录下：
- rules/base_rules.json —— 基础法规规则
- rules/platform_rules.json —— 平台规则映射
- rules/forbidden_words.json —— 禁用词库
- rules/industry/ —— 行业细分规则
- rules/prompts/ —— LLM Prompt 模板

规则热加载：规则更新后无需重启服务，引擎会检测文件变化并自动重新加载。

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

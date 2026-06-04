# 📋 包合规 (baohegui) - 招标文件发布前合规自检系统

## 产品定位

面向招标代理机构和政府采购部门的 **招标文件发布前合规自检工具**。

- 在公共资源交易平台正式发布前完成合规自检，**降低平台拦截和返工风险**
- 规则引擎 + AI 大模型双驱动，**全面识别合规风险**
- 同步公共资源交易平台审查规则，**精准对齐平台拦截标准**
- 帮助非进场项目完成 **合规兜底**，降低质疑投诉法律风险

## 快速开始

### 前提条件

- Docker & Docker Compose
- Node.js 22+（前端开发）
- Python 3.13+（后端开发）
- uv（Python 包管理）

### Docker 部署（推荐）

```bash
# 克隆项目
cd baohegui

# 构建并启动所有服务
docker compose up -d --build

# 访问
# - 前端: http://localhost:3000
# - 后端 API: http://localhost:8000
# - API 文档: http://localhost:8000/docs
# - MinIO 控制台: http://localhost:9001
```

### 本地开发

#### 后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

#### 前端

```bash
cd frontend
npm install
npm run dev
```

## 核心功能

1. **上传招标文件**（PDF/Word，≤50MB）
2. **章节结构化抽取**（自动识别五大必备章节）
3. **双引擎合规检查**
   - 规则引擎：章节完整性、关键字合规、禁用词
   - AI大模型：排他性检测、倾向性判断、隐性壁垒识别
4. **合规报告生成**（含平台规则映射、整改建议、法律风险预警）
5. **规则热加载**（规则更新无需重启）
6. **平台规则同步**（对接公共资源交易平台审查规则）

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.13, FastAPI, SQLAlchemy |
| 前端 | React 19, TypeScript, Vite, Ant Design |
| 存储 | PostgreSQL, MinIO |
| AI | API 接入（国产大模型，默认 mock） |
| 部署 | Docker Compose |

## 产品边界

### ✅ 包含

- 招标文件发布前合规自检
- 硬性规则 + AI大模型语义双驱动
- 同步公共资源交易平台审查规则
- 合规报告生成与下载
- 基本权限管理与操作审计
- Docker 单机部署 / SaaS

### ❌ 不包含

- 投标文件分析与审查
- 为交易中心构建AI审查引擎
- 批量API对接、自动化流水线
- 质疑/投诉答复生成
- 完整的OA/ERP集成

## 目录结构

```
baohegui/
├── .claude/CLAUDE.md       # AI 智能体项目上下文
├── backend/                 # Python 后端
├── frontend/                # React 前端
├── rules/                   # 规则配置
│   ├── base_rules.json      # 基础法规规则
│   ├── platform_rules.json  # 平台规则映射
│   ├── forbidden_words.json # 禁用词库
│   ├── industry/            # 行业规则
│   └── prompts/             # LLM Prompt
├── docs/                    # 文档
├── docker-compose.yml       # Docker 编排
└── README.md
```

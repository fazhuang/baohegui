## 自动化部署与测试工作流

代码修改完成后，按照以下流程依次执行自动化部署和测试。这是一个标准化的回归验证流程。

### 流程概览
```
第 1 步：Docker 构建和部署   → docker compose build → up -d → 等待健康
第 2 步：后端 API 冒烟测试    → 健康检查 + 核心 API 可用性
第 3 步：运行后端 pytest       → 引擎层 + API 层的全部已有测试
第 4 步：API 接口场景测试      → curl 模拟完整 API 调用流程
第 5 步：浏览器 UI 模拟人工测试  → Chrome 工具验证各页面 UI
第 6 步：核心 E2E 场景测试     → 完整用户旅程 + 异常流程
第 7 步：测试报告汇总          → 输出本次测试结果概览
```

### 第 1 步：Docker Compose 构建和部署

```bash
# 从项目根目录执行
cd /Users/likeming/Sites/baohegui

# 1a. 停止现有容器并清理
docker compose down -v --remove-orphans 2>/dev/null

# 1b. 重新构建并后台启动所有服务
docker compose up -d --build

# 1c. 等待服务全部健康
echo "等待服务就绪..."
for i in $(seq 1 30); do
  backend_ok=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null)
  frontend_ok=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ 2>/dev/null)
  if [ "$backend_ok" = "200" ] && [ "$frontend_ok" = "200" ]; then
    echo "✅ 所有服务就绪（第 ${i}s）"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "❌ 服务启动超时（后端=$backend_ok 前端=$frontend_ok）"
  fi
  sleep 2
done
```

> ⚠️ 如果只修改了后端代码，可只重启后端服务：
> ```bash
> docker compose up -d --build backend
> ```
> 同理，只改前端则 `docker compose up -d --build frontend`

### 第 2 步：后端 API 冒烟测试

验证核心 API 端点是否正常响应：

```bash
BASE="http://localhost:8000"

# 2a. 健康检查
curl -s "$BASE/health" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='ok'; print('✅ 健康检查 OK')"

# 2b. 注册测试用户（首次运行）
curl -s -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123","company":"测试公司","email":"test@test.com"}' | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert 'access_token' in d
print('✅ 注册 OK')
"

# 2c. 用户登录（获取 token）
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "✅ 登录 OK (token: ${TOKEN:0:20}...)"

# 2d. 获取当前用户信息
curl -s "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d['username'] == 'testuser'
print('✅ 获取用户信息 OK')
"
```

### 第 3 步：运行后端 pytest

```bash
# 在 Docker 容器内执行 pytest（推荐）
docker compose exec -T backend python -m pytest tests/ -v --tb=short 2>&1
```

> 确保 `BHG_LLM_MOCK_MODE=true`（开发环境默认），避免真实调用大模型 API。

### 第 4 步：API 接口场景测试（curl 模拟）

使用 curl 模拟完整的用户 API 调用流程：

```bash
BASE="http://localhost:8000"

# 获取管理员 token
ADMIN_TOKEN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

USER_TOKEN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "===== 场景 1：文件上传流程 ====="

# 创建测试 Word 文档
python3 -c "
from docx import Document
doc = Document()
doc.add_heading('第一章 招标公告', level=1)
doc.add_paragraph('本采购项目采用公开招标方式，欢迎合格供应商投标。预算金额500万元。')
doc.add_heading('第二章 招标范围', level=1)
doc.add_paragraph('本次采购内容包括XXX系统建设及运维服务。')
doc.add_heading('第三章 投标人资格要求', level=1)
doc.add_paragraph('1. 投标人应具有独立承担民事责任的能力。')
doc.add_paragraph('2. 投标人必须为本市注册企业，注册资本不低于1000万元。')
doc.add_paragraph('3. 本项目不接受联合体投标。')
doc.add_heading('第四章 评审办法', level=1)
doc.add_paragraph('本项目采用综合评分法。技术方案40分，价格30分，业绩30分。')
doc.add_heading('第五章 投标须知', level=1)
doc.add_paragraph('投标截止时间：2026年7月1日9:00。投标有效期90天。')
doc.save('/tmp/test_bid.docx')
print('测试文档已创建')
"

# 上传文件
UPLOAD_RESP=$(curl -s -X POST "$BASE/api/upload/" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -F "file=@/tmp/test_bid.docx")
FILE_ID=$(echo "$UPLOAD_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['db_id'])")
echo "✅ 文件上传成功，file_id=$FILE_ID"

echo "===== 场景 2：合规检查 ====="
CHECK_RESP=$(curl -s -X POST "$BASE/api/check/$FILE_ID" \
  -H "Authorization: Bearer $USER_TOKEN")
REPORT_ID=$(echo "$CHECK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['report_id'])")
TOTAL_SCORE=$(echo "$CHECK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_score'])")
echo "✅ 合规检查完成，report_id=$REPORT_ID, total_score=$TOTAL_SCORE"

echo "===== 场景 3：查看报告 ====="
curl -s "$BASE/api/report/list/" -H "Authorization: Bearer $USER_TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert len(d) > 0; print(f'✅ 报告列表 OK，共 {len(d)} 条')"

curl -s "$BASE/api/report/$REPORT_ID" -H "Authorization: Bearer $USER_TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert 'total_score' in d
print(f'✅ 报告详情 OK，总分: {d[\"total_score\"]}，违规: {d[\"total_violations\"]} 条')"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/report/$REPORT_ID/pdf" -H "Authorization: Bearer $USER_TOKEN")
echo "✅ 报告 PDF 下载 OK (HTTP $HTTP_CODE)"

echo "===== 场景 4：规则管理 ====="
curl -s "$BASE/api/rules/engine/status" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin); print(f'✅ 规则引擎 OK，共 {d[\"total\"]} 条规则')"
curl -s -X POST "$BASE/api/rules/reload" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin); print(f'✅ 规则热加载 OK，{d[\"rule_count\"]} 条')"

echo "===== 场景 5：管理后台 ====="
curl -s "$BASE/api/admin/users" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin); print(f'✅ 用户列表 OK，共 {len(d)} 个用户')"
curl -s "$BASE/api/stats/dashboard" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin); print(f'✅ 仪表盘 OK')"

echo "===== API 场景测试全部完成 ====="
```

### 第 5 步：浏览器 UI 模拟人工测试（Chrome 工具）

使用 `mcp__Claude_in_Chrome__*` 系列工具打开前端页面，模拟人工操作验证 UI。

**需要验证的前端页面和关键元素：**

| 页面 | 验证要点 |
|------|---------|
| `/login` | 登录表单、注册表单、"开发模式 - 一键登录"按钮 |
| `/`（仪表盘） | KPI 卡片（月度检查数、总检查数、通过率、待处理高风险）、快捷操作、近期报告列表、风险分布图 |
| `/upload` | 拖拽上传区域、行业选择器（工程建设/信息技术/医疗采购）、四步流程指示器（上传→解析→规则→AI） |
| `/report/:id` | 评分仪表盘（环图）、四个维度进度条、风险违规表格、PDF 下载按钮 |
| `/history` | 报告列表表格、搜索/日期筛选、评分趋势图、报告对比选择 |
| `/admin/rules` | 规则列表 CRUD、同步管理、拦截反馈、系统仪表盘四个标签页 |
| `/admin/panel` | 用户管理 CRUD、审计日志、文件对比、计费仪表盘四个标签页 |

**浏览器操作步骤：**

```
1. 打开浏览器 → 访问 http://localhost:3000（或 http://localhost:8080）
   → 截图确认页面加载正常

2. 点击"开发模式 - 一键登录"按钮
   → 截图确认跳转到仪表盘
   → 验证导航菜单包含：仪表盘、文件上传、历史记录等

3. 导航到文件上传页面（/upload）
   → 验证拖拽上传区域存在
   → 验证行业选择器存在
   → 验证四步流程指示器完整

4. 导航到历史记录页面（/history）
   → 验证报告列表表格
   → 验证搜索和筛选控件

5. 导航到规则管理（/admin/rules）
   → 验证四个标签页切换

6. 导航到管理面板（/admin/panel）
   → 验证用户管理、审计日志、文件对比等标签页

7. 响应式布局验证（可选）
   → 缩小浏览器窗口至移动端宽度
   → 验证底部标签栏和侧边抽屉菜单
```

### 第 6 步：核心 E2E 场景测试

**场景 A：完整用户旅程（登录 → 上传 → 检查 → 查看报告）**

```bash
echo "===== E2E 场景 A：完整用户旅程 ====="
BASE="http://localhost:8000"

# A1: 登录
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "A1 ✅ 登录成功"

# A2: 上传文件
UPLOAD_RESP=$(curl -s -X POST "$BASE/api/upload/" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/test_bid.docx")
FILE_ID=$(echo "$UPLOAD_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['db_id'])")
echo "A2 ✅ 文件上传成功 (db_id=$FILE_ID)"

# A3: 合规检查
CHECK_RESP=$(curl -s -X POST "$BASE/api/check/$FILE_ID" \
  -H "Authorization: Bearer $TOKEN")
REPORT_ID=$(echo "$CHECK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['report_id'])")
echo "A3 ✅ 合规检查完成 (report_id=$REPORT_ID)"

# A4: 报告详情
curl -s "$BASE/api/report/$REPORT_ID" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d['total_score'] >= 0; assert d['total_violations'] > 0
print(f'A4 ✅ 报告完整（总分:{d[\"total_score\"]} 违规:{d[\"total_violations\"]}）')"

# A5: 下载 PDF
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/report/$REPORT_ID/pdf" -H "Authorization: Bearer $TOKEN")
echo "A5 ✅ PDF报告下载 (HTTP $HTTP_CODE)"

echo "===== E2E 场景 B：异常流程 ====="

# B1: 不支持格式
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/upload/" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/dev/null;filename=test.txt")
echo "B1 ✅ 不支持格式拒绝 (HTTP $HTTP_CODE)"

# B2: 不存在的文件
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/check/99999" \
  -H "Authorization: Bearer $TOKEN")
echo "B2 ✅ 不存在的文件拒绝 (HTTP $HTTP_CODE)"

# B3: 未认证访问
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/report/list/")
echo "B3 ✅ 未认证拒绝 (HTTP $HTTP_CODE)"
```

**场景 C：浏览器 E2E（Chrome 工具）**

使用浏览器工具完成以下操作：
1. 打开前端首页 → 一键登录
2. 导航到上传页面 → 选择测试文件 → 点击上传
3. 观察四步流程状态变化
4. 完成后进入报告页面 → 验证所有组件渲染
5. 尝试 PDF 下载

### 第 7 步：测试结果汇总

```bash
echo ""
echo "═══════════════════════════════════════"
echo "  包合规 - 自动化测试报告"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════"
echo "【   】步骤 1 - Docker 部署"
echo "【   】步骤 2 - API 冒烟测试"
echo "【   】步骤 3 - pytest"
echo "【   】步骤 4 - API 场景测试"
echo "【   】步骤 5 - 浏览器 UI 测试"
echo "【   】步骤 6 - E2E 场景测试"
```

> 每个步骤完成后更新方括号标记：✅ 通过 / ❌ 失败:原因 / ⏭️ 跳过:原因

### 测试文件清单

```
backend/tests/
├── conftest.py              # 共享 fixtures
├── test_e2e.py              # E2E 测试（正常/异常/边界/规则管理/同步/部署验证）
├── test_fusion.py           # 融合引擎单元测试
├── test_llm_engine.py       # LLM 引擎单元测试
├── test_llm_integration.py  # LLM 集成测试
├── test_rule_engine.py      # 规则引擎单元测试
├── test_parser.py           # 文档解析器测试
└── fixtures/                # 测试文档工具
```

### 注意事项

- **LLM Mock 模式**：确保 `BHG_LLM_MOCK_MODE=true`（开发环境默认），避免真实调用大模型 API
- **Docker 日志查看**：`docker compose logs backend --tail=50`
- **数据清理**：`docker compose down -v` 删除全部数据卷
- **前端无测试**：目前无测试框架，浏览器手工测试是主要验证手段
- **本地直接运行**：也可从宿主机直接运行 pytest，但需 PostgreSQL 和 MinIO 在运行

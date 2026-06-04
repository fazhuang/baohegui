# 警示公告 & 政策法规模块 — hlgs 可复用资产分析

## 1. 警示公告模块 (Announcement)

### 数据模型 (`announcement.py`)
```python
# announcements 表 — 9 个业务字段 + 2 个元数据字段
class AnnouncementModel:
    title: str(200)          # 公告标题
    summary: str(500)        # 摘要
    content: Text            # 正文
    severity: str(20)        # info | warning | danger | critical  — 严重程度分级
    category: str(50)        # 违规处罚 | 政策通知 | 系统公告
    source: str(100)         # 通报来源机构
    case_date: str(50)       # 案例发生时间
    penalty_amount: str(50)  # 处罚/项目金额
    violation_type: str(100) # 违规类型分类
    is_pinned: bool          # 是否置顶
    is_published: bool       # 发布状态
    view_count: int          # 浏览计数
```

### API 路由设计
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/announcements` | GET | 公开列表（分页+分类过滤） |
| `/api/v1/announcements/homepage` | GET | 首页置顶公告 JSON |
| `/api/v1/announcements/homepage-html` | GET | 首页 HTMX 片段（含风格映射） |
| `/api/v1/announcements/{id}` | GET | 详情（自动增加浏览计数） |
| `/api/v1/announcements/admin/all` | GET | 管理员全部列表 |
| `/api/v1/announcements` | POST | 管理员创建 |
| `/api/v1/announcements/{id}` | PUT | 管理员更新 |
| `/api/v1/announcements/{id}` | DELETE | 管理员删除 |
| `/api/v1/announcements/sync` | POST | 触发全网通报采集合成 |

### 核心亮点
1. **severity 四级分色**：info(蓝) / warning(黄) / danger(红) / critical(红)，首页 HTMX 片段动态映射颜色
2. **自动去重同步**：从甘肃省政府采购网、信用中国等多渠道采集，标题去重后入库
3. **浏览量自动递增**：get_announcement 自动 +1
4. **预置案例数据**：`_legacy_sync_network_announcements` 含 5 条完整真实案例（提供虚假材料、串通投标、违规转包、拒签合同、违规收费）

---

## 2. 政策法规模块 (Policy)

### 数据模型 (`policy.py`)
```python
# policy_articles 表 — 14 个字段
class PolicyArticleModel:
    title: str(240)        # 标题
    slug: str(260)         # URL 友好标识（自动生成，唯一）
    summary: str(800)      # 摘要
    content: Text          # 正文
    interpretation: Text   # 政策解读
    policy_basis: Text     # 政策依据
    source: str(160)       # 来源
    source_url: str(500)   # 来源链接
    category: str(80)      # 政策解读 | 法规速递 等
    region: str(80)        # 全国 | 甘肃 等
    tags: JSON             # ["中小企业","价格评审"]
    is_pinned: bool        # 置顶
    is_published: bool     # 发布状态（草稿/已发布分离）
    view_count: int
```

### API 路由设计
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/policies` | GET | 公开列表（分类+地域+关键词搜索+分页） |
| `/api/v1/policies/admin/all` | GET | 管理员全部（含未发布草稿） |
| `/api/v1/policies/{id}` | GET | 详情（公开仅看已发布） |
| `/api/v1/policies` | POST | 管理员发布 |
| `/api/v1/policies/{id}` | PUT | 管理员更新 |
| `/api/v1/policies/{id}` | DELETE | 管理员删除 |

### 核心亮点
1. **草稿/发布分离**：`is_published=False` 的文章公开 API 返回 404，管理端可见
2. **slug 自动生成**：标题 → 拼音/lowercase → 唯一性检查 → 追加后缀
3. **全文检索**：title + summary + content + interpretation 四字段 `ilike` 或搜索
4. **公开时间记录**：首次 `is_published=True` 时自动设置 `published_at`

---

## 3. 法规库模块 (Regulation)

### 设计模式
- 法规数据存储为 JSON 文件（`data/regulations/structured.json`，`data/regulations/knowledge_base.json`）
- 无数据库模型，`regulation_service.py` 纯文件 IO + 内存缓存
- 前端有独立的搜索/筛选页面（`regulations.html`）和 HTMX partial（`regulation_cards.html`）

### API 结构
- `get_filter_options()` — 返回所有可用的法律层级/文档类型/发布机构/风险类型筛选选项
- `search_structured()` — 关键词+多维度过滤+分页，按 source document 分组返回

---

## 4. 可复用资产清单

### P0 — 直接可迁移
| 资产 | 描述 | 工作量 |
|------|------|--------|
| `AnnouncementModel` 设计 | 10 字段完整设计 + SQLAlchemy 映射 | 0.5天 |
| `PolicyArticleModel` 设计 | 15 字段完整设计 + slug 生成逻辑 | 0.5天 |
| API 路由模式 | 公开列表+管理员CRUD+草稿分离的权限模型 | 0.5天 |
| severity 四级分色系统 | info/warning/danger/critical → 前端颜色映射 | 0.2天 |

### P1 — 需要适配
| 资产 | 描述 | 工作量 |
|------|------|--------|
| 首页 HTMX 公告片段 | 需适配 React 前端 | 1天 |
| 全网通报采集合成 | 需要实现爬虫或 API 对接 | 2-3天 |
| 法规库搜索 | 需要准备法规 JSON 数据 | 2天 |

---

## 5. baohegui 集成建议

### 数据模型 (backend/app/models/)
```python
# 新增两个模型文件
backend/app/models/announcement.py  — 警示公告
backend/app/models/policy.py        — 政策法规
```

### 服务层 (backend/app/services/)
```python
backend/app/services/announcement_service.py  — 公告 CRUD
backend/app/services/policy_service.py        — 政策 CRUD
```

### API 路由 (backend/app/api/)
```python
backend/app/api/announcements.py  — 公告 API
backend/app/api/policies.py       — 政策 API
```

### 前端页面 (frontend/src/pages/)
```typescript
frontend/src/pages/Announcements.tsx     — 公告列表
frontend/src/pages/AnnouncementDetail.tsx — 公告详情
frontend/src/pages/Policies.tsx          — 政策列表
frontend/src/pages/PolicyDetail.tsx      — 政策详情
```

### 首页集成
将公告模块集成到首页 Dashboard：显示最新 3-5 条违规警示（带颜色标记）
将政策模块集成到首页：显示最新政策解读文章

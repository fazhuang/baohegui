"""案例采集到知识库同步测试。"""

from __future__ import annotations

import pytest

from app.models.complaint_case import ComplaintCase
from app.models.knowledge_graph import KGNode


@pytest.mark.asyncio
async def test_crawl_all_syncs_cases_into_kg(db_session, monkeypatch):
    from app.services import crawler_service

    async def _noop_sleep(*args, **kwargs):
        return None

    async def _fake_ccgp_list(fetcher):
        return [
            {"title": "A", "url": "https://example.com/a", "date": "2026-06-18"},
        ]

    async def _fake_ningxia_list(fetcher):
        return [
            {"title": "B", "url": "https://example.com/b", "date": "2026-06-18"},
        ]

    async def _fake_detail(url, fetcher):
        return {
            "province": "全国",
            "source_url": url,
            "title": f"case-{url.rsplit('/', 1)[-1]}",
            "project_name": "测试项目",
            "project_number": "X-2026-001",
            "complainant": "张三",
            "respondent": "某单位",
            "decision_date": "2026-06-18",
            "decision_type": "upheld",
            "complaint_types": '["品牌锁定"]',
            "legal_basis": "",
            "summary": "测试摘要",
            "raw_content": "测试全文",
            "is_analyzed": 0,
        }

    async def _fake_shaanxi():
        return 0

    async def _fake_mof_list(fetcher):
        return [
            {"title": "C", "url": "https://example.com/c"},
        ]

    monkeypatch.setattr(crawler_service.asyncio, "sleep", _noop_sleep)
    monkeypatch.setattr(crawler_service, "crawl_ccgp_list", _fake_ccgp_list)
    monkeypatch.setattr(crawler_service, "crawl_ningxia_list", _fake_ningxia_list)
    monkeypatch.setattr(crawler_service, "crawl_ccgp_detail", _fake_detail)
    monkeypatch.setattr("app.services.browser_crawler.crawl_shaanxi", _fake_shaanxi)
    monkeypatch.setattr("app.services.mof_crawler.fetch_gks_list", _fake_mof_list)

    stats = await crawler_service.crawl_all()

    assert stats["ccgp"]["saved"] == 1
    assert stats["ningxia"]["saved"] == 1
    assert stats["mof"]["saved"] == 1
    assert stats["cases_saved"] == 3
    # Phase 2: kg_synced now counts published cases only (via kg_projection);
    # newly-crawled cases are in "fetched" state, so kg_synced = 0
    assert stats["kg_synced"] == 0
    assert stats["errors"] == []

    complaint_count = db_session.query(ComplaintCase).count()
    kg_case_count = db_session.query(KGNode).filter(KGNode.node_type == "case").count()
    assert complaint_count == 3
    # Phase 2: kg_case nodes only created for published cases
    assert kg_case_count == 0

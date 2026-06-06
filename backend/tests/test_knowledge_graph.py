"""知识图谱测试"""
import pytest


class TestKnowledgeGraph:
    """知识图谱API测试"""

    def test_search_requires_auth(self, client):
        resp = client.get("/api/kg/search", params={"q": "招标"})
        assert resp.status_code in (401, 403)

    def test_search_with_auth(self, client, auth_headers):
        resp = client.get("/api/kg/search", params={"q": "招标"}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_seed_endpoint(self, client, auth_headers):
        resp = client.post("/api/kg/seed", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_regulation_lookup(self, client, auth_headers):
        resp = client.get("/api/kg/regulation/R101", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "regulations" in data

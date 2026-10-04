from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from interviewlens.api.app import app
from interviewlens.api.deps import get_session


@pytest.mark.parametrize(
    "url",
    [
        "/posts?position_category=Java",
        "/posts?skills=基础架构",
        "/posts/search?q=分布式锁&position_category=Java",
        "/posts/search?q=分布式锁&skills=基础架构",
    ],
)
def test_http_rejects_uncontrolled_facets_before_query(url):
    session = MagicMock()
    session.execute = AsyncMock()

    async def dependency():
        yield session

    app.dependency_overrides[get_session] = dependency
    try:
        assert TestClient(app).get(url).status_code == 422
        session.execute.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


def test_taxonomy_contract_has_exactly_eleven_categories():
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)

    async def dependency():
        yield session

    app.dependency_overrides[get_session] = dependency
    try:
        result = TestClient(app).get("/position-taxonomy")
        assert result.status_code == 200
        assert result.json()["categories"] == [
            "后端",
            "前端",
            "客户端",
            "算法/AI",
            "测试",
            "运维/SRE",
            "数据",
            "安全",
            "游戏",
            "嵌入式/系统",
            "其他",
        ]
    finally:
        app.dependency_overrides.clear()

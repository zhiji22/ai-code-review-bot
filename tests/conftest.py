"""
Test configuration and fixtures.

Per DESIGN.md §11: 65% unit / 25% integration / 10% E2E.
Uses pytest + httpx + respx + fakeredis.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Set test environment before importing app
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-32chars!")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "code_review_test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
os.environ.setdefault("GITHUB_APP_ID", "test-app-id")
os.environ.setdefault("GITHUB_APP_PRIVATE_KEY_PATH", "dummy")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret-min-1char")
os.environ.setdefault("GITHUB_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-client-secret")


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client for API testing with mocked DB."""
    from app.core.database import get_db
    from app.main import app

    # Override get_db to avoid real DB connections
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: _mock_db_generator(mock_db)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Clean up overrides after test
    app.dependency_overrides.clear()


async def _mock_db_generator(mock_db: AsyncMock):
    """Yield a mock DB session (matches get_db async generator signature)."""
    yield mock_db


@pytest.fixture
def sample_python_code() -> str:
    """Sample Python code with known issues for testing."""
    return '''import os
import sys  # unused

def hello(name):
    print(f"Hello, {name}")

def complex_function(a, b, c, d, e, f):
    """Too many params and too complex."""
    x = 1
    if a:
        if b:
            if c:
                if d:
                    x = 2
    return x

password = "hardcoded_secret_123"
eval("1+1")
'''


@pytest.fixture
def sample_js_code() -> str:
    """Sample JavaScript code with known issues."""
    return """const password = "hardcoded_secret";

function fetchData(url) {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", url, false); // sync
    xhr.send();
    return xhr.responseText;
}

element.innerHTML = userInput; // XSS
"""


@pytest.fixture
def webhook_payload() -> dict:
    """Sample GitHub webhook payload."""
    return {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "number": 42,
            "title": "Add new feature",
            "body": "This adds a cool feature",
            "head": {"sha": "abc123def456"},
            "base": {"sha": "main_branch_sha"},
            "user": {"login": "testuser"},
            "additions": 150,
            "deletions": 30,
            "changed_files": 5,
        },
        "repository": {
            "id": 123456,
            "full_name": "testowner/test-repo",
            "name": "test-repo",
            "owner": {"login": "testowner"},
        },
    }

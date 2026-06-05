"""
Test configuration and fixtures.

Per DESIGN.md §11: 65% unit / 25% integration / 10% E2E.
Uses pytest + httpx + respx + fakeredis.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Set test environment before importing app
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("APP_SECRET", "test-secret-key-for-testing-only-32chars!")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://review:review@localhost:5432/review_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
os.environ.setdefault("GITHUB_TOKEN", "ghp_test_token")


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client for API testing."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


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
    return '''const password = "hardcoded_secret";

function fetchData(url) {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", url, false); // sync
    xhr.send();
    return xhr.responseText;
}

element.innerHTML = userInput; // XSS
'''


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

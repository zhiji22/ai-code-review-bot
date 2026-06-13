"""Unit tests for RuleService — CRUD for custom and builtin rules."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.schemas.rules import RuleCreateSchema, RuleUpdateSchema
from app.services.rule_service import RuleService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    *,
    id: int = 1,
    rule_id: str = "SEC001",
    name: str = "SQL Injection",
    description: str | None = "Detects SQL injection",
    category: str = "security",
    severity: str = "critical",
    pattern: str | None = r"execute\(.*\+",
    message: str = "Possible SQL injection",
    suggestion: str | None = "Use parameterized queries",
    languages: list[str] | None = None,
    enabled: bool = True,
    is_builtin: bool = False,
    repository_id: int | None = None,
) -> MagicMock:
    """Build a mock Rule-like object with attribute access."""
    rule = MagicMock()
    rule.id = id
    rule.rule_id = rule_id
    rule.name = name
    rule.description = description
    rule.category = category
    rule.severity = severity
    rule.pattern = pattern
    rule.message = message
    rule.suggestion = suggestion
    rule.languages = languages or ["python"]
    rule.enabled = enabled
    rule.is_builtin = is_builtin
    rule.repository_id = repository_id
    rule.created_at = datetime(2025, 1, 1, tzinfo=UTC)
    rule.updated_at = datetime(2025, 1, 1, tzinfo=UTC)
    return rule


def _make_create_schema(**overrides: object) -> RuleCreateSchema:
    """Build a valid RuleCreateSchema with sensible defaults."""
    defaults: dict = {
        "rule_id": "CUS001",
        "name": "Custom Rule",
        "category": "security",
        "severity": "warning",
        "pattern": r"eval\(",
        "message": "Avoid eval()",
    }
    defaults.update(overrides)
    return RuleCreateSchema(**defaults)


# ---------------------------------------------------------------------------
# Tests — create
# ---------------------------------------------------------------------------


class TestRuleServiceCreate:
    """Tests for RuleService.create."""

    @pytest.mark.asyncio
    async def test_create_rule(self) -> None:
        """Creates a rule with correct fields and is_builtin=False."""
        session = AsyncMock()
        # session.add is synchronous in SQLAlchemy, use MagicMock to capture
        add_mock = MagicMock()
        session.add = add_mock
        session.commit.return_value = None
        session.refresh.return_value = None
        service = RuleService(session)

        data = _make_create_schema(
            description="Test description",
            suggestion="Use ast.literal_eval",
            languages=["python", "javascript"],
            repository_id=42,
        )

        await service.create(data)

        add_mock.assert_called_once()
        created = add_mock.call_args[0][0]

        assert created.rule_id == "CUS001"
        assert created.name == "Custom Rule"
        assert created.description == "Test description"
        assert created.category == "security"
        assert created.severity == "warning"
        assert created.pattern == r"eval\("
        assert created.message == "Avoid eval()"
        assert created.suggestion == "Use ast.literal_eval"
        assert created.languages == ["python", "javascript"]
        assert created.is_builtin is False
        assert created.repository_id == 42

        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(created)

    @pytest.mark.asyncio
    async def test_create_rule_with_defaults(self) -> None:
        """Uses defaults: languages=['python'], enabled=True when not specified."""
        session = AsyncMock()
        add_mock = MagicMock()
        session.add = add_mock
        session.commit.return_value = None
        session.refresh.return_value = None
        service = RuleService(session)

        data = _make_create_schema()
        assert data.languages is not None  # schema default is ["python"]

        await service.create(data)

        add_mock.assert_called_once()
        created = add_mock.call_args[0][0]
        # Default languages from schema
        assert created.languages == ["python"]
        # enabled defaults to True when None
        assert created.enabled is True
        # is_builtin always False for user-created rules
        assert created.is_builtin is False


# ---------------------------------------------------------------------------
# Tests — read (get_by_id, get_by_rule_id, list_rules, list_for_repository)
# ---------------------------------------------------------------------------


class TestRuleServiceRead:
    """Tests for RuleService read operations."""

    @pytest.mark.asyncio
    async def test_get_by_id_found(self) -> None:
        """Returns the rule when found by primary key."""
        session = AsyncMock()
        service = RuleService(session)

        mock_rule = _make_rule(id=5, rule_id="SEC001")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_rule
        session.execute.return_value = mock_result

        result = await service.get_by_id(5)

        assert result is not None
        assert result.id == 5
        assert result.rule_id == "SEC001"
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self) -> None:
        """Returns None when no rule with given id exists."""
        session = AsyncMock()
        service = RuleService(session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await service.get_by_id(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_rule_id_found(self) -> None:
        """Returns rule when found by string rule_id."""
        session = AsyncMock()
        service = RuleService(session)

        mock_rule = _make_rule(id=3, rule_id="SEC005")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_rule
        session.execute.return_value = mock_result

        result = await service.get_by_rule_id("SEC005")

        assert result is not None
        assert result.rule_id == "SEC005"

    @pytest.mark.asyncio
    async def test_list_rules_no_filters(self) -> None:
        """Returns all rules with total count when no filters applied."""
        session = AsyncMock()
        service = RuleService(session)

        rules = [_make_rule(id=i, rule_id=f"R{i:03d}") for i in range(1, 4)]

        # First call: scalar for total count
        # Second call: execute for the paginated result
        session.scalar.return_value = 3

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = rules
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result_rules, total = await service.list_rules()

        assert total == 3
        assert len(result_rules) == 3
        session.scalar.assert_awaited_once()
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_rules_with_repository_filter(self) -> None:
        """Includes both repo-specific and global (NULL repo) rules."""
        session = AsyncMock()
        service = RuleService(session)

        repo_rules = [
            _make_rule(id=1, rule_id="R001", repository_id=10),
            _make_rule(id=2, rule_id="R002", repository_id=None),
        ]

        session.scalar.return_value = 2
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = repo_rules
        session.execute.return_value = mock_result

        result_rules, total = await service.list_rules(repository_id=10)

        assert total == 2
        assert len(result_rules) == 2
        # Verify the query was built (repo_id=10 OR repo_id IS NULL)
        session.scalar.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_rules_with_category_filter(self) -> None:
        """Filters rules by category."""
        session = AsyncMock()
        service = RuleService(session)

        sec_rules = [
            _make_rule(id=1, rule_id="S01", category="security"),
            _make_rule(id=2, rule_id="S02", category="security"),
        ]

        session.scalar.return_value = 2
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sec_rules
        session.execute.return_value = mock_result

        result_rules, total = await service.list_rules(category="security")

        assert total == 2
        assert all(r.category == "security" for r in result_rules)

    @pytest.mark.asyncio
    async def test_list_rules_with_severity_filter(self) -> None:
        """Filters rules by severity."""
        session = AsyncMock()
        service = RuleService(session)

        critical_rules = [_make_rule(id=1, severity="critical")]

        session.scalar.return_value = 1
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = critical_rules
        session.execute.return_value = mock_result

        result_rules, total = await service.list_rules(severity="critical")

        assert total == 1
        assert result_rules[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_list_rules_with_enabled_filter(self) -> None:
        """Filters rules by enabled status."""
        session = AsyncMock()
        service = RuleService(session)

        disabled_rules = [_make_rule(id=1, enabled=False)]

        session.scalar.return_value = 1
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = disabled_rules
        session.execute.return_value = mock_result

        result_rules, total = await service.list_rules(enabled=False)

        assert total == 1
        assert result_rules[0].enabled is False

    @pytest.mark.asyncio
    async def test_list_rules_pagination(self) -> None:
        """Respects offset and limit for pagination."""
        session = AsyncMock()
        service = RuleService(session)

        page2_rules = [_make_rule(id=i) for i in range(11, 21)]

        session.scalar.return_value = 30
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = page2_rules
        session.execute.return_value = mock_result

        result_rules, total = await service.list_rules(offset=10, limit=10)

        assert total == 30
        assert len(result_rules) == 10

        # Verify offset/limit were applied to the statement
        execute_call = session.execute.call_args
        stmt = execute_call.args[0]
        # Verify the statement has LIMIT and OFFSET clauses
        compiled_str = str(stmt)
        assert "LIMIT" in compiled_str
        assert "OFFSET" in compiled_str

    @pytest.mark.asyncio
    async def test_list_for_repository_enabled_only(self) -> None:
        """Default enabled_only=True returns only enabled builtin + repo rules."""
        session = AsyncMock()
        service = RuleService(session)

        rules = [
            _make_rule(id=1, rule_id="B001", enabled=True, is_builtin=True, repository_id=None),
            _make_rule(id=2, rule_id="C001", enabled=True, is_builtin=False, repository_id=10),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rules
        session.execute.return_value = mock_result

        result = await service.list_for_repository(10)

        assert len(result) == 2
        assert all(r.enabled for r in result)

    @pytest.mark.asyncio
    async def test_list_for_repository_all(self) -> None:
        """enabled_only=False returns all rules including disabled ones."""
        session = AsyncMock()
        service = RuleService(session)

        rules = [
            _make_rule(id=1, rule_id="B001", enabled=True, repository_id=None),
            _make_rule(id=2, rule_id="C001", enabled=False, repository_id=10),
            _make_rule(id=3, rule_id="C002", enabled=True, repository_id=10),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rules
        session.execute.return_value = mock_result

        result = await service.list_for_repository(10, enabled_only=False)

        assert len(result) == 3
        # Includes the disabled rule
        assert any(not r.enabled for r in result)


# ---------------------------------------------------------------------------
# Tests — update / toggle
# ---------------------------------------------------------------------------


class TestRuleServiceUpdate:
    """Tests for RuleService update and toggle operations."""

    @pytest.mark.asyncio
    async def test_update_rule(self) -> None:
        """Updates specified fields and returns refreshed rule."""
        session = AsyncMock()
        service = RuleService(session)

        updated_rule = _make_rule(id=5, name="Updated Name", severity="info")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = updated_rule
        session.execute.return_value = mock_result
        session.commit.return_value = None

        data = RuleUpdateSchema(name="Updated Name", severity="info")

        result = await service.update(5, data)

        assert result is not None
        assert result.name == "Updated Name"
        assert result.severity == "info"
        # execute called twice: once for update stmt, once for get_by_id
        assert session.execute.await_count == 2
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_rule_no_changes(self) -> None:
        """Returns existing rule when no values are set in update schema."""
        session = AsyncMock()
        service = RuleService(session)

        existing_rule = _make_rule(id=5, name="Original")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_rule
        session.execute.return_value = mock_result

        data = RuleUpdateSchema()  # All fields default to None (exclude_unset=True -> empty dict)

        result = await service.update(5, data)

        assert result is not None
        assert result.name == "Original"
        # Only one execute call: get_by_id, no update stmt
        assert session.execute.await_count == 1
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_toggle_rule(self) -> None:
        """Enables or disables a rule and returns the updated rule."""
        session = AsyncMock()
        service = RuleService(session)

        toggled_rule = _make_rule(id=7, enabled=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = toggled_rule
        session.execute.return_value = mock_result
        session.commit.return_value = None

        result = await service.toggle(7, enabled=False)

        assert result is not None
        assert result.enabled is False
        # execute called twice: update stmt + get_by_id
        assert session.execute.await_count == 2
        session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests — delete
# ---------------------------------------------------------------------------


class TestRuleServiceDelete:
    """Tests for RuleService.delete."""

    @pytest.mark.asyncio
    async def test_delete_custom_rule(self) -> None:
        """Deletes a custom (non-builtin) rule and returns True."""
        session = AsyncMock()
        service = RuleService(session)

        custom_rule = _make_rule(id=10, is_builtin=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = custom_rule
        session.execute.return_value = mock_result
        session.commit.return_value = None

        result = await service.delete(10)

        assert result is True
        # execute called twice: get_by_id + delete stmt
        assert session.execute.await_count == 2
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_builtin_rule(self) -> None:
        """Cannot delete builtin rules — returns False."""
        session = AsyncMock()
        service = RuleService(session)

        builtin_rule = _make_rule(id=20, is_builtin=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = builtin_rule
        session.execute.return_value = mock_result

        result = await service.delete(20)

        assert result is False
        # Only get_by_id was called, no delete stmt
        session.execute.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_rule(self) -> None:
        """Returns False when rule does not exist."""
        session = AsyncMock()
        service = RuleService(session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await service.delete(999)

        assert result is False
        session.execute.assert_awaited_once()
        session.commit.assert_not_awaited()

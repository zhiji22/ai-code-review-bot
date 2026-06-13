"""Rule Engine - pattern-based code issue detection.

Categories: security, performance, style, best_practices.
Each rule has an ID, severity, pattern (regex or AST), message, and suggestion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class RuleCategory(StrEnum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    STYLE = "style"
    BEST_PRACTICES = "best_practices"


class RuleSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Rule:
    """A single code review rule."""

    rule_id: str  # e.g., SEC001
    name: str
    category: RuleCategory
    severity: RuleSeverity
    pattern: str  # regex pattern
    message: str
    suggestion: str
    languages: list[str] = field(default_factory=list)
    enabled: bool = True

    def matches(self, code: str, language: str) -> list[re.Match[str]]:
        """Check if this rule's pattern matches in the code."""
        if not self.enabled:
            return []
        if self.languages and language not in self.languages and "all" not in self.languages:
            return []
        try:
            return list(re.finditer(self.pattern, code, re.MULTILINE | re.IGNORECASE))
        except re.error as e:
            logger.warning("rule_regex_error", rule_id=self.rule_id, error=str(e))  # type: ignore[call-arg]
            return []


@dataclass
class RuleViolation:
    """A single rule violation found in code."""

    rule_id: str
    category: str
    severity: str
    message: str
    line_number: int = 1
    line_end: int | None = None
    suggestion: str = ""
    matched_text: str = ""
    confidence: float = 1.0


# --- Built-in Rules ---

BUILTIN_RULES: list[Rule] = [
    # Security Rules (SEC001-SEC010)
    Rule(
        rule_id="SEC001",
        name="SQL Injection",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.CRITICAL,
        pattern=(
            r'(?:execute|cursor\.execute)\s*\(\s*["\']'
            r"(?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\s+.*?"
            r'(?:\+|\%|\bf\b|\.format|f["\'])'
        ),
        message="Potential SQL injection: dynamic query with string concatenation",
        suggestion='Use parameterized queries: cursor.execute("SELECT ... WHERE id = %s", (val,))',
        languages=["python"],
    ),
    Rule(
        rule_id="SEC002",
        name="Hardcoded Secret",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.CRITICAL,
        pattern=(
            r"(?i)(?:password|secret|api[_-]?key|token|private[_-]?key)\s*[=:]\s*"
            r'["\'][^"\']{8,}["\']'
        ),
        message="Hardcoded secret/token detected",
        suggestion="Use environment variables or a secrets manager (e.g., Vault, AWS Secrets Manager)",
        languages=["all"],
    ),
    Rule(
        rule_id="SEC003",
        name="Unsafe Deserialization",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.CRITICAL,
        pattern=r"(?:pickle\.loads|yaml\.load|eval|exec)\s*\(",
        message="Unsafe deserialization or code execution",
        suggestion="Use json.loads() or yaml.safe_load(); avoid eval()/exec()",
        languages=["python"],
    ),
    Rule(
        rule_id="SEC004",
        name="XSS via innerHTML",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.CRITICAL,
        pattern=r"\.innerHTML\s*=\s*[^;]+",
        message="Potential XSS: setting innerHTML with untrusted content",
        suggestion="Use textContent or sanitize HTML with DOMPurify before setting innerHTML",
        languages=["javascript", "typescript"],
    ),
    Rule(
        rule_id="SEC005",
        name="Disabled HTTPS Verification",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.CRITICAL,
        pattern=r"verify\s*=\s*False",
        message="SSL/TLS verification disabled",
        suggestion="Never disable certificate verification in production code",
        languages=["python"],
    ),
    Rule(
        rule_id="SEC006",
        name="Command Injection",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.CRITICAL,
        pattern=r'(?:os\.system|subprocess\.call|subprocess\.Popen)\s*\(\s*["\'].*?\+',
        message="Potential command injection: shell command with concatenation",
        suggestion="Use subprocess with list arguments: subprocess.run(['cmd', arg], shell=False)",
        languages=["python"],
    ),
    Rule(
        rule_id="SEC007",
        name="Weak Hashing",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.WARNING,
        pattern=r"hashlib\.(?:md5|sha1)\s*\(",
        message="Weak hash algorithm (MD5/SHA1) is insecure for cryptographic purposes",
        suggestion="Use hashlib.sha256 or hashlib.sha512 for security-sensitive hashing",
        languages=["python"],
    ),
    Rule(
        rule_id="SEC008",
        name="Debug Mode in Production",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.WARNING,
        pattern=r"(?:DEBUG\s*=\s*True|app\.run\s*\(\s*debug\s*=\s*True)",
        message="Debug mode enabled - exposes sensitive info in production",
        suggestion="Set DEBUG=False in production; use environment variables",
        languages=["python"],
    ),
    Rule(
        rule_id="SEC009",
        name="Insecure Random",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.WARNING,
        pattern=r"random\.random\s*\(\s*\)",
        message="Insecure random number generator for security context",
        suggestion="Use secrets module for tokens, passwords, and security-sensitive randomness",
        languages=["python"],
    ),
    Rule(
        rule_id="SEC010",
        name="Broad Exception Handler",
        category=RuleCategory.SECURITY,
        severity=RuleSeverity.WARNING,
        pattern=r"except\s*(?:Exception|BaseException)?\s*:\s*pass",
        message="Silent exception swallowing (bare except + pass)",
        suggestion="Log the exception and handle specifically: except SpecificError as e: logger.error(...)",
        languages=["python"],
    ),
    # Performance Rules (PERF001-PERF005)
    Rule(
        rule_id="PERF001",
        name="N+1 Query Pattern",
        category=RuleCategory.PERFORMANCE,
        severity=RuleSeverity.WARNING,
        pattern=r"(?:for\s+\w+\s+in\s+\w+\.objects|for\s+\w+\s+in\s+\w+\.all\(\)|for\s+\w+\s+in\s+\w+\.filter\()",
        message="Potential N+1 query: database access inside a loop",
        suggestion="Use select_related/prefetch_related or batch fetch before the loop",
        languages=["python"],
    ),
    Rule(
        rule_id="PERF002",
        name="List Append in Loop",
        category=RuleCategory.PERFORMANCE,
        severity=RuleSeverity.INFO,
        pattern=r"for\s+\w+\s+in\s+\w+:\s*\n\s*\w+\.append\(",
        message="Building list in a loop with append - consider list comprehension",
        suggestion="Use list comprehension: [transform(x) for x in items]",
        languages=["python"],
    ),
    Rule(
        rule_id="PERF003",
        name="Unnecessary Re-compile",
        category=RuleCategory.PERFORMANCE,
        severity=RuleSeverity.INFO,
        pattern=r're\.(?:match|search|findall|sub)\s*\(\s*["\']',
        message="Regex pattern compiled inline on every call",
        suggestion="Pre-compile: pattern = re.compile(r'...') and reuse",
        languages=["python"],
    ),
    Rule(
        rule_id="PERF004",
        name="Global Mutable State",
        category=RuleCategory.PERFORMANCE,
        severity=RuleSeverity.WARNING,
        pattern=r"^(?:\s*_?\w+\s*:\s*(?:list|dict|set)\s*=\s*(?:\[\]|\{\}|\{\}|\(\)))",
        message="Module-level mutable default (potential shared state issue)",
        suggestion="Initialize inside function or use None as default and create inside",
        languages=["python"],
    ),
    Rule(
        rule_id="PERF005",
        name="Synchronous IO in Async",
        category=RuleCategory.PERFORMANCE,
        severity=RuleSeverity.WARNING,
        pattern=r"async\s+def\s+\w+.*:\s*\n(?:.*\n)*?.*(?:requests\.|urllib\.|open\()",
        message="Blocking I/O inside async function",
        suggestion="Use aiohttp/httpx for HTTP, aiofiles for file I/O in async contexts",
        languages=["python"],
    ),
    # Style Rules (STYLE001-STYLE004)
    Rule(
        rule_id="STYLE001",
        name="Long Line",
        category=RuleCategory.STYLE,
        severity=RuleSeverity.INFO,
        pattern=r"^.{121,}$",
        message="Line exceeds 120 characters",
        suggestion="Break long lines for readability",
        languages=["all"],
    ),
    Rule(
        rule_id="STYLE002",
        name="TODO/FIXME Comment",
        category=RuleCategory.STYLE,
        severity=RuleSeverity.INFO,
        pattern=r"(?:TODO|FIXME|HACK|XXX)\b",
        message="Unresolved TODO/FIXME comment",
        suggestion="Create a ticket or resolve before merging",
        languages=["all"],
    ),
    Rule(
        rule_id="STYLE003",
        name="Print Statement",
        category=RuleCategory.STYLE,
        severity=RuleSeverity.INFO,
        pattern=r"^\s*print\s*\(",
        message="Print statement found (should use logging in production)",
        suggestion="Replace print() with logger.info/debug/warning",
        languages=["python"],
    ),
    Rule(
        rule_id="STYLE004",
        name="Magic Number",
        category=RuleCategory.STYLE,
        severity=RuleSeverity.INFO,
        pattern=r"(?:==|!=|<=|>=|<|>)\s*(\d{3,})",
        message="Magic number in comparison - extract to named constant",
        suggestion="Define: MAX_RETRIES = 500; if count > MAX_RETRIES: ...",
        languages=["all"],
    ),
    # Best Practices (BP001-BP004)
    Rule(
        rule_id="BP001",
        name="Missing Type Hints",
        category=RuleCategory.BEST_PRACTICES,
        severity=RuleSeverity.INFO,
        pattern=r"def\s+\w+\s*\([^)]*\)\s*:",
        message="Function lacks type annotations",
        suggestion="Add type hints: def func(x: int) -> str:",
        languages=["python"],
    ),
    Rule(
        rule_id="BP002",
        name="Mutable Default Argument",
        category=RuleCategory.BEST_PRACTICES,
        severity=RuleSeverity.WARNING,
        pattern=r"def\s+\w+\([^)]*=\s*(?:\[\]|\{\})",
        message="Mutable default argument (list/dict) - shared across calls",
        suggestion="Use None as default: def func(x=None): x = x or []",
        languages=["python"],
    ),
    Rule(
        rule_id="BP003",
        name="String Formatting",
        category=RuleCategory.BEST_PRACTICES,
        severity=RuleSeverity.INFO,
        pattern=r"\.format\s*\(",
        message="Using .format() instead of f-string",
        suggestion='Use f-string: f"Hello {name}" for better readability',
        languages=["python"],
    ),
    Rule(
        rule_id="BP004",
        name="Assert in Production",
        category=RuleCategory.BEST_PRACTICES,
        severity=RuleSeverity.WARNING,
        pattern=r"^\s*assert\s+",
        message="Assert statement removed when running with -O flag",
        suggestion="Use if not condition: raise ValueError(...) for runtime checks",
        languages=["python"],
    ),
]


class RuleEngine:
    """Executes rule checks against source code."""

    def __init__(self, custom_rules: list[Rule] | None = None) -> None:
        self.rules: list[Rule] = list(BUILTIN_RULES)
        if custom_rules:
            self.rules.extend(custom_rules)

    def check(
        self,
        code: str,
        language: str,
        rules: list[Rule] | None = None,
        file_path: str = "",
    ) -> list[RuleViolation]:
        """Run all enabled rules against the code.

        Args:
            code: Source code text
            language: Programming language
            rules: Override rules (default: use self.rules)
            file_path: Optional file path for context

        Returns:
            List of violations found
        """
        violations: list[RuleViolation] = []
        active_rules = rules if rules is not None else self.rules

        for rule in active_rules:
            if not rule.enabled:
                continue
            if rule.languages and language not in rule.languages and "all" not in rule.languages:
                continue

            matches = rule.matches(code, language)
            for match in matches:
                # Calculate line number from match position
                line_num = code[: match.start()].count("\n") + 1
                match_end_line = code[: match.end()].count("\n") + 1

                # Context-aware message
                matched_text = match.group(0)[:100]  # truncate
                violation = RuleViolation(
                    rule_id=rule.rule_id,
                    category=rule.category.value,
                    severity=rule.severity.value,
                    message=rule.message,
                    line_number=line_num,
                    line_end=match_end_line if match_end_line > line_num else None,
                    suggestion=rule.suggestion,
                    matched_text=matched_text,
                    confidence=1.0,
                )
                violations.append(violation)

        return violations

    def get_rules_by_category(self, category: RuleCategory) -> list[Rule]:
        """Filter rules by category."""
        return [r for r in self.rules if r.category == category and r.enabled]

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a rule by ID."""
        for r in self.rules:
            if r.rule_id == rule_id:
                r.enabled = True
                return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a rule by ID."""
        for r in self.rules:
            if r.rule_id == rule_id:
                r.enabled = False
                return True
        return False

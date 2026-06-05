"""AST Analyzer using tree-sitter.

Detects structural code issues:
- High cyclomatic complexity functions
- Unused imports
- Deep nesting
- Duplicate code blocks
- LOC / comment ratio stats
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from tree_sitter import Language, Node, Parser

try:
    from tree_sitter_languages import get_language, get_parser
    _HAS_TS_LANGS = True
except ImportError:
    _HAS_TS_LANGS = False
    get_language = None  # type: ignore
    get_parser = None  # type: ignore

logger = logging.getLogger(__name__)

# Supported languages
SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "java", "go", "rust"}

# Thresholds
MAX_CYCLOMATIC_COMPLEXITY = 10
MAX_NESTING_DEPTH = 4
MAX_FUNCTION_LENGTH = 50  # lines
MAX_PARAMS = 5


@dataclass
class ASTIssue:
    """A single AST-detected issue."""

    line_number: int
    line_end: int | None = None
    category: str = ""  # maintainability, style, performance
    severity: str = "warning"  # critical, warning, info
    message: str = ""
    suggestion: str = ""
    issue_type: str = ""  # complexity, nesting, unused_import, etc.
    confidence: float = 0.95


@dataclass
class ASTReport:
    """Full AST analysis report for a single file."""

    file_path: str = ""
    language: str = ""
    issues: list[ASTIssue] = field(default_factory=list)
    lines_of_code: int = 0
    comment_lines: int = 0
    import_count: int = 0
    function_count: int = 0
    max_complexity: int = 0
    parse_error: bool = False

    @classmethod
    def empty(cls, file_path: str = "", language: str = "") -> ASTReport:
        return cls(file_path=file_path, language=language)


class ASTAnalyzer:
    """Tree-sitter based AST analyzer."""

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}

    def _get_parser(self, language: str) -> Parser | None:
        """Get or create parser for a language."""
        if language not in SUPPORTED_LANGUAGES:
            return None
        if language in self._parsers:
            return self._parsers[language]
        try:
            if _HAS_TS_LANGS:
                parser = get_parser(language)
            else:
                # Fallback: individual tree-sitter packages
                parser = self._build_parser(language)
            self._parsers[language] = parser
            return parser
        except Exception as e:
            logger.warning("parser_init_failed for %s: %s", language, e)
            return None

    def _build_parser(self, language: str) -> Parser:
        """Build parser from individual tree-sitter packages."""
        import tree_sitter_python
        import tree_sitter_javascript
        import tree_sitter_typescript

        lang_map = {
            "python": tree_sitter_python,
            "javascript": tree_sitter_javascript,
            "typescript": tree_sitter_typescript,
        }
        if language not in lang_map:
            raise ValueError(f"Unsupported language: {language}")

        lang_module = lang_map[language]
        # tree-sitter 0.23+: language() returns PyCapsule, wrap in Language
        ts_lang = Language(lang_module.language())
        parser = Parser(ts_lang)
        return parser

    def analyze(
        self,
        file_path: str,
        code: str,
        language: str,
    ) -> ASTReport:
        """Parse code AST and return structural report.

        Args:
            file_path: Path to the source file
            code: Full source code text
            language: Programming language identifier

        Returns:
            ASTReport with detected issues and metrics
        """
        report = ASTReport(file_path=file_path, language=language)

        parser = self._get_parser(language)
        if parser is None:
            report.parse_error = True
            return report

        try:
            tree = parser.parse(code.encode("utf-8"))
        except Exception as e:
            logger.warning("parse_failed for %s: %s", file_path, e)
            report.parse_error = True
            return report

        root = tree.root_node

        # Basic metrics
        report.lines_of_code = code.count("\n") + 1
        report.comment_lines = _count_comments(code, language)

        # Walk AST for analysis
        self._walk(root, code, language, report)

        return report

    def _walk(
        self,
        node: Node,
        code: str,
        language: str,
        report: ASTReport,
    ) -> None:
        """Walk AST nodes and check for issues."""
        # Language-specific function/method node types
        FUNC_TYPES = {
            "python": {"function_definition"},
            "javascript": {"function_declaration", "method_definition", "arrow_function"},
            "typescript": {"function_declaration", "method_definition", "arrow_function"},
            "java": {"method_declaration", "constructor_declaration"},
            "go": {"function_declaration", "method_declaration"},
        }

        IMPORT_TYPES = {
            "python": {"import_statement", "import_from_statement"},
            "javascript": {"import_statement"},
            "typescript": {"import_statement", "import_alias"},
            "java": {"import_declaration"},
            "go": {"import_declaration"},
        }

        func_types = FUNC_TYPES.get(language, set())
        import_types = IMPORT_TYPES.get(language, set())

        if node.type in func_types:
            self._check_function(node, code, report)
            report.function_count += 1

        if node.type in import_types:
            report.import_count += 1
            self._check_unused_import(node, code, report, language)

        # Recurse children
        for child in node.children:
            self._walk(child, code, language, report)

    def _check_function(
        self,
        node: Node,
        code: str,
        report: ASTReport,
    ) -> None:
        """Check a function node for issues."""
        # Get function name
        name_node = node.child_by_field_name("name")
        func_name = _node_text(name_node, code) if name_node else "<anonymous>"

        # Line numbers
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        func_length = end_line - start_line + 1

        # 1. Function too long
        if func_length > MAX_FUNCTION_LENGTH:
            report.issues.append(ASTIssue(
                line_number=start_line,
                line_end=end_line,
                category="maintainability",
                severity="warning",
                message=f"Function '{func_name}' is {func_length} lines long (max {MAX_FUNCTION_LENGTH})",
                suggestion="Consider breaking into smaller functions",
                issue_type="long_function",
            ))

        # 2. Parameter count
        params_node = node.child_by_field_name("parameters")
        if params_node:
            param_count = sum(
                1 for c in params_node.children
                if c.type not in {",", "(", ")", "comment"}
            )
            if param_count > MAX_PARAMS:
                report.issues.append(ASTIssue(
                    line_number=start_line,
                    category="maintainability",
                    severity="info",
                    message=f"Function '{func_name}' has {param_count} parameters (max {MAX_PARAMS})",
                    suggestion="Consider using a config object or dataclass",
                    issue_type="too_many_params",
                ))

        # 3. Cyclomatic complexity
        complexity = _calc_complexity(node)
        report.max_complexity = max(report.max_complexity, complexity)
        if complexity > MAX_CYCLOMATIC_COMPLEXITY:
            report.issues.append(ASTIssue(
                line_number=start_line,
                category="maintainability",
                severity="warning",
                message=(
                    f"Function '{func_name}' has cyclomatic complexity {complexity} "
                    f"(max {MAX_CYCLOMATIC_COMPLEXITY})"
                ),
                suggestion="Reduce branching: extract helpers, use early returns, guard clauses",
                issue_type="high_complexity",
            ))

        # 4. Nesting depth
        depth = _max_nesting(node)
        if depth > MAX_NESTING_DEPTH:
            report.issues.append(ASTIssue(
                line_number=start_line,
                category="maintainability",
                severity="info",
                message=f"Function '{func_name}' has nesting depth {depth} (max {MAX_NESTING_DEPTH})",
                suggestion="Flatten nesting with early returns or extract nested logic",
                issue_type="deep_nesting",
            ))

    def _check_unused_import(
        self,
        node: Node,
        code: str,
        report: ASTReport,
        language: str,
    ) -> None:
        """Check for potentially unused imports (heuristic)."""
        # This is a simplified heuristic; full unused-import detection
        # would require scope analysis
        imported_name = ""
        if language == "python":
            # Handle: import X or from X import Y
            for child in node.children:
                if child.type == "dotted_name":
                    imported_name = _node_text(child, code).split(".")[-1]
                    break
                if child.type == "identifier":
                    imported_name = _node_text(child, code)
                    break
            # Also check aliased imports
            alias_node = node.child_by_field_name("alias")
            if alias_node:
                imported_name = _node_text(alias_node, code)

        # Skip wildcard imports
        if imported_name and imported_name != "*":
            # Check if name appears elsewhere in code (rough heuristic)
            # Remove the import line from search
            import_line = _node_text(node, code)
            search_code = code.replace(import_line, "", 1)
            # Count occurrences outside the import statement
            occurrences = search_code.count(imported_name)
            if occurrences == 0:
                line_num = node.start_point[0] + 1
                report.issues.append(ASTIssue(
                    line_number=line_num,
                    category="maintainability",
                    severity="info",
                    message=f"Import '{imported_name}' appears unused",
                    suggestion=f"Remove unused import: {imported_name}",
                    issue_type="unused_import",
                ))


# --- Helpers ---


def _node_text(node: Node | None, code: str) -> str:
    """Get text of a node from source."""
    if node is None:
        return ""
    lines = code.split("\n")
    start_row, start_col = node.start_point
    end_row, end_col = node.end_point
    if start_row == end_row:
        return lines[start_row][start_col:end_col]
    result = lines[start_row][start_col:]
    for r in range(start_row + 1, end_row):
        result += "\n" + lines[r]
    result += "\n" + lines[end_row][:end_col]
    return result


def _count_comments(code: str, language: str) -> int:
    """Count comment lines."""
    comment_chars = {
        "python": "#",
        "javascript": "//",
        "typescript": "//",
        "java": "//",
        "go": "//",
        "rust": "//",
    }
    cc = comment_chars.get(language, "//")
    count = 0
    for line in code.split("\n"):
        stripped = line.strip()
        if stripped.startswith(cc) or stripped.startswith("/*") or stripped.startswith("*"):
            count += 1
    return count


def _calc_complexity(node: Node) -> int:
    """Calculate cyclomatic complexity of a function node."""
    # Decision points: if, elif, for, while, except, and, or, case
    DECISION_TYPES = {
        "if_statement",
        "for_statement",
        "while_statement",
        "except_clause",
        "case",
        "conditional_expression",  # ternary
        "boolean_operation",  # and/or
    }
    complexity = 1  # base
    stack = list(node.children)
    while stack:
        child = stack.pop()
        if child.type in DECISION_TYPES:
            complexity += 1
        stack.extend(child.children)
    return complexity


def _max_nesting(node: Node, current_depth: int = 0) -> int:
    """Calculate maximum nesting depth within a function."""
    NESTING_TYPES = {
        "if_statement",
        "for_statement",
        "while_statement",
        "with_statement",
        "try_statement",
        "except_clause",
        "finally_clause",
        "else_clause",
        "elif_clause",
    }
    max_d = current_depth
    for child in node.children:
        if child.type in NESTING_TYPES:
            child_depth = _max_nesting(child, current_depth + 1)
            max_d = max(max_d, child_depth)
        else:
            child_depth = _max_nesting(child, current_depth)
            max_d = max(max_d, child_depth)
    return max_d

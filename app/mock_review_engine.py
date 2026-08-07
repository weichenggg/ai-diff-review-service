"""Deterministic mock review rules for parsed diff additions."""

import re
from dataclasses import dataclass

from app.diff_parser import AddedLine


@dataclass(frozen=True)
class Finding:
    id: str
    ruleId: str
    path: str
    line: int
    severity: str
    category: str
    title: str
    evidence: str


RuleDetails = tuple[str, str, str]

RULE_DETAILS: dict[str, RuleDetails] = {
    "MOCK-001": ("critical", "security", "eval usage"),
    "MOCK-002": ("critical", "security", "hardcoded credential"),
    "MOCK-003": ("high", "security", "SQL string concatenation"),
    "MOCK-004": ("high", "correctness", "swallowed exception"),
    "MOCK-005": ("medium", "correctness", "loose null comparison"),
    "MOCK-006": ("medium", "performance", "deep-clone via JSON"),
    "MOCK-007": ("low", "style", "console.log left in"),
    "MOCK-008": ("low", "style", "unresolved marker"),
    "MOCK-INJ": ("critical", "security", "prompt-injection content"),
}

HARDCODED_CREDENTIAL_PATTERN = re.compile(
    r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_-]{16,}['\"]",
    re.IGNORECASE,
)
SQL_STRING_CONCATENATION_PATTERN = re.compile(
    r"(?:['\"][^'\"]*\b(?:SELECT|INSERT|UPDATE|DELETE)\b[^'\"]*['\"]\s*\+"
    r"|\+\s*['\"][^'\"]*\b(?:SELECT|INSERT|UPDATE|DELETE)\b[^'\"]*['\"])",
    re.IGNORECASE,
)
EMPTY_CATCH_START_PATTERN = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{")
LOOSE_NULL_PATTERN = re.compile(r"(?:==|!=)\s*null")
PROMPT_INJECTION_PATTERN = re.compile(
    r"ignore previous instructions|disregard all prior|you are now",
    re.IGNORECASE,
)


def _make_finding(rule_id: str, path: str, added_line: AddedLine) -> Finding:
    severity, category, title = RULE_DETAILS[rule_id]
    return Finding(
        id=f"{rule_id}:{path}:{added_line.lineNumber}",
        ruleId=rule_id,
        path=path,
        line=added_line.lineNumber,
        severity=severity,
        category=category,
        title=title,
        evidence=added_line.content,
    )


def _is_empty_catch_block(added_lines: list[AddedLine], start_index: int) -> bool:
    """Determine whether a catch block made of consecutive additions is empty."""
    match = EMPTY_CATCH_START_PATTERN.search(added_lines[start_index].content)
    if match is None:
        return False

    brace_depth = 1
    block_content: list[str] = []
    expected_line_number = added_lines[start_index].lineNumber

    for added_line in added_lines[start_index:]:
        if added_line.lineNumber != expected_line_number:
            return False
        expected_line_number += 1

        content = added_line.content
        segment = content[match.end() :] if added_line is added_lines[start_index] else content
        for character in segment:
            if character == "{":
                brace_depth += 1
            elif character == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    return not "".join(block_content).strip()
            else:
                block_content.append(character)

    return False


def review_added_lines(path: str, added_lines: list[AddedLine]) -> list[Finding]:
    """Apply all mock rules to parsed additions for one file."""
    findings: list[Finding] = []

    for index, added_line in enumerate(added_lines):
        content = added_line.content
        rule_ids: list[str] = []

        if "eval(" in content:
            rule_ids.append("MOCK-001")
        if HARDCODED_CREDENTIAL_PATTERN.search(content):
            rule_ids.append("MOCK-002")
        if SQL_STRING_CONCATENATION_PATTERN.search(content):
            rule_ids.append("MOCK-003")
        if _is_empty_catch_block(added_lines, index):
            rule_ids.append("MOCK-004")
        if LOOSE_NULL_PATTERN.search(content):
            rule_ids.append("MOCK-005")
        if "JSON.parse(JSON.stringify(" in content:
            rule_ids.append("MOCK-006")
        if "console.log(" in content:
            rule_ids.append("MOCK-007")
        if "TODO" in content or "FIXME" in content:
            rule_ids.append("MOCK-008")
        if PROMPT_INJECTION_PATTERN.search(content):
            rule_ids.append("MOCK-INJ")

        findings.extend(_make_finding(rule_id, path, added_line) for rule_id in rule_ids)

    return sorted(findings, key=lambda finding: (finding.path, finding.line, finding.ruleId))

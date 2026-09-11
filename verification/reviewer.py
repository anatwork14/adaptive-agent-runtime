"""Automated code reviewer and security boundary verifier."""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ReviewResult:
    passed: bool
    comments: List[str] = field(default_factory=list)
    security_violations: List[str] = field(default_factory=list)


class CodeReviewer:
    """Automated reviewer checking security boundaries and submission criteria."""

    SECRET_PATTERNS = [
        re.compile(r"(?i)(api[_-]?key|secret|password|bearer|auth[_-]?token)\s*=\s*['\"][a-zA-Z0-9_\-\.]{12,}['\"]"),
        re.compile(r"(?i)ghp_[a-zA-Z0-9]{36}"),
        re.compile(r"(?i)sk-[a-zA-Z0-9]{32,}"),
    ]

    HIDDEN_TEST_PATTERNS = [
        re.compile(r"(?i)hidden_test"),
        re.compile(r"(?i)grading_test"),
    ]

    def review_patch(self, diff: str, summary: str = "", acceptance_criteria: Optional[List[str]] = None) -> ReviewResult:
        violations: List[str] = []
        comments: List[str] = []

        if not diff.strip() and not summary.strip():
            violations.append("Empty submission: no diff or summary provided.")

        # Check for hardcoded secrets
        for pattern in self.SECRET_PATTERNS:
            if pattern.search(diff):
                violations.append("Security violation: hardcoded credentials or API key detected in diff.")

        # Check for hidden test tampering
        for pattern in self.HIDDEN_TEST_PATTERNS:
            if pattern.search(diff):
                violations.append("Security violation: attempt to access or modify hidden/grading tests.")

        if acceptance_criteria:
            comments.append(f"Reviewed against {len(acceptance_criteria)} acceptance criteria.")

        return ReviewResult(
            passed=len(violations) == 0,
            comments=comments,
            security_violations=violations,
        )

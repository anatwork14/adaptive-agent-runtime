"""GitHub CLI integration used by ARC's closed-loop review supervisor.

ARC deliberately delegates GitHub authentication to the user's existing `gh`
installation. This module never reads or persists GitHub tokens. External PR,
check, and review state is normalized into a compact snapshot which the
application layer can project into ARC's append-only event stream.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class GitHubCliError(RuntimeError):
    """Raised when the local GitHub CLI cannot complete an integration action."""


class GitHubCheck(BaseModel):
    name: str
    status: str = "UNKNOWN"
    conclusion: str = ""
    url: str = ""

    @property
    def failed(self) -> bool:
        conclusion = self.conclusion.upper()
        return conclusion not in {"", "SUCCESS", "NEUTRAL", "SKIPPED"}

    @property
    def pending(self) -> bool:
        return self.status.upper() not in {"COMPLETED", "SUCCESS"} and not self.conclusion


class GitHubFeedback(BaseModel):
    source: str
    author: str = ""
    body: str
    url: str = ""
    path: str = ""
    line: int | None = None
    state: str = ""


class GitHubPullRequestSnapshot(BaseModel):
    number: int
    url: str
    title: str = ""
    state: str = "OPEN"
    head_ref: str = ""
    base_ref: str = ""
    review_decision: str = ""
    merge_state_status: str = ""
    checks: list[GitHubCheck] = Field(default_factory=list)
    feedback: list[GitHubFeedback] = Field(default_factory=list)
    digest: str = ""

    @property
    def failed_checks(self) -> list[GitHubCheck]:
        return [item for item in self.checks if item.failed]

    @property
    def pending_checks(self) -> list[GitHubCheck]:
        return [item for item in self.checks if item.pending]

    @property
    def healthy(self) -> bool:
        return (
            self.state.upper() == "OPEN"
            and not self.failed_checks
            and not self.pending_checks
            and self.review_decision.upper() != "CHANGES_REQUESTED"
        )

    def actionable_feedback(self) -> str:
        sections: list[str] = []
        if self.failed_checks:
            lines = ["GitHub checks currently failing:"]
            for check in self.failed_checks:
                suffix = f" ({check.url})" if check.url else ""
                lines.append(f"- {check.name}: {check.conclusion or check.status}{suffix}")
            sections.append("\n".join(lines))
        if self.review_decision.upper() == "CHANGES_REQUESTED":
            sections.append("GitHub review decision: CHANGES_REQUESTED")
        if self.feedback:
            lines = ["Review feedback:"]
            for item in self.feedback[-20:]:
                location = f" {item.path}:{item.line}" if item.path and item.line else (
                    f" {item.path}" if item.path else ""
                )
                who = item.author or "reviewer"
                lines.append(f"- [{item.source}] {who}{location}: {item.body.strip()}")
            sections.append("\n".join(lines))
        return "\n\n".join(section for section in sections if section.strip()).strip()


class GitHubCliClient:
    """Thin, testable wrapper around `gh` and `git` for one repository worktree."""

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path).resolve()
        self._repo_slug: str | None = None

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command,
                cwd=str(cwd or self.repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitHubCliError(f"required executable not found: {command[0]}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip()
            raise GitHubCliError(f"{' '.join(command)} failed: {detail}")
        return result

    def doctor(self) -> dict[str, Any]:
        gh = shutil.which("gh")
        if not gh:
            return {"status": "MISSING", "detail": "GitHub CLI (`gh`) is not installed"}
        result = self._run([gh, "auth", "status"], check=False)
        if result.returncode != 0:
            return {
                "status": "AUTH_REQUIRED",
                "detail": (result.stderr or result.stdout or "run gh auth login").strip(),
            }
        return {"status": "READY", "detail": "GitHub CLI authenticated"}

    def _gh(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        executable = shutil.which("gh") or "gh"
        return self._run([executable, *args], check=check)

    def repo_slug(self) -> str:
        if self._repo_slug:
            return self._repo_slug
        result = self._gh(["repo", "view", "--json", "nameWithOwner"])
        try:
            payload = json.loads(result.stdout)
            slug = str(payload["nameWithOwner"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise GitHubCliError("could not resolve GitHub repository name with `gh repo view`") from exc
        self._repo_slug = slug
        return slug

    def push_branch(self, branch: str, *, remote: str = "origin") -> None:
        self._run(["git", "push", "--set-upstream", remote, branch])

    def create_pr(
        self,
        *,
        branch: str,
        base: str,
        title: str,
        body: str,
        remote: str = "origin",
    ) -> GitHubPullRequestSnapshot:
        self.push_branch(branch, remote=remote)
        result = self._gh(
            [
                "pr",
                "create",
                "--base",
                base,
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ]
        )
        url = ""
        for line in reversed(result.stdout.splitlines()):
            if line.strip().startswith("http"):
                url = line.strip()
                break
        return self.snapshot(url or branch)

    def update_pr(self, pr: int | str, *, branch: str, remote: str = "origin") -> GitHubPullRequestSnapshot:
        self.push_branch(branch, remote=remote)
        return self.snapshot(pr)

    def snapshot(self, pr: int | str) -> GitHubPullRequestSnapshot:
        result = self._gh(
            [
                "pr",
                "view",
                str(pr),
                "--json",
                (
                    "number,url,title,state,headRefName,baseRefName,reviewDecision,"
                    "mergeStateStatus,statusCheckRollup,reviews,comments"
                ),
            ]
        )
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubCliError("GitHub CLI returned invalid PR JSON") from exc

        checks = [self._normalize_check(item) for item in raw.get("statusCheckRollup") or []]
        feedback = self._normalize_feedback(raw)

        number = int(raw.get("number") or 0)
        if number <= 0:
            raise GitHubCliError("GitHub PR snapshot did not include a valid number")
        try:
            feedback.extend(self._inline_review_feedback(number))
        except GitHubCliError:
            # Inline review comments enrich the loop but should not make a normal
            # PR snapshot unusable when enterprise permissions restrict the API.
            pass

        canonical = {
            "number": number,
            "state": raw.get("state") or "",
            "review_decision": raw.get("reviewDecision") or "",
            "merge_state_status": raw.get("mergeStateStatus") or "",
            "checks": [item.model_dump(mode="json") for item in checks],
            "feedback": [item.model_dump(mode="json") for item in feedback],
        }
        digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return GitHubPullRequestSnapshot(
            number=number,
            url=str(raw.get("url") or ""),
            title=str(raw.get("title") or ""),
            state=str(raw.get("state") or "OPEN"),
            head_ref=str(raw.get("headRefName") or ""),
            base_ref=str(raw.get("baseRefName") or ""),
            review_decision=str(raw.get("reviewDecision") or ""),
            merge_state_status=str(raw.get("mergeStateStatus") or ""),
            checks=checks,
            feedback=feedback,
            digest=digest,
        )

    def _inline_review_feedback(self, number: int) -> list[GitHubFeedback]:
        slug = self.repo_slug()
        result = self._gh(["api", f"repos/{slug}/pulls/{number}/comments"])
        try:
            rows = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubCliError("GitHub inline-review API returned invalid JSON") from exc
        output: list[GitHubFeedback] = []
        for item in rows if isinstance(rows, list) else []:
            body = str(item.get("body") or "").strip()
            if not body:
                continue
            user = item.get("user") or {}
            output.append(
                GitHubFeedback(
                    source="inline_review",
                    author=str(user.get("login") or ""),
                    body=body,
                    url=str(item.get("html_url") or ""),
                    path=str(item.get("path") or ""),
                    line=item.get("line") or item.get("original_line"),
                )
            )
        return output

    @staticmethod
    def _normalize_check(item: dict[str, Any]) -> GitHubCheck:
        name = item.get("name") or item.get("context") or item.get("workflowName") or "check"
        status = item.get("status") or ""
        conclusion = item.get("conclusion") or item.get("state") or ""
        url = item.get("detailsUrl") or item.get("targetUrl") or ""
        return GitHubCheck(
            name=str(name),
            status=str(status),
            conclusion=str(conclusion),
            url=str(url),
        )

    @staticmethod
    def _normalize_feedback(raw: dict[str, Any]) -> list[GitHubFeedback]:
        output: list[GitHubFeedback] = []
        for review in raw.get("reviews") or []:
            body = str(review.get("body") or "").strip()
            state = str(review.get("state") or "")
            if not body and state.upper() != "CHANGES_REQUESTED":
                continue
            author = review.get("author") or {}
            output.append(
                GitHubFeedback(
                    source="review",
                    author=str(author.get("login") or ""),
                    body=body or f"Review state: {state}",
                    url=str(review.get("url") or ""),
                    state=state,
                )
            )
        for comment in raw.get("comments") or []:
            body = str(comment.get("body") or "").strip()
            if not body:
                continue
            author = comment.get("author") or {}
            output.append(
                GitHubFeedback(
                    source="pr_comment",
                    author=str(author.get("login") or ""),
                    body=body,
                    url=str(comment.get("url") or ""),
                )
            )
        return output

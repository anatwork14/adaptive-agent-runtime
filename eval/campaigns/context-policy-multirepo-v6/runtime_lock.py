"""Campaign-specific runtime lock for the V6 provider-backed ARC study.

This is deliberately outside ARC's generic preregistration schema. It freezes
the provider command, reasoning-effort flags, provider CLI version, and ARC
engine commit that would otherwise remain live operator state. The lock stores
a digest of the effective argv, never argv itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from application.agents import build_agent
from application.config import ConfigStore

SCHEMA = "arc-empirical-runtime-lock-v6"
DEFAULT_ARC_REPO = Path(__file__).resolve().parents[3]


def _canonical(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest_argv(argv: list[str]) -> str:
    return hashlib.sha256(_canonical(argv)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _effective_argv(profile) -> list[str]:
    agent = build_agent(profile)
    builder = getattr(agent, "build_command", None)
    if builder is None:
        return []
    return list(builder())


def _provider_cli_version(argv: list[str], environment: dict[str, str]) -> str:
    if not argv:
        raise SystemExit("provider command is empty; cannot freeze CLI version")
    try:
        proc = subprocess.run(
            [argv[0], "--version"],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            f"provider executable {argv[0]!r} is not installed; cannot freeze runtime"
        ) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "version command failed").strip()
        raise SystemExit(f"cannot read provider CLI version: {detail}")
    version = (proc.stdout or proc.stderr).strip().splitlines()
    if not version:
        raise SystemExit("provider CLI returned an empty version string")
    return version[0].strip()


def _git_head(path: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        detail = (proc.stderr or proc.stdout or "git rev-parse failed").strip()
        raise SystemExit(f"cannot resolve ARC engine commit in {path}: {detail}")
    return proc.stdout.strip()


def _require_clean_git(path: Path, *, label: str) -> None:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git status failed").strip()
        raise SystemExit(f"cannot inspect {label} worktree in {path}: {detail}")
    status = proc.stdout.strip()
    if status:
        preview = "; ".join(status.splitlines()[:10])
        raise SystemExit(f"{label} worktree must be clean for a reproducible campaign: {preview}")


def _arc_repo(path: Path | None) -> Path:
    return (path or DEFAULT_ARC_REPO).resolve()


def _codex_runtime_identity(profile, environment: dict[str, str]) -> dict[str, str]:
    if profile.provider != "codex":
        return {}
    if not profile.codex_home or not profile.codex_config_path:
        raise SystemExit("codex profile must declare codex_home and codex_config_path")
    home = Path(profile.codex_home).expanduser().resolve()
    config_path = Path(profile.codex_config_path).expanduser().resolve()
    if not home.is_dir():
        raise SystemExit(f"dedicated Codex home does not exist: {home}")
    if not config_path.is_file():
        raise SystemExit(f"dedicated Codex config does not exist: {config_path}")
    try:
        config_path.relative_to(home)
    except ValueError as exc:
        raise SystemExit("dedicated Codex config must live inside codex_home") from exc
    if environment.get("CODEX_HOME") != str(home):
        raise SystemExit("Codex subprocess environment does not use the configured codex_home")
    return {
        "codex_home": str(home),
        "codex_config_path": str(config_path),
        "codex_config_sha256": _sha256_file(config_path),
    }


def runtime_payload(repo: Path, profile_name: str) -> dict[str, Any]:
    config = ConfigStore(repo).load()
    profile = config.agents.get(profile_name)
    if profile is None:
        raise SystemExit(f"profile {profile_name!r} is not configured in {repo}")
    agent = build_agent(profile)
    argv = list(agent.build_command())
    environment = agent.execution_environment()
    payload = {
        "schema_version": SCHEMA,
        "profile": profile.name,
        "provider": profile.provider,
        "model": profile.model,
        "role": profile.role,
        "capabilities": sorted(set(profile.capabilities)),
        "effective_argv_sha256": _digest_argv(argv),
        "provider_cli_version": _provider_cli_version(argv, environment),
        "env_allow": sorted(set(profile.env_allow)),
        "provider_execution_timeout_seconds": config.provider_execution_timeout_seconds,
        "auth_mode": "chatgpt_subscription" if profile.provider == "codex" else None,
    }
    payload.update(_codex_runtime_identity(profile, environment))
    return payload


def lock_digest(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body["lock_digest"] = ""
    return hashlib.sha256(_canonical(body)).hexdigest()


def freeze(
    repo: Path,
    profile: str,
    output: Path,
    arc_repo: Path | None,
    *,
    provider_execution_timeout_seconds: int,
) -> None:
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing lock: {output}")
    arc_path = _arc_repo(arc_repo)
    _require_clean_git(arc_path, label="ARC engine")
    payload = runtime_payload(repo, profile)
    if payload["provider_execution_timeout_seconds"] != provider_execution_timeout_seconds:
        raise SystemExit(
            "provider execution timeout does not match the V6 contract: "
            f"expected={provider_execution_timeout_seconds}, "
            f"actual={payload['provider_execution_timeout_seconds']}"
        )
    payload.update(
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "arc_commit": _git_head(arc_path),
            "arc_worktree_clean": True,
            "lock_digest": "",
        }
    )
    payload["lock_digest"] = lock_digest(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"runtime_lock={output.resolve()}")
    print(f"lock_digest={payload['lock_digest']}")
    print(f"arc_commit={payload['arc_commit']}")
    print("arc_worktree_clean=true")
    print(f"effective_argv_sha256={payload['effective_argv_sha256']}")
    print(f"provider_cli_version={payload['provider_cli_version']}")


def verify(
    repo: Path,
    profile: str,
    lock: Path,
    arc_repo: Path | None = None,
    *,
    provider_execution_timeout_seconds: int,
) -> None:
    frozen = json.loads(lock.read_text(encoding="utf-8"))
    if frozen.get("schema_version") != SCHEMA:
        raise SystemExit("unsupported runtime-lock schema")
    if frozen.get("provider_execution_timeout_seconds") != provider_execution_timeout_seconds:
        raise SystemExit("runtime-lock provider execution timeout does not match V6 contract")
    if frozen.get("lock_digest") != lock_digest(frozen):
        raise SystemExit("runtime-lock digest mismatch: lock was modified")
    arc_path = _arc_repo(arc_repo)
    _require_clean_git(arc_path, label="ARC engine")
    live = runtime_payload(repo, profile)
    live["arc_commit"] = _git_head(arc_path)
    live["arc_worktree_clean"] = True
    keys = (
        "profile",
        "provider",
        "model",
        "role",
        "capabilities",
        "effective_argv_sha256",
        "provider_cli_version",
        "env_allow",
        "provider_execution_timeout_seconds",
        "auth_mode",
        "arc_commit",
        "arc_worktree_clean",
    )
    if frozen.get("provider") == "codex":
        keys += ("codex_home", "codex_config_path", "codex_config_sha256")
    mismatches = [key for key in keys if frozen.get(key) != live.get(key)]
    if mismatches:
        details = ", ".join(
            f"{key}: frozen={frozen.get(key)!r}, live={live.get(key)!r}" for key in mismatches
        )
        raise SystemExit("runtime contract drift: " + details)
    print("runtime_contract=VERIFIED")
    print(f"lock_digest={frozen['lock_digest']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    freeze_p = sub.add_parser("freeze")
    freeze_p.add_argument("--repo", type=Path, default=Path("."))
    freeze_p.add_argument("--profile", default="builder")
    freeze_p.add_argument("--output", type=Path, required=True)
    freeze_p.add_argument("--arc-repo", type=Path)
    freeze_p.add_argument("--provider-execution-timeout-seconds", type=int, required=True)
    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--repo", type=Path, default=Path("."))
    verify_p.add_argument("--profile", default="builder")
    verify_p.add_argument("--lock", type=Path, required=True)
    verify_p.add_argument("--arc-repo", type=Path)
    verify_p.add_argument("--provider-execution-timeout-seconds", type=int, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(
            args.repo.resolve(),
            args.profile,
            args.output,
            args.arc_repo,
            provider_execution_timeout_seconds=args.provider_execution_timeout_seconds,
        )
    else:
        verify(
            args.repo.resolve(),
            args.profile,
            args.lock,
            args.arc_repo,
            provider_execution_timeout_seconds=args.provider_execution_timeout_seconds,
        )


if __name__ == "__main__":
    main()

"""Campaign-specific runtime lock for the first provider-backed ARC study.

This is deliberately outside ARC's generic preregistration schema. It closes
empirical reproducibility gaps in v0.16 without changing historical plan
digests: profile command overrides, reasoning-effort flags, and provider CLI
version are otherwise live operator state. The lock stores a digest of the
effective argv, never argv itself.
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

SCHEMA = "arc-empirical-runtime-lock-v2"


def _canonical(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest_argv(argv: list[str]) -> str:
    return hashlib.sha256(_canonical(argv)).hexdigest()


def _effective_argv(profile) -> list[str]:
    agent = build_agent(profile)
    builder = getattr(agent, "build_command", None)
    if builder is None:
        return []
    return list(builder())


def _provider_cli_version(argv: list[str]) -> str:
    if not argv:
        raise SystemExit("provider command is empty; cannot freeze CLI version")
    try:
        proc = subprocess.run(
            [argv[0], "--version"],
            capture_output=True,
            text=True,
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
    return proc.stdout.strip() if proc.returncode == 0 else ""


def runtime_payload(repo: Path, profile_name: str) -> dict[str, Any]:
    config = ConfigStore(repo).load()
    profile = config.agents.get(profile_name)
    if profile is None:
        raise SystemExit(f"profile {profile_name!r} is not configured in {repo}")
    argv = _effective_argv(profile)
    return {
        "schema_version": SCHEMA,
        "profile": profile.name,
        "provider": profile.provider,
        "model": profile.model,
        "role": profile.role,
        "capabilities": sorted(set(profile.capabilities)),
        "effective_argv_sha256": _digest_argv(argv),
        "provider_cli_version": _provider_cli_version(argv),
        "env_allow": sorted(set(profile.env_allow)),
    }


def lock_digest(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body["lock_digest"] = ""
    return hashlib.sha256(_canonical(body)).hexdigest()


def freeze(repo: Path, profile: str, output: Path, arc_repo: Path | None) -> None:
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing lock: {output}")
    payload = runtime_payload(repo, profile)
    payload.update(
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "arc_commit": _git_head(arc_repo.resolve()) if arc_repo else "",
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
    print(f"effective_argv_sha256={payload['effective_argv_sha256']}")
    print(f"provider_cli_version={payload['provider_cli_version']}")


def verify(repo: Path, profile: str, lock: Path) -> None:
    frozen = json.loads(lock.read_text(encoding="utf-8"))
    if frozen.get("schema_version") != SCHEMA:
        raise SystemExit("unsupported runtime-lock schema")
    if frozen.get("lock_digest") != lock_digest(frozen):
        raise SystemExit("runtime-lock digest mismatch: lock was modified")
    live = runtime_payload(repo, profile)
    keys = (
        "profile",
        "provider",
        "model",
        "role",
        "capabilities",
        "effective_argv_sha256",
        "provider_cli_version",
        "env_allow",
    )
    mismatches = [key for key in keys if frozen.get(key) != live.get(key)]
    if mismatches:
        details = ", ".join(
            f"{key}: frozen={frozen.get(key)!r}, live={live.get(key)!r}"
            for key in mismatches
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
    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--repo", type=Path, default=Path("."))
    verify_p.add_argument("--profile", default="builder")
    verify_p.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.repo.resolve(), args.profile, args.output, args.arc_repo)
    else:
        verify(args.repo.resolve(), args.profile, args.lock)


if __name__ == "__main__":
    main()

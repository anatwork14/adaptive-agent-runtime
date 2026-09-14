"""Finalize a completed provider campaign into integrity-checked thesis evidence.

This command is deliberately offline. It never loads an agent profile, checks
provider authentication, or starts provider inference. It consumes only a
successful ``execute_campaign.py`` attempt, verifies the persisted repository
exports and hierarchical meta-analysis by SHA-256, then writes a concise
B7-oriented evidence summary plus a self-digesting evidence manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

CAMPAIGN_ID = "context-policy-multirepo-v6"
REPOSITORY_ORDER = ("click", "httpx", "python-dotenv")
METRIC_ORDER = (
    "resolved_rate",
    "mean_context_tokens",
    "mean_provider_tokens",
    "mean_cost_usd",
    "p95_end_to_end_latency_ms",
    "stale_delivery_rate",
)
HIGHER_IS_BETTER = {"resolved_rate"}


def _canonical(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} must contain one JSON object: {path}")
    return payload


def _inside(root: Path, raw: str | Path, *, label: str) -> Path:
    root = root.resolve()
    path = Path(raw)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise SystemExit(f"{label} escapes campaign attempt root: {resolved}")
    return resolved


def _safe_child(root: Path, name: str, *, label: str) -> Path:
    candidate = Path(name)
    if not name or candidate.is_absolute() or candidate.name != name:
        raise SystemExit(f"invalid {label} file name: {name!r}")
    path = (root.resolve() / name).resolve()
    if path.parent != root.resolve():
        raise SystemExit(f"{label} escapes artifact directory: {path}")
    return path


def _verify_repository_export(export_dir: Path, expected_plan_digest: str) -> list[Path]:
    manifest_path = export_dir / "export_manifest.json"
    manifest = _read_json(manifest_path, label="repository export manifest")
    if manifest.get("plan_digest") != expected_plan_digest:
        raise SystemExit(
            f"repository export plan digest mismatch in {export_dir}: "
            f"expected={expected_plan_digest}, actual={manifest.get('plan_digest')}"
        )
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SystemExit(f"repository export manifest has no files: {manifest_path}")
    verified = [manifest_path]
    for key, metadata in files.items():
        if not isinstance(metadata, dict):
            raise SystemExit(f"invalid repository export entry {key!r}: {manifest_path}")
        path = _safe_child(export_dir, str(metadata.get("path") or ""), label="export")
        if not path.is_file():
            raise SystemExit(f"missing repository export file: {path}")
        actual = _sha256_file(path)
        expected = str(metadata.get("sha256") or "")
        if actual != expected:
            raise SystemExit(
                f"repository export hash mismatch for {path}: expected={expected}, actual={actual}"
            )
        verified.append(path)
    return verified


def _verify_meta_export(meta_dir: Path, expected_plan_digest: str) -> list[Path]:
    manifest_path = meta_dir / "meta_export_manifest.json"
    manifest = _read_json(manifest_path, label="meta export manifest")
    if manifest.get("meta_plan_digest") != expected_plan_digest:
        raise SystemExit("meta export plan digest does not match execution manifest")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SystemExit(f"meta export manifest has no files: {manifest_path}")
    verified = [manifest_path]
    for name, expected in files.items():
        path = _safe_child(meta_dir, str(name), label="meta export")
        if not path.is_file():
            raise SystemExit(f"missing meta export file: {path}")
        actual = _sha256_file(path)
        if actual != str(expected):
            raise SystemExit(
                f"meta export hash mismatch for {path}: expected={expected}, actual={actual}"
            )
        verified.append(path)
    return verified


def _orient_metric(
    comparison: dict[str, Any],
    metric_name: str,
) -> dict[str, Any] | None:
    """Orient a frozen A-B meta effect as B7-comparator without changing inference."""
    baseline_a = str(comparison.get("baseline_a") or "")
    baseline_b = str(comparison.get("baseline_b") or "")
    if "B7" not in (baseline_a, baseline_b):
        return None
    comparator = baseline_b if baseline_a == "B7" else baseline_a
    sign = 1.0 if baseline_a == "B7" else -1.0
    raw = comparison.get("metrics", {}).get(metric_name)
    if not isinstance(raw, dict):
        return None

    def oriented(value: Any) -> float | None:
        if value is None:
            return None
        return sign * float(value)

    mean = oriented(raw.get("mean_delta"))
    raw_lower = raw.get("ci_lower")
    raw_upper = raw.get("ci_upper")
    if raw_lower is None or raw_upper is None:
        lower = None
        upper = None
    elif sign > 0:
        lower = float(raw_lower)
        upper = float(raw_upper)
    else:
        lower = -float(raw_upper)
        upper = -float(raw_lower)

    evidence = "unobserved"
    if mean is not None and lower is not None and upper is not None:
        if lower <= 0.0 <= upper:
            evidence = "uncertain_ci_includes_zero"
        else:
            favorable = mean > 0.0 if metric_name in HIGHER_IS_BETTER else mean < 0.0
            evidence = "direction_favors_B7" if favorable else "direction_favors_comparator"

    return {
        "comparison": f"B7-{comparator}",
        "comparator": comparator,
        "metric": metric_name,
        "mean_delta": mean,
        "ci_lower": lower,
        "ci_upper": upper,
        "repository_count": int(raw.get("repository_count") or 0),
        "repetition_count": int(raw.get("repetition_count") or 0),
        "preferred_direction": "higher" if metric_name in HIGHER_IS_BETTER else "lower",
        "evidence": evidence,
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    return f"{float(value):+.{digits}f}"


def _report_markdown(
    execution: dict[str, Any],
    meta: dict[str, Any],
    claims: list[dict[str, Any]],
    repository_rows: list[dict[str, str]],
) -> str:
    lines = [
        f"# Final Evidence Report — {CAMPAIGN_ID}",
        "",
        "This report is generated only from persisted campaign artifacts. The finalization step performs no provider inference and does not alter the preregistered analysis.",
        "",
        "## Frozen execution provenance",
        "",
        f"- Attempt: `{execution['attempt_id']}`",
        f"- ARC commit: `{execution['arc_commit']}`",
        f"- Provider CLI: `{execution.get('provider_cli_version')}`",
        f"- Runtime-lock digest: `{execution['runtime_lock_digest']}`",
        f"- Freeze-manifest SHA-256: `{execution.get('freeze_manifest_sha256')}`",
        f"- Meta-plan digest: `{execution['meta_plan_digest']}`",
        f"- Repository clusters: `{meta['repository_count']}`",
        "",
        "## Repository studies",
        "",
        "| Repository | Status | Plan digest | Study artifact |",
        "|---|---|---|---|",
    ]
    for slug in REPOSITORY_ORDER:
        state = execution["repositories"][slug]
        lines.append(
            f"| {slug} | {state['status']} | `{state['plan_digest']}` | `{state['study_dir']}` |"
        )

    lines.extend(
        [
            "",
            "## B7-oriented preregistered meta-effects",
            "",
            "Deltas below are re-oriented only for readability as **B7 − comparator**. The underlying hierarchical bootstrap remains exactly the preregistered A−B analysis. Positive is favorable only for resolved rate; lower values are favorable for token, cost, latency, and stale-delivery metrics.",
            "",
            "| Comparison | Metric | B7−comparator Δ | Hierarchical CI | Repos / paired reps | Reading |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for item in claims:
        lines.append(
            "| {comparison} | {metric} | {mean} | [{lower}, {upper}] | {repos} / {reps} | {evidence} |".format(
                comparison=item["comparison"],
                metric=item["metric"],
                mean=_fmt(item["mean_delta"]),
                lower=_fmt(item["ci_lower"]),
                upper=_fmt(item["ci_upper"]),
                repos=item["repository_count"],
                reps=item["repetition_count"],
                evidence=item["evidence"].replace("_", " "),
            )
        )

    if repository_rows:
        lines.extend(
            [
                "",
                "## Repository-level resolved-rate effects",
                "",
                "These are diagnostic cluster effects, not independent task-level samples.",
                "",
                "| Repository | Pair | Mean Δ (frozen A−B orientation) | Repetitions |",
                "|---|---|---:|---:|",
            ]
        )
        for row in repository_rows:
            if row.get("metric") != "resolved_rate":
                continue
            pair = f"{row.get('baseline_a')}-{row.get('baseline_b')}"
            if "B7" not in pair:
                continue
            lines.append(
                f"| {row.get('benchmark_id')} | {pair} | {_fmt(row.get('repository_mean_delta'))} | {row.get('repetitions')} |"
            )

    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- The repository is the top-level inference cluster; task rows must not be treated as independent observations.",
            "- `direction_favors_*` means the preregistered hierarchical bootstrap interval excludes zero in that direction. It is not a universal claim beyond the frozen repositories and provider configuration.",
            "- `uncertain_ci_includes_zero` means the observed direction is not cleanly separated from zero by the frozen interval.",
            "- Nullable provider-token or cost measurements remain nullable; missing coverage must not be converted to zero.",
            "- Repository/task-specific analyses are diagnostic unless they were explicitly preregistered as primary.",
            "- Opaque provider-side model revisions behind a model alias remain an external reproducibility limitation even though ARC, CLI version, argv, plans, hidden tests, and repository commits are frozen.",
            "",
            "## Artifact integrity",
            "",
            "All repository tidy exports and all hierarchical meta-export files were SHA-256 verified before this report was written. `evidence-manifest.json` records hashes for the verified inputs and final outputs.",
            "",
        ]
    )
    return "\n".join(lines)


def _repository_effect_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"missing repository-effects CSV: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _evidence_manifest_digest(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body["manifest_digest"] = ""
    return hashlib.sha256(_canonical(body)).hexdigest()


def finalize_campaign(execution_root: Path, output_dir: Path | None = None) -> Path:
    root = execution_root.resolve()
    execution_path = root / "execution-manifest.json"
    execution = _read_json(execution_path, label="execution manifest")
    if execution.get("schema_version") != "arc-campaign-execution-v6":
        raise SystemExit("unsupported campaign execution-manifest schema")
    if execution.get("campaign_id") != CAMPAIGN_ID:
        raise SystemExit("execution manifest belongs to a different campaign")
    if execution.get("status") != "SUCCEEDED":
        raise SystemExit(
            f"only a successful campaign can be finalized; status={execution.get('status')!r}"
        )
    if execution.get("provider_execution_started") is not True:
        raise SystemExit(
            "successful execution manifest must record provider_execution_started=true"
        )

    input_files: set[Path] = {execution_path}
    expected_plan_digests: set[str] = set()
    repositories = execution.get("repositories")
    if not isinstance(repositories, dict) or set(repositories) != set(REPOSITORY_ORDER):
        raise SystemExit("execution manifest does not contain exactly the frozen repositories")

    for slug in REPOSITORY_ORDER:
        state = repositories[slug]
        if state.get("status") != "SUCCEEDED":
            raise SystemExit(f"repository {slug} is not successful in execution manifest")
        plan_digest = str(state.get("plan_digest") or "")
        if len(plan_digest) != 64:
            raise SystemExit(f"repository {slug} has an invalid plan digest")
        expected_plan_digests.add(plan_digest)
        study_dir = _inside(root, str(state.get("study_dir") or ""), label=f"{slug} study")
        export_dir = _inside(root, str(state.get("export_dir") or ""), label=f"{slug} export")
        for name in ("study.json", "provenance.json", "aggregates.json"):
            path = _safe_child(study_dir, name, label=f"{slug} study artifact")
            if not path.is_file():
                raise SystemExit(f"missing completed study artifact: {path}")
            input_files.add(path)
        provenance = _read_json(study_dir / "provenance.json", label=f"{slug} provenance")
        if provenance.get("extra", {}).get("plan_digest") != plan_digest:
            raise SystemExit(f"completed study provenance plan digest mismatch for {slug}")
        input_files.update(_verify_repository_export(export_dir, plan_digest))

    meta_state = execution.get("meta")
    if not isinstance(meta_state, dict) or meta_state.get("status") != "SUCCEEDED":
        raise SystemExit("execution manifest does not contain a successful meta-analysis")
    meta_dir = _inside(root, str(meta_state.get("output_dir") or ""), label="meta output")
    meta_plan_digest = str(execution.get("meta_plan_digest") or "")
    input_files.update(_verify_meta_export(meta_dir, meta_plan_digest))
    meta = _read_json(meta_dir / "meta_study.json", label="meta study")
    if meta.get("meta_plan_digest") != meta_plan_digest:
        raise SystemExit("meta_study.json plan digest differs from execution manifest")
    studies = meta.get("studies")
    if (
        not isinstance(studies, list)
        or {str(item.get("plan_digest") or "") for item in studies if isinstance(item, dict)}
        != expected_plan_digests
    ):
        raise SystemExit("meta study repository plan set differs from execution manifest")
    if int(meta.get("repository_count") or 0) != len(REPOSITORY_ORDER):
        raise SystemExit("meta study repository count differs from frozen campaign")

    comparisons = meta.get("comparisons")
    if not isinstance(comparisons, list):
        raise SystemExit("meta_study.json comparisons must be a list")
    claims: list[dict[str, Any]] = []
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            continue
        for metric in METRIC_ORDER:
            oriented = _orient_metric(comparison, metric)
            if oriented is not None:
                claims.append(oriented)

    repository_rows = _repository_effect_rows(meta_dir / "repository_effects.csv")
    final_dir = output_dir.resolve() if output_dir else root / "final-evidence"
    if final_dir.exists():
        raise SystemExit(f"refusing to overwrite existing final evidence directory: {final_dir}")
    if final_dir != root and not final_dir.is_relative_to(root):
        raise SystemExit("final evidence directory must remain inside the campaign attempt root")
    final_dir.mkdir(parents=True, exist_ok=False)

    claim_payload = {
        "schema_version": "arc-campaign-claims-v6",
        "campaign_id": CAMPAIGN_ID,
        "attempt_id": execution["attempt_id"],
        "meta_plan_digest": meta_plan_digest,
        "analysis_unit": meta.get("analysis_unit"),
        "repository_count": meta.get("repository_count"),
        "orientation": "B7-minus-comparator",
        "metrics": claims,
    }
    claim_path = final_dir / "claim_summary.json"
    claim_path.write_text(
        json.dumps(claim_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = final_dir / "final_report.md"
    report_path.write_text(
        _report_markdown(execution, meta, claims, repository_rows),
        encoding="utf-8",
    )

    manifest_payload: dict[str, Any] = {
        "schema_version": "arc-campaign-evidence-v6",
        "campaign_id": CAMPAIGN_ID,
        "attempt_id": execution["attempt_id"],
        "arc_commit": execution["arc_commit"],
        "runtime_lock_digest": execution["runtime_lock_digest"],
        "meta_plan_digest": meta_plan_digest,
        "inputs": {
            str(path.relative_to(root)): _sha256_file(path)
            for path in sorted(input_files, key=lambda item: str(item))
        },
        "outputs": {
            report_path.name: _sha256_file(report_path),
            claim_path.name: _sha256_file(claim_path),
        },
        "manifest_digest": "",
    }
    manifest_payload["manifest_digest"] = _evidence_manifest_digest(manifest_payload)
    manifest_path = final_dir / "evidence-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"final_evidence={final_dir.resolve()}")
    print(f"final_report={report_path.resolve()}")
    print(f"claim_summary={claim_path.resolve()}")
    print(f"evidence_manifest={manifest_path.resolve()}")
    print(f"evidence_manifest_digest={manifest_payload['manifest_digest']}")
    return final_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "execution_root",
        type=Path,
        help="Successful context-policy-multirepo-v6 campaign attempt directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional final evidence directory; must remain inside execution_root",
    )
    args = parser.parse_args()
    finalize_campaign(args.execution_root, args.output_dir)


if __name__ == "__main__":
    main()

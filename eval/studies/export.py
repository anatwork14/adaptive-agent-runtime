"""Offline tidy exports for completed ARC repeated-study artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from eval.io import read_measurements_jsonl


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise ValueError(f"required study artifact is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def export_study_tidy(
    study_dir: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Flatten a completed repeated study into task/repetition/pair tables.

    Export is intentionally offline: it reads only persisted benchmark artifacts
    and never opens the live ARC EventStore or source repository.
    """
    root = Path(study_dir).resolve()
    study = _read_json(root / "study.json")
    provenance = _read_json(root / "provenance.json")
    aggregates = _read_json(root / "aggregates.json")

    study_id = str(study["study_id"])
    benchmark_id = str(study["benchmark_id"])
    base_commit = str(study["base_commit"])
    target = Path(output_dir).resolve() if output_dir else root / "exports"
    target.mkdir(parents=True, exist_ok=True)

    task_rows: list[dict[str, Any]] = []
    repetition_rows: list[dict[str, Any]] = []

    repetitions = study.get("repetitions")
    if not isinstance(repetitions, list) or not repetitions:
        raise ValueError("study.json does not contain any repetitions")

    for repeat_index, repeat in enumerate(repetitions, start=1):
        repeat_root = root / str(repeat["artifact_dir"])
        paired = _read_json(repeat_root / "paired_run.json")
        run_id = str(repeat["run_id"])
        execution_order = list(repeat["execution_order"])
        baseline_meta = paired.get("baselines", {})
        if not isinstance(baseline_meta, dict):
            raise ValueError(f"invalid paired_run baselines for {run_id}")

        for baseline in sorted(baseline_meta):
            metadata = baseline_meta[baseline]
            baseline_dir = repeat_root / str(metadata["artifact_dir"])
            summary = _read_json(baseline_dir / "summary.json")
            measurements = read_measurements_jsonl(baseline_dir / "measurements.jsonl")
            try:
                order_position = execution_order.index(baseline) + 1
            except ValueError as exc:
                raise ValueError(
                    f"baseline {baseline} missing from execution_order for {run_id}"
                ) from exc

            repetition_row = {
                "study_id": study_id,
                "benchmark_id": benchmark_id,
                "base_commit": base_commit,
                "repeat_index": repeat_index,
                "run_id": run_id,
                "repeat_seed": (
                    study.get("repeat_seeds", [])[repeat_index - 1]
                    if repeat_index - 1 < len(study.get("repeat_seeds", []))
                    else None
                ),
                "baseline": baseline,
                "order_position": order_position,
                "execution_order": execution_order,
                "initial_commit": metadata.get("initial_commit"),
                "final_commit": metadata.get("final_commit"),
                "event_count": metadata.get("event_count"),
                **summary,
            }
            repetition_rows.append(repetition_row)

            for measurement in measurements:
                task_rows.append(
                    {
                        "study_id": study_id,
                        "benchmark_id": benchmark_id,
                        "base_commit": base_commit,
                        "repeat_index": repeat_index,
                        "run_id": run_id,
                        "repeat_seed": repetition_row["repeat_seed"],
                        "baseline": baseline,
                        "order_position": order_position,
                        **measurement.model_dump(mode="json"),
                    }
                )

    pair_rows: list[dict[str, Any]] = []
    if not isinstance(aggregates, list):
        raise ValueError("aggregates.json root must be a list")
    for aggregate in aggregates:
        pair = f"{aggregate['baseline_a']}-{aggregate['baseline_b']}"
        common = {
            "study_id": study_id,
            "benchmark_id": benchmark_id,
            "base_commit": base_commit,
            "pair": pair,
            "baseline_a": aggregate["baseline_a"],
            "baseline_b": aggregate["baseline_b"],
            "repetitions": aggregate["repetitions"],
            "wins_a": aggregate["wins_a"],
            "ties": aggregate["ties"],
            "wins_b": aggregate["wins_b"],
        }
        for key, metric in aggregate.items():
            if not key.endswith("_delta") or not isinstance(metric, dict):
                continue
            pair_rows.append(
                {
                    **common,
                    "metric": key.removesuffix("_delta"),
                    "sample_count": metric.get("sample_count"),
                    "mean_delta": metric.get("mean_delta"),
                    "median_delta": metric.get("median_delta"),
                    "ci_lower": metric.get("ci_lower"),
                    "ci_upper": metric.get("ci_upper"),
                }
            )

    outputs = {
        "tasks_csv": target / "tasks.csv",
        "tasks_jsonl": target / "tasks.jsonl",
        "repetitions_csv": target / "repetitions.csv",
        "repetitions_jsonl": target / "repetitions.jsonl",
        "pairs_csv": target / "pairs.csv",
        "pairs_jsonl": target / "pairs.jsonl",
    }
    _write_csv(outputs["tasks_csv"], task_rows)
    _write_jsonl(outputs["tasks_jsonl"], task_rows)
    _write_csv(outputs["repetitions_csv"], repetition_rows)
    _write_jsonl(outputs["repetitions_jsonl"], repetition_rows)
    _write_csv(outputs["pairs_csv"], pair_rows)
    _write_jsonl(outputs["pairs_jsonl"], pair_rows)

    export_manifest = {
        "study_id": study_id,
        "benchmark_id": benchmark_id,
        "base_commit": base_commit,
        "plan_digest": provenance.get("extra", {}).get("plan_digest"),
        "row_counts": {
            "tasks": len(task_rows),
            "repetitions": len(repetition_rows),
            "pairs": len(pair_rows),
        },
        "files": {
            key: {"path": path.name, "sha256": _file_digest(path)}
            for key, path in outputs.items()
        },
    }
    manifest_path = target / "export_manifest.json"
    manifest_path.write_text(
        json.dumps(export_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outputs["manifest"] = manifest_path
    return outputs

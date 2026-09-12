"""Evaluation, benchmarks, fault injection, and reproducible research records."""

from eval.analysis.stats import BootstrapResult, StatisticalAnalyzer
from eval.comparison import (
    PairedComparison,
    compare_paired_measurements,
    validate_comparable_manifests,
)
from eval.faults.injector import FaultInjector, FaultType
from eval.grading.hidden_tests import GradingResult, HiddenTestGrader
from eval.io import (
    load_manifest,
    read_measurements_jsonl,
    write_measurements_jsonl,
    write_summary_json,
)
from eval.models import (
    BenchmarkManifest,
    EvaluationSummary,
    EvaluationTaskSpec,
    FaultSpec,
    TaskMeasurement,
)
from eval.runners.experiment import ExperimentRunner, ExperimentSummary, TaskMetric
from eval.telemetry import TraceTelemetry, collect_trace_telemetry

__all__ = [
    "FaultInjector",
    "FaultType",
    "HiddenTestGrader",
    "GradingResult",
    "StatisticalAnalyzer",
    "BootstrapResult",
    "ExperimentRunner",
    "ExperimentSummary",
    "TaskMetric",
    "BenchmarkManifest",
    "EvaluationTaskSpec",
    "FaultSpec",
    "TaskMeasurement",
    "EvaluationSummary",
    "TraceTelemetry",
    "collect_trace_telemetry",
    "load_manifest",
    "read_measurements_jsonl",
    "write_measurements_jsonl",
    "write_summary_json",
    "PairedComparison",
    "validate_comparable_manifests",
    "compare_paired_measurements",
]

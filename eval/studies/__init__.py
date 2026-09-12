"""Pre-registration, suite aggregation, and offline export helpers for ARC studies."""

from eval.studies.export import export_study_tidy
from eval.studies.preregistration import (
    PRIMARY_METRICS,
    PreregisteredStudy,
    StudyDesign,
    StudyRuntimeContract,
    compute_plan_digest,
    create_preregistration,
    load_preregistration,
    save_preregistration,
    tree_digest,
    validate_execution_environment,
)
from eval.studies.suite import (
    HierarchicalMetric,
    HierarchicalPairAggregate,
    PreregisteredSuite,
    SuiteAggregationResult,
    SuiteDesign,
    SuiteMember,
    aggregate_suite_studies,
    compute_suite_digest,
    create_suite,
    load_suite,
    save_suite,
)

__all__ = [
    "PRIMARY_METRICS",
    "PreregisteredStudy",
    "StudyDesign",
    "StudyRuntimeContract",
    "compute_plan_digest",
    "create_preregistration",
    "load_preregistration",
    "save_preregistration",
    "tree_digest",
    "validate_execution_environment",
    "export_study_tidy",
    "SuiteMember",
    "SuiteDesign",
    "PreregisteredSuite",
    "HierarchicalMetric",
    "HierarchicalPairAggregate",
    "SuiteAggregationResult",
    "compute_suite_digest",
    "create_suite",
    "save_suite",
    "load_suite",
    "aggregate_suite_studies",
]

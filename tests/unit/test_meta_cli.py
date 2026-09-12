from typer.testing import CliRunner

from cli.bootstrap import app


runner = CliRunner()


def test_benchmark_help_registers_cross_repository_meta_commands() -> None:
    result = runner.invoke(app, ["benchmark", "--help"])
    assert result.exit_code == 0
    assert "meta-preregister" in result.output
    assert "meta" in result.output


def test_meta_preregister_requires_multiple_repository_plans() -> None:
    result = runner.invoke(
        app,
        [
            "benchmark",
            "meta-preregister",
            "only-one.json",
            "--meta-id",
            "meta-01",
        ],
    )
    assert result.exit_code != 0
    assert "at least two repository study plans" in result.output


def test_meta_analysis_requires_multiple_study_directories() -> None:
    result = runner.invoke(
        app,
        [
            "benchmark",
            "meta",
            "meta-plan.json",
            "only-one-study",
        ],
    )
    assert result.exit_code != 0
    assert "at least two study directories" in result.output

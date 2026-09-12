from typer.testing import CliRunner

from cli.bootstrap import app


runner = CliRunner()


def test_installed_cli_registers_benchmark_surfaces() -> None:
    result = runner.invoke(app, ["benchmark", "--help"])
    assert result.exit_code == 0
    assert "paired" in result.output
    assert "repeated" in result.output
    assert "reproducible ARC research benchmarks" in result.output


def test_paired_benchmark_requires_multiple_manifests() -> None:
    result = runner.invoke(app, ["benchmark", "paired", "only-one.yaml"])
    assert result.exit_code != 0
    assert "at least two manifests" in result.output


def test_repeated_benchmark_requires_multiple_manifests() -> None:
    result = runner.invoke(app, ["benchmark", "repeated", "only-one.yaml"])
    assert result.exit_code != 0
    assert "at least two manifests" in result.output


def test_repeated_benchmark_help_exposes_statistical_controls() -> None:
    result = runner.invoke(app, ["benchmark", "repeated", "--help"])
    assert result.exit_code == 0
    assert "--repeats" in result.output
    assert "--bootstrap-samples" in result.output
    assert "--ci" in result.output

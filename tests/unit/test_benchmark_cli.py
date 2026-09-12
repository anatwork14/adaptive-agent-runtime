from typer.testing import CliRunner

from cli.bootstrap import app


runner = CliRunner()


def test_installed_cli_registers_paired_benchmark_surface() -> None:
    result = runner.invoke(app, ["benchmark", "--help"])
    assert result.exit_code == 0
    assert "paired" in result.stdout
    assert "reproducible ARC research benchmarks" in result.stdout


def test_paired_benchmark_requires_multiple_manifests() -> None:
    result = runner.invoke(app, ["benchmark", "paired", "only-one.yaml"])
    assert result.exit_code != 0
    assert "at least two manifests" in result.stdout

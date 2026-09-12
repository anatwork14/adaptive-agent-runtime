import re

from typer.testing import CliRunner

from cli.bootstrap import app


runner = CliRunner()
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _plain_output(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


def test_installed_cli_registers_benchmark_surfaces() -> None:
    result = runner.invoke(app, ["benchmark", "--help"])
    assert result.exit_code == 0
    plain = _plain_output(result.output)
    assert "paired" in plain
    assert "repeated" in plain
    assert "reproducible ARC research benchmarks" in plain


def test_paired_benchmark_requires_multiple_manifests() -> None:
    result = runner.invoke(app, ["benchmark", "paired", "only-one.yaml"])
    assert result.exit_code != 0
    assert "at least two manifests" in _plain_output(result.output)


def test_repeated_benchmark_requires_multiple_manifests() -> None:
    result = runner.invoke(app, ["benchmark", "repeated", "only-one.yaml"])
    assert result.exit_code != 0
    assert "at least two manifests" in _plain_output(result.output)


def test_repeated_benchmark_help_exposes_statistical_controls() -> None:
    result = runner.invoke(app, ["benchmark", "repeated", "--help"])
    assert result.exit_code == 0
    plain = _plain_output(result.output)
    assert "--repeats" in plain
    assert "--bootstrap-samples" in plain
    assert "--ci" in plain

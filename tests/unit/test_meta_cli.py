import re

from typer.testing import CliRunner

from cli.bootstrap import app


runner = CliRunner()
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_BOX_CHARS = str.maketrans({char: " " for char in "│╭╮╰╯─"})


def _plain_output(text: str) -> str:
    unstyled = _ANSI_ESCAPE.sub("", text).translate(_BOX_CHARS)
    return " ".join(unstyled.split())


def test_benchmark_help_registers_cross_repository_meta_commands() -> None:
    result = runner.invoke(app, ["benchmark", "--help"])
    assert result.exit_code == 0
    plain = _plain_output(result.output)
    assert "meta-preregister" in plain
    assert "meta" in plain


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
    assert "at least two repository study plans" in _plain_output(result.output)


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
    assert "at least two study directories" in _plain_output(result.output)

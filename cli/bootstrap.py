"""Installed ARC entrypoint with research subcommands registered."""

from cli.benchmark import benchmark_app
from cli.launcher import app
from cli.study_commands import register_study_commands

register_study_commands(benchmark_app)

# Keep research tooling isolated from the interactive/session modules while
# registering it on the same Typer application used by `cli.product`.
app.add_typer(benchmark_app, name="benchmark")

from cli.product import main as _product_main  # noqa: E402


def main() -> None:
    _product_main()


if __name__ == "__main__":  # pragma: no cover
    main()

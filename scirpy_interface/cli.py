from __future__ import annotations

import typer

try:
    from .source_transformer import DEFAULT_SOURCE, DEFAULT_TARGET, transform
except ImportError:  # Support running this file directly.
    from source_transformer import DEFAULT_SOURCE, DEFAULT_TARGET, transform


app = typer.Typer(help="Transform Python source code into scirpy AST JSON IR.")


@app.command()
def main(
    source: str = typer.Option(
        str(DEFAULT_SOURCE),
        "--source",
        help="Path to the Python source file.",
    ),
    target: str = typer.Option(
        str(DEFAULT_TARGET),
        "--target",
        help="Output file or directory for the generated IR.",
    ),
) -> None:
    """Transform SOURCE and write its IR to TARGET."""
    transform(source, target)
    typer.echo(f"Generated IR in {target}")


if __name__ == "__main__":
    app()

import typer
from pathlib import Path

app = typer.Typer(help="py-dbridge: Rewrite Python DB apps for set-oriented query execution.")

@app.command()
def transform(
    source: Path = typer.Argument(..., help="Path to the Python source file."),
    output: Path = typer.Option(None, "--output", "-o", help="Output file path."),
    db_type: str = typer.Option("postgres", "--db", help="Database type: postgres or sqlite"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show transformations without writing."),
) -> None:
    """Transform SOURCE for set-oriented query execution."""
    from src.pipeline import run_pipeline
    result = run_pipeline(source, output, db_type, dry_run)
    if result.analysis:
        typer.echo(result.analysis.format_summary(result.transformations))
    if dry_run or not output:
        typer.echo(result.transformed_code)
    elif result.transformations:
        typer.echo(f"Applied {len(result.transformations)} transformation(s) -> {output}")
    else:
        typer.echo("No transformation opportunities found.")

if __name__ == "__main__":
    app()

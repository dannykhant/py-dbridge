"""Tests for py-dbridge CLI and analysis output formatting."""
import os
from pathlib import Path
from typer.testing import CliRunner
from src.cli import app
from src.analyzer import run_analysis

runner = CliRunner()

def test_cli_dry_run_scirpy_summary(tmp_path: Path):
    source = tmp_path / "query_app.py"
    source.write_text('''
for pid in product_ids:
    cursor.execute("SELECT name, price FROM products WHERE id = %s", (pid,))
    row = cursor.fetchone()
    results.append(row)
''', encoding="utf-8")

    res = runner.invoke(app, [str(source), "--dry-run"])
    assert res.exit_code == 0
    assert "Analysis Result" in res.stdout
    assert "Analysis Engine" in res.stdout
    assert "Applied Rules" in res.stdout
    assert "loop_splitting" in res.stdout
    assert "_pyd_params" in res.stdout

def test_cli_output_file_mode(tmp_path: Path):
    source = tmp_path / "app.py"
    output = tmp_path / "app_opt.py"
    source.write_text('''
for pid in product_ids:
    cursor.execute("SELECT name, price FROM products WHERE id = %s", (pid,))
    row = cursor.fetchone()
    results.append(row)
''', encoding="utf-8")

    res = runner.invoke(app, [str(source), "-o", str(output)])
    assert res.exit_code == 0
    assert "Analysis Result" in res.stdout
    assert "Applied" in res.stdout and "transformation(s)" in res.stdout
    assert output.exists()

def test_analysis_result_properties(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text('x = 1\n', encoding="utf-8")
    analysis = run_analysis(source)
    assert hasattr(analysis, "engine")
    assert hasattr(analysis, "format_summary")
    summary = analysis.format_summary()
    assert "Analysis Result" in summary

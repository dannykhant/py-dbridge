"""End-to-end transformation pipeline."""

from dataclasses import dataclass, field
from pathlib import Path

from src.analyzer import AnalysisResult

@dataclass
class TransformResult:
    source_path: Path
    output_path: Path | None
    transformations: list[str] = field(default_factory=list)
    original_code: str = ""
    transformed_code: str = ""
    analysis: AnalysisResult | None = None

def run_pipeline(source: Path, output: Path | None = None,
                 db_type: str = "postgres", dry_run: bool = True) -> TransformResult:
    """Run the full py-dbridge transformation pipeline.

    Steps:
    1. Read source and parse to AST
    2. Convert AST to JSON for SCIRPy
    3. Run SCIRPy static analysis (via Java subprocess)
    4. Read analysis results
    5. Apply transformations (statement reordering, loop splitting, query rewrite)
    6. Generate output Python code
    """
    from src.source_reader import read_source
    from src.analyzer import run_analysis
    from src.transformer import apply_transformations
    from src.code_generator import generate_code

    result = TransformResult(source_path=source, output_path=output)
    result.original_code = read_source(source)
    
    current_code = result.original_code
    all_transformations = []
    
    analysis = run_analysis(source, source_code=current_code)
    result.analysis = analysis
    if analysis.transformable_queries:
        transformed_ir = apply_transformations(analysis, db_type)
        current_code = generate_code(transformed_ir)
        for r in transformed_ir.applied_rules:
            if r not in all_transformations:
                all_transformations.append(r)


    if "collections.defaultdict" in current_code and "import collections" not in current_code:
        # Must be inserted after any `from __future__` import, which is only
        # legal as the first statement in the module.
        lines = current_code.splitlines(keepends=True)
        insert_at = 0
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("from __future__"):
                insert_at = i + 1
            else:
                break
        lines.insert(insert_at, "import collections\n")
        current_code = "".join(lines)
        
    result.transformed_code = current_code
    result.transformations = all_transformations

    if not dry_run and output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.transformed_code, encoding="utf-8")

    return result

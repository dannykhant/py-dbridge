import ast
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "examples" / "retail_api" / "app.py"
DEFAULT_TARGET = PROJECT_ROOT / "sandbox" / "retail_api"

sys.path.insert(0, str(PROJECT_ROOT / "scirpy"))
from astexport.export import export_json

def transform(src=None, target=None):
    '''Transforms a Python program into ast and emits it json

      Parameters:
        src: Complete path to the source program. Defaults to the retail API example.
        target: Target file or directory. A directory receives ``<source>.json``.

     Returns:
        0 if the target is generated

     next line is temporary, delete it when stablized'''

    source_path = Path(src) if src is not None else DEFAULT_SOURCE
    target_path = Path(target) if target is not None else DEFAULT_TARGET

    if not source_path.is_file():
        raise FileNotFoundError(f"source program does not exist: {source_path}")

    # A directory target keeps each transformed source together in its sandbox.
    if (target_path.exists() and target_path.is_dir()) or target_path.suffix == "":
        target_path.mkdir(parents=True, exist_ok=True)
        target_path /= f"{source_path.stem}.json"
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)

    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    target_path.write_text(export_json(tree, True), encoding="utf-8")
    return 0

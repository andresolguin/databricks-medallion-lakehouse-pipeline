"""Check notebook syntax and ensure published notebooks contain no stale execution output."""

import ast
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = sorted([*root.glob("notebooks/**/*.ipynb"), *root.glob("sql/**/*.ipynb")])
for path in paths:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4, path
    for index, cell in enumerate(notebook["cells"], 1):
        if cell["cell_type"] == "code":
            assert not cell.get("outputs"), f"Stored execution output: {path}, cell {index}"
            ast.parse("".join(cell["source"]), filename=f"{path}:cell-{index}")
print(f"Validated {len(paths)} notebooks")

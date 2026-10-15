import ast
import json
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_databricks_job_uses_the_package_and_serializes_stages():
    job = yaml.safe_load((ROOT / "resources/pipeline.job.yml").read_text())["resources"]["jobs"][
        "iowa_pipeline"
    ]
    assert job["max_concurrent_runs"] == 1
    assert {p["name"]: p["default"] for p in job["parameters"]}["process_date"] == ""
    tasks = job["tasks"]
    assert [t["task_key"] for t in tasks] == ["bronze", "silver", "gold", "archive"]
    for index, task in enumerate(tasks):
        assert (ROOT / "resources" / task["spark_python_task"]["python_file"]).resolve().exists()
        assert task["spark_python_task"]["parameters"][:2] == ["--stage", task["task_key"]]
        if index:
            assert task["depends_on"] == [{"task_key": tasks[index - 1]["task_key"]}]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["iowa-lakehouse"] == "iowa_lakehouse.cli:main"


def test_notebooks_have_valid_syntax_ids_and_no_execution_output():
    paths = [*ROOT.glob("notebooks/**/*.ipynb"), *ROOT.glob("sql/**/*.ipynb")]
    assert len(paths) == 5
    for path in paths:
        notebook = json.loads(path.read_text())
        ids = [c["id"] for c in notebook["cells"]]
        assert len(ids) == len(set(ids))
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                assert cell["outputs"] == [] and cell["execution_count"] is None
                ast.parse("".join(cell["source"]))

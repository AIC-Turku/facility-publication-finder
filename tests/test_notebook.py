import ast
import json
import re
from pathlib import Path

NOTEBOOKS = [Path("notebooks/1_build_corpus.ipynb"), Path("notebooks/2_find_and_validate.ipynb")]


def _nb(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _source(path):
    return "\n".join("".join(c.get("source") or []) for c in _nb(path)["cells"])


def test_the_two_notebooks_run_the_canonical_steps():
    one, two = (_source(p) for p in NOTEBOOKS)
    assert "aic-pubs sweep --year {y}" in one and "aic-pubs embed --years {SWEPT_ARG}" in one
    assert "aic-pubs rescreen --year {YEAR}" in two and "workflow.prepare_sheet(gc, YEAR" in two
    assert "workflow.collect(gc, YEAR" in two and "workflow.learn(gc, YEAR" in two and "inbox.txt" in two


def test_notebooks_hold_no_algorithms():
    """Cells set parameters and call package functions or commands: no loops over data, no globbing."""
    for p in NOTEBOOKS:
        code = "\n".join("".join(c["source"]) for c in _nb(p)["cells"] if c["cell_type"] == "code")
        assert "glob" not in code and "embeddings.run" not in code and "gsheets." not in code


def test_data_lives_in_drive_and_code_on_the_temporary_disk():
    for p in NOTEBOOKS:
        src = _source(p)
        assert "os.environ['PUBS_DATA'] = DATA" in src and "/content/drive/MyDrive/" in src
        assert "CODE = '/content/code'" in src and "reset" not in src


def test_no_secrets_needed_for_the_public_repository():
    for p in NOTEBOOKS:
        src = _source(p)
        assert "GITHUB_TOKEN" not in src and "https://github.com/AIC-Turku/facility-publication-finder" in src


def test_slow_or_blocking_steps_are_opt_in_and_nothing_is_stored():
    for p in NOTEBOOKS:
        nb = _nb(p)
        assert "accelerator" not in nb["metadata"]
        assert all(not c.get("outputs") for c in nb["cells"] if c["cell_type"] == "code")
        for cell in nb["cells"]:
            body = "".join(cell.get("source") or [])
            if "files.upload()" in body:
                assert "if UPLOAD_PRIVATE:" in body


def test_code_cells_are_valid_python_once_magics_are_removed():
    for p in NOTEBOOKS:
        for cell in _nb(p)["cells"]:
            if cell["cell_type"] != "code":
                continue
            lines = []
            for line in "".join(cell["source"]).splitlines():
                stripped = line.lstrip()
                if stripped.startswith(("!", "%")):
                    line = line[: len(line) - len(stripped)] + "pass"
                lines.append(line)
            ast.parse("\n".join(lines))


def test_variables_are_defined_before_use():
    for p in NOTEBOOKS:
        code = ["".join(c["source"]) for c in _nb(p)["cells"] if c["cell_type"] == "code"]
        src = "\n".join(re.sub(r"#.*", "", line) for cell in code for line in cell.splitlines())
        for name in {NOTEBOOKS[0]: ("SWEPT_ARG",), NOTEBOOKS[1]: ("gc", "workflow")}[p]:
            uses = [m.start() for m in re.finditer(rf"\b{name}\b", src)]
            defs = [m.start() for m in re.finditer(rf"\b{name}\s*=|import [\w, ]*\b{name}\b", src)]
            if uses:
                assert defs and min(defs) <= min(uses), (p, name)

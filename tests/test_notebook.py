import ast
import json
import re
from pathlib import Path

NOTEBOOKS = [Path("notebooks/1_build_corpus/1_build_corpus.ipynb"), Path("notebooks/2_find_and_validate/2_find_and_validate.ipynb")]


def _nb(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _source(path):
    return "\n".join("".join(c.get("source") or []) for c in _nb(path)["cells"])


def test_the_two_notebooks_run_the_canonical_steps():
    one, two = (_source(p) for p in NOTEBOOKS)
    assert "cli.main(['sweep', '--year', str(y)])" in one and "cli.main(['embed', '--years'" in one
    assert "ui.Settings(FACILITIES, kind='build')" in one
    assert "ui.Settings(FACILITIES, kind='review')" in two
    assert "cli.main(['rescreen', '--year', str(cfg['year'])])" in two and "workflow.prepare(cfg['year']" in two
    assert "review.start(cfg['year'], at_once=cfg['at_once'], revisit=cfg['revisit'])" in two
    assert "workflow.collect(cfg['year']" in two and "workflow.learn(cfg['year']" in two
    assert "workflow.issue_link(REPO, cfg['facility']" in two and "workflow.feedback()" in two


def test_install_then_drive_then_settings():
    for p in NOTEBOOKS:
        titles = [("".join(c["source"]).splitlines() or [""])[0] for c in _nb(p)["cells"] if c["cell_type"] == "code"]
        assert titles[:3] == ["# @title 1. Install the code", "# @title 2. Connect your Google Drive (Colab)",
                              "# @title 3. Choose the settings"], p
        assert all(t.startswith("# @title ") for t in titles), p          # a header in Colab


def test_colab_only_code_is_guarded():
    """Mounting Drive, uploads and the Colab install run only in Colab, so the notebooks also run locally."""
    for p in NOTEBOOKS:
        for cell in _nb(p)["cells"]:
            body = "".join(cell["source"])
            if cell["cell_type"] == "code" and "google.colab" in body.replace("'google.colab' in sys.modules", ""):
                assert "ui.in_colab()" in body or "'google.colab' in sys.modules" in body, body[:60]


def test_notebooks_hold_no_algorithms():
    """Cells set parameters and call package functions or commands: no loops over data, no globbing."""
    for p in NOTEBOOKS:
        code = "\n".join("".join(c["source"]) for c in _nb(p)["cells"] if c["cell_type"] == "code")
        assert "glob" not in code and "embeddings.run" not in code and "set_verdict" not in code


def test_code_on_the_temporary_disk_and_settings_before_use():
    for p in NOTEBOOKS:
        src = _source(p)
        assert "CODE = Path('/content/code')" in src and "drive.mount('/content/drive')" in src
        assert "PUBS_DATA" not in src            # set by ui.Settings, the one place


def test_no_secrets_or_google_logins_needed():
    for p in NOTEBOOKS:
        src = _source(p)
        assert "authenticate_user" not in src and "gspread" not in src
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
        for name in {NOTEBOOKS[0]: ("settings", "cfg", "ui", "cli", "CODE", "FACILITIES"),
                     NOTEBOOKS[1]: ("settings", "cfg", "ui", "cli", "review", "workflow", "CODE", "REPO", "FACILITIES")}[p]:
            uses = [m.start() for m in re.finditer(rf"\b{name}\b", src)]
            defs = [m.start() for m in re.finditer(rf"\b{name}\s*=|import [\w, ]*\b{name}\b", src)]
            if uses:
                assert defs and min(defs) <= min(uses), (p, name)


def test_each_notebook_folder_has_its_labconstrictor_requirements():
    import yaml
    needed = {"pyyaml", "pymupdf", "fastembed", "scikit-learn", "numpy", "ipywidgets"}
    for p, extra in zip(NOTEBOOKS, ({"openpyxl"}, set())):
        req = yaml.safe_load((p.parent / "requirements.yaml").read_text())
        assert {"dependencies", "python_version", "description"} <= set(req) and req["description"].strip()
        names = {d.split("==")[0].lower() for d in req["dependencies"]}
        assert names == needed | extra, p
        assert all("==" in d for d in req["dependencies"]), "pinned versions only"
        assert p.parent.name == p.stem                       # LabConstrictor: notebooks/<name>/<name>.ipynb


def test_each_notebook_folder_has_a_labconstrictor_changelog():
    for p in NOTEBOOKS:
        text = (p.parent / "CHANGELOG.md").read_text()
        assert text.startswith(f"# Changelog - {p.stem}\n") and re.search(r"^## \[\d+\.\d+\.\d+\] - \d{4}-\d\d-\d\d$", text, re.M)


def _current_version(path):
    """As LabConstrictor reads it: a top-level `current_version = "..."` in a code cell."""
    for cell in _nb(path)["cells"]:
        if cell["cell_type"] != "code":
            continue
        lines = [line[: len(line) - len(line.lstrip())] + "pass" if line.lstrip().startswith(("!", "%")) else line
                 for line in "".join(cell["source"]).splitlines()]
        for node in ast.parse("\n".join(lines)).body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "current_version" for t in node.targets):
                return node.value.value


def test_versions_agree_in_the_notebook_its_changelog_and_the_version_file():
    import yaml
    latest = yaml.safe_load(Path("notebooks/notebook_latest_versions.yaml").read_text())
    for p in NOTEBOOKS:
        version = _current_version(p)
        top = re.search(r"^## \[(\d+\.\d+\.\d+)\]", (p.parent / "CHANGELOG.md").read_text(), re.M).group(1)
        assert version == top == latest[p.parent.name][p.stem], p
        assert f"notebook_name = '{p.stem}'" in _source(p)

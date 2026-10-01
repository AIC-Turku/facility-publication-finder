import datetime
import os

import pytest

pytest.importorskip("ipywidgets")
from facility_pubs import ui  # noqa: E402

TODAY = datetime.date(2026, 10, 1)


@pytest.fixture(autouse=True)
def _restore_facility(monkeypatch):
    """Settings.confirm sets the environment; monkeypatch restores it after each test."""
    for name in ("PUBS_FACILITY", "PUBS_DATA", "PUBS_PRIVATE"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
        if not os.environ[name]:
            monkeypatch.delenv(name)


def _facilities(tmp_path):
    root = tmp_path / "facilities"
    for name in ("my-core", "template"):
        (root / name).mkdir(parents=True)
        (root / name / "facility.yaml").write_text("x: 1\n")
    (root / "no-yaml").mkdir()
    return root


def test_folder_picker_opens_goes_up_and_creates_folders(tmp_path):
    (tmp_path / "B").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / ".hidden").mkdir()
    seen = []
    picker = ui.FolderPicker(tmp_path, on_change=seen.append)
    assert picker.list.options == (ui.FolderPicker.UP, "a", "B")
    picker.list.value = "B"                                     # click: open it
    assert picker.value == tmp_path.resolve() / "B" and picker.list.options == (ui.FolderPicker.UP,)
    picker.list.value = ui.FolderPicker.UP                      # click: up
    assert picker.value == tmp_path.resolve()
    picker.new_name.value = "AIC-publications"
    picker.create()
    assert (tmp_path / "AIC-publications").is_dir() and picker.value.name == "AIC-publications"
    picker.new_name.value = "../escape"
    picker.create()
    assert "no slashes" in picker.message.value
    picker.path.value = str(tmp_path / "missing")               # typed path that does not exist
    assert "is not a folder" in picker.message.value
    assert seen[0] == tmp_path.resolve()


def test_build_settings_choose_years_and_set_the_environment(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    s = ui.Settings(_facilities(tmp_path), kind="build", colab=False, start=data, today=TODAY)
    assert s.facility.options == ("my-core",)                   # no template, no folder without facility.yaml
    assert s.years.value == (2025, 2024, 2023, 2022)
    with pytest.raises(SystemExit, match="Use these settings"):
        s.require()
    monkeypatch.setattr("facility_pubs.cli.main", lambda argv: None)
    values = s.confirm()
    assert values["years"] == [2025, 2024, 2023, 2022] and s.require() is values
    assert os.environ["PUBS_DATA"] == str(data.resolve())
    assert os.environ["PUBS_FACILITY"] == str(tmp_path / "facilities" / "my-core")
    assert os.environ["PUBS_PRIVATE"] == str(tmp_path / "private") and values["private"].is_dir()
    s.picker.go(tmp_path)                                       # another folder: confirm again
    with pytest.raises(SystemExit):
        s.require()


def test_review_settings_list_the_years_built_in_the_chosen_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("facility_pubs.cli.main", lambda argv: None)
    data = tmp_path / "data"
    for y in ("2023", "2025"):
        (data / y).mkdir(parents=True)
        (data / y / "screened.jsonl").write_text("")
    empty = tmp_path / "empty"
    empty.mkdir()
    s = ui.Settings(_facilities(tmp_path), kind="review", colab=False, start=empty, today=TODAY)
    assert s.confirm() is None and "run notebook 1 first" in s.message.value
    s.picker.go(data)
    assert s.year.options == (2023, 2025) and s.year.value == 2025
    s.revisit.value = ("likely",)
    v = s.confirm()
    assert (v["year"], v["top_n"], v["at_once"], v["revisit"]) == (2025, 200, 1, ["likely"])


def test_a_colab_folder_outside_drive_is_allowed_with_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr("facility_pubs.cli.main", lambda argv: None)
    s = ui.Settings(_facilities(tmp_path), kind="build", colab=True, start=tmp_path, today=TODAY)
    assert s.confirm() is not None and "lost when the" in s.message.value


def test_check_data_folder_refuses_missing_folders(tmp_path):
    errors, _ = ui.check_data_folder(tmp_path / "nope", colab=False)
    assert errors and "not an existing folder" in errors[0]


def _zip(files):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_facilities_come_from_the_clone_when_there_is_one(tmp_path):
    (tmp_path / "facilities").mkdir()
    assert ui.facilities_folder(tmp_path, "https://x", fetch=lambda u: 1 / 0) == tmp_path / "facilities"


def test_an_installed_app_downloads_the_facilities_and_keeps_them_fresh(tmp_path):
    asked = []
    files = {"repo-main/facilities/my-core/facility.yaml": "v: 1\n", "repo-main/src/x.py": "",
             "repo-main/facilities/my-core/papers/2025.yaml": "[]\n"}
    got = ui.facilities_folder(tmp_path / "site", "https://github.com/o/repo.git", cache=tmp_path / "c",
                               fetch=lambda u: asked.append(u) or _zip(files))
    assert asked == ["https://github.com/o/repo/archive/refs/heads/main.zip"]
    assert (got / "my-core" / "facility.yaml").read_text() == "v: 1\n" and not (got.parent / "src").exists()
    files["repo-main/facilities/my-core/facility.yaml"] = "v: 2\n"           # next run: the new version
    ui.facilities_folder(tmp_path / "site", "https://github.com/o/repo", cache=tmp_path / "c", fetch=lambda u: _zip(files))
    assert (got / "my-core" / "facility.yaml").read_text() == "v: 2\n"


def test_offline_uses_the_last_download_or_explains(tmp_path, capsys):
    def offline(u):
        raise OSError("no network")
    with pytest.raises(SystemExit, match="cannot download the facilities"):
        ui.facilities_folder(tmp_path / "site", "https://github.com/o/repo", cache=tmp_path / "c", fetch=offline)
    (tmp_path / "c" / "facilities" / "my-core").mkdir(parents=True)
    got = ui.facilities_folder(tmp_path / "site", "https://github.com/o/repo", cache=tmp_path / "c", fetch=offline)
    assert got == tmp_path / "c" / "facilities" and "using" in capsys.readouterr().out

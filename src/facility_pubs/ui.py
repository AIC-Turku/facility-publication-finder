"""Notebook widgets that work in Google Colab and in local Jupyter (ipywidgets only: no Colab
forms, no native dialogs). The notebooks call these; no logic lives in notebooks.

    from facility_pubs import ui
    settings = ui.Settings(facilities_folder, kind="build")   # or kind="review"
    settings.widget                                            # shown by the cell
    cfg = settings.require()                                   # in later cells

`Settings` lets the user pick the facility, browse to the working-data folder (their Google
Drive in Colab) and choose the years; "Use these settings" checks them and sets PUBS_DATA and
PUBS_FACILITY / PUBS_PRIVATE for the rest of the session (the one place the notebooks set the environment).
"""
from collections.abc import Callable
from pathlib import Path
import datetime
import html
import io
import os
import shutil
import sys
import zipfile

DRIVE = Path("/content/drive/MyDrive")


def in_colab() -> bool:
    return "google.colab" in sys.modules


def facilities_folder(code: Path, repo: str, cache: Path | None = None, branch: str = "main",
                      fetch: Callable[[str], bytes] | None = None) -> Path:
    """The folder with the facilities (rules and confirmed papers).

    `code`: the repository the package runs from (a clone, Colab's /content/code). An installed
    app (e.g. built with LabConstrictor) has the package but not the facilities: they are then
    downloaded from `repo` (a zip of `branch`, no git needed) into `cache` (default
    ~/.facility_pubs), fresh on every call so rules and confirmed papers stay current. Without a
    connection the last download is used, with a warning; with none at all it is an error."""
    if (code / "facilities").is_dir():
        return code / "facilities"
    cache = cache or Path.home() / ".facility_pubs"
    target = cache / "facilities"
    url = f"{repo.removesuffix('.git').rstrip('/')}/archive/refs/heads/{branch}.zip"
    if fetch is None:
        import urllib.request

        def fetch(u):
            with urllib.request.urlopen(u, timeout=60) as r:
                return r.read()
    try:
        archive = zipfile.ZipFile(io.BytesIO(fetch(url)))
    except Exception as exc:  # noqa: BLE001 - offline, proxy, GitHub down: fall back or explain
        if target.is_dir():
            print(f"⚠️ could not download the latest facilities ({exc.__class__.__name__}): using {target}")
            return target
        raise SystemExit(f"cannot download the facilities from {url} ({exc}); check the internet "
                         f"connection, or install from a clone of the repository") from None
    members = [m for m in archive.namelist() if m.split("/")[1:2] == ["facilities"] and not m.endswith("/")]
    if not members:
        raise SystemExit(f"{url} has no facilities/ folder")
    fresh = cache / "facilities.new"
    shutil.rmtree(fresh, ignore_errors=True)
    for m in members:
        out = fresh.joinpath(*m.split("/")[2:])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(archive.read(m))
    shutil.rmtree(target, ignore_errors=True)
    fresh.rename(target)
    return target


def version_status(name: str, current: str, latest_versions: dict | None) -> str:
    """One line comparing the notebook's version with notebooks/notebook_latest_versions.yaml
    (LabConstrictor's format: {folder: {notebook: version}}); latest_versions None: not fetched."""
    if latest_versions is None:
        return f"Notebook version {current} (the latest version could not be checked)."
    latest = (latest_versions.get(name) or {}).get(name)
    if not latest:
        return f"Notebook version {current} (⚠️ this notebook is not listed in the version file)."
    if latest == current:
        return f"Notebook version {current}: ✅ up to date."
    return (f"Notebook version {current}: ⚠️ version {latest} is available (Colab: reopen the notebook from "
            f"the repository; app: update it).")


def check_version(repo: str, name: str, current: str, branch: str = "main",
                  fetch: Callable[[str], bytes] | None = None) -> str:
    """version_status() with the version file read from GitHub; never fails (offline: says so)."""
    import yaml
    path = repo.removesuffix(".git").rstrip("/").replace("https://github.com/", "https://raw.githubusercontent.com/")
    url = f"{path}/{branch}/notebooks/notebook_latest_versions.yaml"
    if fetch is None:
        import urllib.request

        def fetch(u):
            with urllib.request.urlopen(u, timeout=20) as r:
                return r.read()
    try:
        latest = yaml.safe_load(fetch(url)) or {}
    except Exception:  # noqa: BLE001 - offline or GitHub unreachable: only the check is skipped
        latest = None
    return version_status(name, current, latest)


def _widgets():
    try:
        import ipywidgets
    except ImportError:
        raise SystemExit("the notebooks need ipywidgets (preinstalled in Colab; locally: "
                         "pip install -e \".[embed,openiris,notebook]\")") from None
    return ipywidgets


def subfolders(folder: Path) -> list[str]:
    """Visible subfolder names of `folder`, sorted case-insensitively ([] if unreadable)."""
    try:
        return sorted((p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")),
                      key=str.lower)
    except OSError:
        return []


def check_data_folder(folder: Path, colab: bool) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a working-data folder."""
    errors, warnings = [], []
    if not folder.is_dir():
        return [f"{folder} is not an existing folder"], []
    probe = folder / ".facility_pubs_write_test"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        errors.append(f"cannot write in {folder} ({exc.__class__.__name__})")
    if colab and not str(folder).startswith("/content/drive/"):
        warnings.append("this folder is not in your Google Drive: everything in it is lost when the "
                        "Colab session ends")
    return errors, warnings


class FolderPicker:
    """Browse folders: click a folder to open it, ".." to go up; type a path; create a folder."""

    UP = ".. (up one level)"

    def __init__(self, start: Path, on_change: Callable[[Path], None] | None = None):
        w = _widgets()
        self._on_change = on_change
        self.path = w.Text(description="Folder", continuous_update=False,
                           layout=w.Layout(width="95%"), style={"description_width": "70px"})
        self.list = w.Select(options=[], rows=9, layout=w.Layout(width="95%"))
        self.new_name = w.Text(placeholder="new folder name", layout=w.Layout(width="260px"))
        create = w.Button(description="Create folder here", icon="plus", layout=w.Layout(width="170px"))
        self.message = w.HTML()
        self.path.observe(lambda ch: self.go(Path(ch["new"]).expanduser()), names="value")
        self.list.observe(self._clicked, names="value")
        create.on_click(lambda _: self.create())
        self.widget = w.VBox([self.path, self.list, w.HBox([self.new_name, create]), self.message])
        self.go(start)

    @property
    def value(self) -> Path:
        return Path(self.path.value)

    def go(self, folder: Path) -> None:
        if not folder.is_dir():
            self.message.value = f"<span style='color:#b00020'>{html.escape(str(folder))} is not a folder</span>"
            return
        self.message.value = ""
        folder = folder.resolve() if not str(folder).startswith("/content/drive") else folder
        if self.path.value != str(folder):
            self.path.value = str(folder)            # observed: comes back here once, unchanged
            return
        names = ([self.UP] if folder.parent != folder else []) + subfolders(folder)
        self.list.unobserve(self._clicked, names="value")
        self.list.options, self.list.value = names, None
        self.list.observe(self._clicked, names="value")
        if self._on_change:
            self._on_change(folder)

    def _clicked(self, change) -> None:
        name = change["new"]
        if name:
            self.go(self.value.parent if name == self.UP else self.value / name)

    def create(self) -> None:
        name = self.new_name.value.strip()
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            self.message.value = "<span style='color:#b00020'>type a folder name (no slashes)</span>"
            return
        (self.value / name).mkdir(exist_ok=True)
        self.new_name.value = ""
        self.go(self.value / name)


class Settings:
    """The settings form of a notebook. kind="build" (notebook 1: years to build) or
    kind="review" (notebook 2: the year to review, list size, papers per page, revisit)."""

    def __init__(self, facilities: Path, kind: str, default_facility: str = "aic-turku",
                 colab: bool | None = None, start: Path | None = None, today: datetime.date | None = None):
        if kind not in ("build", "review"):
            raise ValueError("kind must be 'build' or 'review'")
        w = _widgets()
        self.kind, self.facilities = kind, Path(facilities)
        self.colab = in_colab() if colab is None else colab
        self._values: dict | None = None
        names = [n for n in subfolders(self.facilities) if (self.facilities / n / "facility.yaml").exists()
                 and n != "template"]
        if not names:
            raise SystemExit(f"no facility folder with a facility.yaml in {self.facilities}")
        style = {"description_width": "150px"}
        self.facility = w.Dropdown(options=names, value=default_facility if default_facility in names else names[0],
                                   description="Facility", style=style)
        this_year = (today or datetime.date.today()).year
        if kind == "build":
            options = list(range(this_year, this_year - 16, -1))
            self.years = w.SelectMultiple(options=options, value=tuple(options[1:5]), rows=6,
                                          description="Years to build", style=style)
            extra = [self.years, w.HTML("<small>Ctrl/Cmd-click to choose several years.</small>")]
        else:
            self.year = w.Dropdown(options=[], description="Year to review", style=style)
            self.top_n = w.BoundedIntText(value=200, min=0, max=5000, step=50,
                                          description="Check-list papers", style=style)
            self.at_once = w.BoundedIntText(value=1, min=1, max=10, description="Papers per page", style=style)
            self.revisit = w.SelectMultiple(options=["likely", "no", "yes"], value=(), rows=3,
                                            description="Show again", style=style)
            extra = [self.year, self.top_n, self.at_once, self.revisit,
                     w.HTML("<small><i>Show again</i>: papers already decided that come back in the review "
                            "(e.g. <i>likely</i>, once the authors answered). Usually none.</small>")]
        start = start or (DRIVE if self.colab and DRIVE.exists() else Path.home())
        self.picker = FolderPicker(start, on_change=self._folder_changed)
        confirm = w.Button(description="Use these settings", button_style="success", icon="check",
                           layout=w.Layout(width="200px"))
        self.message = w.HTML()
        self.report = w.Output()
        confirm.on_click(lambda _: self.confirm())
        where = ("Your Google Drive is under <code>/content/drive/MyDrive</code>." if self.colab
                 else "Choose a folder on this computer.")
        self.widget = w.VBox([
            self.facility,
            w.HTML(f"<b>Working-data folder</b> (the same in both notebooks; it holds the full texts and "
                   f"e-mail addresses, so keep it private). {where}"),
            self.picker.widget, *extra, confirm, self.message, self.report])
        self._folder_changed(self.picker.value)

    def _folder_changed(self, folder: Path) -> None:
        self._values = None
        if self.kind == "review":
            from .workflow import swept_years
            years = swept_years(folder)
            self.year.options = years
            self.year.value = years[-1] if years else None

    def confirm(self) -> dict | None:
        """Check the choices; on success set PUBS_DATA / PUBS_FACILITY and return the values."""
        folder = self.picker.value
        errors, warnings = check_data_folder(folder, self.colab)
        values = {"facility": self.facility.value, "facility_dir": self.facilities / self.facility.value,
                  "data": folder}
        if self.kind == "build":
            values["years"] = sorted(self.years.value, reverse=True)
            if not values["years"]:
                errors.append("choose at least one year")
        else:
            if self.year.value is None:
                errors.append("no year is built in this folder yet: run notebook 1 first, or choose the "
                              "folder notebook 1 used")
            values.update(year=self.year.value, top_n=self.top_n.value, at_once=self.at_once.value,
                          revisit=list(self.revisit.value))
        if errors:
            self._values = None
            self.message.value = "<span style='color:#b00020'>" + "<br>".join(map(html.escape, errors)) + "</span>"
            return None
        os.environ["PUBS_DATA"] = str(folder)
        os.environ["PUBS_FACILITY"] = str(values["facility_dir"])
        values["private"] = self.private_folder()
        os.environ["PUBS_PRIVATE"] = str(values["private"])
        self._values = values
        lines = ["✅ Settings saved: run the next cells."] + [f"⚠️ {html.escape(x)}" for x in warnings]
        self.message.value = "<br>".join(lines)
        self.report.clear_output()
        with self.report:
            from .cli import main
            main(["check-facility"])
        return values

    def private_folder(self) -> Path:
        """Private inputs and what is derived from them: Colab's temporary disk, else next to the
        facilities (a clone's git-ignored private/, or ~/.facility_pubs/private); never in DATA."""
        folder = Path("/content/private") if self.colab else self.facilities.parent / "private"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def require(self) -> dict:
        """The confirmed values, or a clear error if "Use these settings" was not clicked."""
        if self._values is None:
            raise SystemExit("Choose the settings and click 'Use these settings' (step 3) first.")
        return self._values


def link(url: str, text: str):
    """A clickable link (opens in a new tab) for a cell's output."""
    from IPython.display import HTML
    return HTML(f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(text)}</a>')

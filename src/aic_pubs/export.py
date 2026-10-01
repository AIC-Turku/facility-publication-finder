"""Copy the shareable part of this repository into a folder for the public repository.

Public: the code, tests, notebooks, documentation, the facility folders (rules, confirmed
papers, inbox) and the workflows that run tests and file pasted papers. Never: working data
(data/), private inputs, private notes (notes/), experiment outputs, the live-probe workflow.

Files come from the last commit (HEAD), never from the working tree, and the export refuses
to run with uncommitted changes. Afterwards every exported file is scanned: an e-mail address
that is not a known placeholder stops the export.
"""
import re
import subprocess
from pathlib import Path

from .config import ROOT

ALLOW = ("src/", "tests/", "notebooks/", "docs/", "config/plans/", "config/examples/",
         ".github/workflows/tests.yml", ".github/workflows/add-papers.yml",
         "README.md", "AGENTS.md", "CLAUDE.md", "LICENSE", "pyproject.toml", ".gitignore")
# in a facility folder only these: rules, inbox, confirmed papers
FACILITY_FILE = re.compile(r"^facilities/[^/]+/(facility\.yaml|inbox\.txt|papers/(\d{4}\.yaml|README\.md))$")
DENY = ("data/", "notes/", "private/", ".github/workflows/live-probe.yml")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PLACEHOLDER_EMAIL = re.compile(
    r"@([\w-]+\.)*example\.(org|com|edu|net)$|@users\.noreply\.github\.com$|^noreply@anthropic\.com$|"
    r"^jane\.doe@|^permissions@elsevier\.com$|^t@t$|\.(png|jpe?g|gif|svg)$", re.I)
PUBLIC_GITIGNORE = "\n# public repository: working data never belongs here\ndata/\nnotes/\n"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def public_files(root=ROOT):
    """[(path, mode)] of HEAD that are public."""
    out = []
    for line in _git(root, "ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        mode = meta.split()[0]
        if path.startswith(DENY) or "__pycache__" in path:
            continue
        if path.startswith(ALLOW) or FACILITY_FILE.match(path):
            out.append((path, mode))
    return sorted(out)


def scan(folder):
    """E-mail addresses in exported files that are not placeholders: [(file, address)]."""
    found = []
    for path in Path(folder).rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            found += [(str(path.relative_to(folder)), e) for e in EMAIL.findall(text)
                      if not PLACEHOLDER_EMAIL.search(e)]
    return found


def export(dest, root=ROOT):
    """Write the public files of HEAD into dest (new or empty folder). Returns the paths."""
    import shutil
    dest = Path(dest)
    created = not dest.exists()
    if dest.exists() and any(p.name != ".git" for p in dest.iterdir()):
        raise SystemExit(f"{dest} is not empty: export into a new folder (or a clean clone)")
    dirty = [l for l in _git(root, "status", "--porcelain").splitlines() if l[3:].startswith(ALLOW + ("facilities/",))]
    if dirty:
        raise SystemExit("uncommitted changes in public files: commit them first\n  " + "\n  ".join(dirty[:10]))
    files = public_files(root)
    links = [p for p, mode in files if mode == "120000"]
    if links:
        raise SystemExit(f"symlinks are not exported: {', '.join(links)}")
    for path, _ in files:
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{path}"], capture_output=True, check=True).stdout
        target.write_bytes(blob)
    with (dest / ".gitignore").open("a", encoding="utf-8") as f:
        f.write(PUBLIC_GITIGNORE)
    leaks = scan(dest)
    if leaks:
        if created:
            shutil.rmtree(dest)           # never leave a failed export lying around to be pushed
        raise SystemExit("e-mail addresses in the export (remove them, or add a placeholder pattern):\n  "
                         + "\n  ".join(f"{f}: {e}" for f, e in leaks[:20]))
    return [p for p, _ in files]

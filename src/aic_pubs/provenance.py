"""Small shared helpers: which rules produced a sheet, and honest intervals for small counts."""
import hashlib
import subprocess

from .config import config_path


def rules_version(path=None):
    """'config <sha256[:12]> / code <git short hash>' - stamped on every sheet for review,
    so staff verdicts can be tied to the rules that produced the sheet."""
    path = path or config_path()
    cfg = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    try:
        code = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        code = ""
    return f"config {cfg} / code {code or 'unknown'}"


def wilson(k, n, z=1.96):
    """Wilson score 95% interval for k successes out of n (0, 0 when n == 0)."""
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - h), min(1.0, c + h)


def ci(k, n):
    """'0.90 (0.77-0.96)' for k/n, or 'n/a' when n == 0."""
    if not n:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"{k / n:.2f} ({lo:.2f}-{hi:.2f})"


def previous_verdicts(path):
    """{doi: (your_verdict, your_note)} already filled in a sheet that is about to be rewritten,
    so re-running `validate` or `embed` never wipes staff verdicts.

    Reads sheets re-saved by Excel too (UTF-8 with BOM or Windows-1252; comma or semicolon).
    Refuses to continue rather than overwrite a sheet whose verdicts it cannot read."""
    import csv
    from pathlib import Path
    path = Path(path)
    if not path.exists():
        return {}
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    if not text.strip():
        return {}
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    if rows and "doi" not in rows[0]:
        raise SystemExit(f"cannot read the verdicts in {path} (no 'doi' column): save it as CSV, "
                         f"or move it away, before re-running")
    return {r["doi"]: (r.get("your_verdict") or "", r.get("your_note") or "")
            for r in rows if r.get("doi") and (r.get("your_verdict") or r.get("your_note"))}

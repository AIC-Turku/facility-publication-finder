"""Small shared helpers: which rules produced a list, and honest intervals for small counts."""
from pathlib import Path
import hashlib
import subprocess

from .config import config_path


def rules_version(path: Path | None = None) -> str:
    """'config <sha256[:12]> / code <git short hash>' - stamped on every check list,
    so staff verdicts can be tied to the rules that produced the list."""
    path = path or config_path()
    cfg = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    try:
        code = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        code = ""
    return f"config {cfg} / code {code or 'unknown'}"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% interval for k successes out of n (0, 0 when n == 0)."""
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - h), min(1.0, c + h)

"""Private user identities used to prioritize publication recovery.

Identity data belong under private/ and are never written to committed outputs.
Stable identifiers (ORCID/CRIS ids) are preferred; conservative name matching is
used only to annotate an already harvested institutional publication universe.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


LOCAL_MARKERS = (
    "university of turku",
    "turun yliopisto",
    "utu",
    "abo akademi",
    "åbo akademi",
    "aau",
)


@dataclass(frozen=True)
class UserIdentity:
    name: str
    institution: str = ""
    orcid: str = ""
    cris_id: str = ""

    @property
    def is_local(self):
        value = _ascii(self.institution)
        return any(marker in value for marker in LOCAL_MARKERS)


def _ascii(value):
    return unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()


def _name_parts(name):
    value = _ascii(name).strip()
    if "," in value:
        last, _, first = value.partition(",")
    else:
        parts = value.split()
        first, last = (" ".join(parts[:-1]), parts[-1]) if parts else ("", "")
    clean = lambda s: re.sub(r"[^a-z]", "", s)
    return clean(last), clean(first)


def name_match_strength(left, right):
    """Return "exact", "initial", or None for a local-author name comparison."""
    ll, lf = _name_parts(left)
    rl, rf = _name_parts(right)
    if not (ll and rl and ll == rl and lf and rf):
        return None
    if len(lf) > 1 and len(rf) > 1:
        return "exact" if lf == rf else None
    return "initial" if lf[:1] == rf[:1] else None


def same_person(left, right):
    """Compatibility boolean for local metadata matching."""
    return name_match_strength(left, right) is not None


def normalise_orcid(value):
    """Return canonical ORCID or raise on a malformed non-empty identifier."""
    value = (value or "").strip()
    if not value:
        return ""
    value = re.sub(r"^https?://orcid\.org/", "", value, flags=re.I)
    compact = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"\d{15}[\dX]", compact):
        raise ValueError(f"invalid ORCID format: {value!r}")

    total = 0
    for digit in compact[:15]:
        total = (total + int(digit)) * 2
    check = (12 - (total % 11)) % 11
    expected = "X" if check == 10 else str(check)
    if compact[-1] != expected:
        raise ValueError(f"invalid ORCID checksum: {value!r}")

    return "-".join((
        compact[0:4],
        compact[4:8],
        compact[8:12],
        compact[12:16],
    ))


def load_users(path):
    """Load the private identity table.

    Required column: name.
    Optional columns: institution, orcid, cris_id.
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if rows and "name" not in rows[0]:
        raise ValueError("private user CSV must contain a 'name' column")

    users = []
    seen = set()
    for row_number, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        try:
            orcid = normalise_orcid(row.get("orcid"))
        except ValueError as exc:
            raise ValueError(f"{path}:{row_number}: {exc}") from exc

        user = UserIdentity(
            name=name,
            institution=(row.get("institution") or "").strip(),
            orcid=orcid,
            cris_id=(row.get("cris_id") or "").strip(),
        )
        key = (
            ("orcid", user.orcid)
            if user.orcid
            else ("name", _ascii(user.name), _ascii(user.institution))
        )
        if key in seen:
            continue
        seen.add(key)
        users.append(user)
    return users


def paper_user_match_strength(paper, user):
    """Strongest local-author match for a private user identity."""
    authors = list(paper.get("local_authors") or []) + list(paper.get("authors") or [])
    strengths = {
        name_match_strength(user.name, author)
        for author in authors
    }
    if "exact" in strengths:
        return "exact"
    if "initial" in strengths:
        return "initial"
    return None


def paper_has_user(paper, user):
    return paper_user_match_strength(paper, user) is not None


def audit_users(path):
    """Validate a private user CSV without echoing names or identifiers.

    Returns aggregate counts and row-numbered issues suitable for logs.
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    issues = []
    if "name" not in fieldnames:
        return {
            "rows": len(rows),
            "valid_named_rows": 0,
            "with_orcid": 0,
            "without_orcid": 0,
            "local_without_orcid": 0,
            "duplicate_orcid_rows": 0,
            "duplicate_identity_rows": 0,
            "issues": [{"row": 1, "kind": "missing_name_column"}],
            "ok": False,
        }

    seen_orcids = {}
    seen_identity = {}
    valid_named = with_orcid = local_without_orcid = 0
    duplicate_orcid = duplicate_identity = 0

    for row_number, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        institution = (row.get("institution") or "").strip()
        if not name:
            issues.append({"row": row_number, "kind": "missing_name"})
            continue
        valid_named += 1

        try:
            orcid = normalise_orcid(row.get("orcid"))
        except ValueError:
            issues.append({"row": row_number, "kind": "invalid_orcid"})
            orcid = ""

        if orcid:
            with_orcid += 1
            if orcid in seen_orcids:
                duplicate_orcid += 1
                issues.append({
                    "row": row_number,
                    "kind": "duplicate_orcid",
                    "first_row": seen_orcids[orcid],
                })
            else:
                seen_orcids[orcid] = row_number
        elif UserIdentity(name=name, institution=institution).is_local:
            local_without_orcid += 1

        identity_key = (_ascii(name), _ascii(institution))
        if identity_key in seen_identity:
            duplicate_identity += 1
            issues.append({
                "row": row_number,
                "kind": "duplicate_name_institution",
                "first_row": seen_identity[identity_key],
            })
        else:
            seen_identity[identity_key] = row_number

    return {
        "rows": len(rows),
        "valid_named_rows": valid_named,
        "with_orcid": with_orcid,
        "without_orcid": valid_named - with_orcid,
        "local_without_orcid": local_without_orcid,
        "duplicate_orcid_rows": duplicate_orcid,
        "duplicate_identity_rows": duplicate_identity,
        "issues": issues,
        "ok": not any(
            issue["kind"] in {"missing_name_column", "invalid_orcid"}
            for issue in issues
        ),
    }

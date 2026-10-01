"""Corresponding authors and their e-mail addresses, for the facility's validation Sheet.

Used only to contact the authors of validated papers (thanks, acknowledgement reminders).
The result goes into the Google Sheet in the facility's Drive, never into the repository.
Heuristic: e-mail addresses printed in the paper, ranked by closeness to a correspondence
marker, matched to the author list for the name. Staff can correct the Sheet.
"""
import re
import unicodedata

EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_MARKER = re.compile(r"(?i:correspond|to whom|e-?mail|contact)|✉|\*\s*(?=[A-Z])")
# addresses of publishers, journals and services, not of authors
_NOT_PERSONAL = re.compile(
    r"^(permissions?|info|editor|editorial|office|support|help|noreply|no-reply|reprints?|journals?|"
    r"admin|contact|enquiries|service|submissions?|press|orders|subscriptions?|datasharing|data)@|"
    r"@(\w+\.)*(elsevier|wiley|springer(nature)?|nature|plos|cell|frontiersin|mdpi|biorxiv|medrxiv|"
    r"acs|rsc|tandf|sagepub|oup|bmj|biomedcentral|cshl|embo|aaas|iop|pnas|thieme|karger)\.(com|org|net)$",
    re.I)
# marker case-insensitive, the name itself must be capitalised words (re.I would let it match anything)
_NAME_AFTER_MARKER = re.compile(
    r"(?i:correspond\w*(?:\s+authors?)?(?:\s+to)?|to whom correspondence[^:]{0,40}|contact)\s*[:：]?\s*"
    r"((?:[A-ZÅÄÖÉÜØ][\w'’-]*\.?\s+){1,3}[A-ZÅÄÖÉÜØ][\w'’-]+)")
_NOT_A_NAME = re.compile(r"\b(author|authors|e-?mail|address|department|university|institute|faculty|"
                         r"school|hospital|centre|center|laboratory|lab|division|unit|tel|phone|fax)\b", re.I)
_FILE_TLD = re.compile(r"\.(png|jpe?g|gif|svg|tiff?|webp|pdf|docx?|xlsx?|zip)$", re.I)


def _fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _name_for(email, authors):
    """(score, name) of the author whose name is in the address: family name plus given name
    or initial = 3, family name alone = 2 (only if no other author has that family name)."""
    local = re.sub(r"[^a-z]", "", _fold(email.split("@")[0]))
    found = []
    for name in authors or []:
        if "," in name:                       # "Lastname, Firstname"
            family, _, given = name.partition(",")
        else:                                 # "Firstname Lastname"
            parts = name.split()
            family, given = (parts[-1], " ".join(parts[:-1])) if parts else ("", "")
        fam = re.sub(r"[^a-z]", "", _fold(family))
        giv = re.sub(r"[^a-z]", "", _fold(given))
        if len(fam) >= 3 and fam in local:
            rest = local.replace(fam, " ", 1)
            strong = bool(giv) and (giv in local or rest.strip().startswith(giv[:1]) or local.startswith(giv[:1]))
            found.append((3 if strong else 2, fam, f"{given.strip()} {family.strip()}".strip()))
    if not found:
        return 0, ""
    best = max(found)
    if best[0] == 2 and sum(f[1] == best[1] for f in found) > 1:
        return 0, ""                          # several authors share the family name
    return best[0], best[2]


def corresponding_contacts(text, authors=(), limit=3):
    """[{"name", "email"}] for the likely corresponding author(s), best first.

    authors: author names ("Firstname Lastname" or "Lastname, Firstname") to name the
    addresses. Addresses close after a correspondence marker rank first; publisher and
    service addresses are dropped."""
    text = " ".join((text or "").split())
    hits = []
    prev_end, prev_marked = -10**9, False
    for m in EMAIL.finditer(text):
        email = m.group(0).rstrip(".")
        if _NOT_PERSONAL.search(email) or _FILE_TLD.search(email):
            continue
        before = text[max(0, m.start() - 250, prev_end):m.start()]
        # a marker counts for the addresses right after it, or for a short list that follows it
        marked = bool(_MARKER.search(before)) or (prev_marked and m.start() - prev_end < 120)
        prev_end, prev_marked = m.end(), marked
        score = 3 if marked else 0
        score += 1 if m.start() < len(text) * 0.15 else 0     # front matter
        hits.append((score, m.start(), email.lower(), before))
    if not hits:
        return []
    top = max(h[0] for h in hits)
    seen, used, out = set(), set(), []
    for score, _, email, before in sorted((h for h in hits if h[0] == top), key=lambda h: h[1]):
        if email in seen:
            continue
        seen.add(email)
        _, name = _name_for(email, authors)
        if not name:
            m = None
            for m in _NAME_AFTER_MARKER.finditer(before):
                pass
            name = m.group(1).strip() if m else ""
            if _NOT_A_NAME.search(name):
                name = ""
        if name in used:
            name = ""                         # one name per person: never reuse it for another address
        used.add(name)
        out.append({"name": name, "email": email})
        if len(out) == limit:
            break
    return out


def crossref_authors(doi):
    """["Firstname Lastname", ...] from Crossref, or [] (network)."""
    import urllib.parse
    from .http import get_json
    m = (get_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}") or {}).get("message") or {}
    return [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in m.get("author") or []
            if a.get("family")]

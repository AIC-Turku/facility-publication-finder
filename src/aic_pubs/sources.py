"""Where papers and their full text come from.

UTUPub (University of Turku, DSpace 7 REST): every research output of the
  university, with DOI, the university's own list of affiliated authors,
  field-of-science codes and — for open or self-archived versions — an
  extracted-text bitstream.
Åbo Akademi research portal (Pure, OAI-PMH): same role for ÅA; files are PDFs.
Europe PMC: acknowledgement-section search across all open full texts, which
  catches users outside UTU/ÅA and papers not yet self-archived.
"""
import re
import urllib.parse
import xml.etree.ElementTree as ET

from .http import fetch, get_json
from .text import pdf_text

UTUPUB = "https://www.utupub.fi/server/api"
ABO_OAI = "https://research.abo.fi/ws/oai"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# Statistics Finland field-of-science top levels screened by default:
# 1 natural sciences, 2 engineering, 3 medical & health, 4 agricultural.
# 2025 check: the 993 UTUPub papers outside these fields gave 0 AIC leads.
SCIENCE_FIELDS = ("1", "2", "3", "4")


def is_science(item):
    """True when a UTUPub item has a science field code, or no field codes at all."""
    fields = item.get("fields") or []
    return not fields or any(str(f)[:1] in SCIENCE_FIELDS for f in fields)


def clean_authors(names):
    """Drop UTUPub placeholder entries ("Dataimport, <unit>") that are not people."""
    return [n for n in names or [] if not n.lower().startswith(("dataimport", "data import"))]


def _norm_doi(value):
    """Canonicalize common DOI wrappers without damaging valid DOI punctuation."""
    value = urllib.parse.unquote(str(value or "")).strip()
    value = re.sub(r"^(?:urn:doi:|doi:\s*)", "", value, flags=re.I)
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = value.strip().strip("<>\"'")
    match = re.search(r"10\.\d{4,9}/\S+", value, flags=re.I)
    if not match:
        return ""
    doi = match.group(0).lower()
    doi = re.split(r"[?#]|&amp;|&lt;|<", doi)[0]  # URL query strings, fragments, HTML junk
    doi = re.sub(r"/(full|abstract|pdf|epdf|html)(/pdf)?$", "", doi)  # publisher URL suffixes
    doi = doi.rstrip(".,;:")
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        while doi.endswith(closer) and doi.count(closer) > doi.count(opener):
            doi = doi[:-1]
    return doi


# --------------------------------------------------------------------- UTUPub
def utupub_items(year, base_url=UTUPUB, query="dc.year.issued:{year} AND dc.relation.doi:[* TO *]",
                 doi_fields=("dc.relation.doi", "dc.identifier.doi")):
    """All items of a DSpace 7 repository with a DOI issued in `year` (metadata only).
    Defaults: UTUPub. Other DSpace 7 instances: set base_url/query in facility.yaml."""
    items, page = [], 0
    while True:
        q = urllib.parse.urlencode({
            "query": query.format(year=year),
            "dsoType": "ITEM", "size": 100, "page": page})
        d = get_json(f"{base_url}/discover/search/objects?{q}")
        if not d:
            raise RuntimeError(f"UTUPub search failed on page {page}")
        res = d["_embedded"]["searchResult"]
        for o in res["_embedded"]["objects"]:
            it = o["_embedded"]["indexableObject"]
            m = it["metadata"]
            g = lambda k: [v["value"] for v in m.get(k, [])]
            items.append({
                "doi": next((d for f in doi_fields for d in map(_norm_doi, g(f)) if d), ""),
                "title": (g("dc.title") or [""])[0],
                "journal": (g("dc.relation.ispartofjournal") or [""])[0],
                "year": year,
                "type": (g("dc.okm.type") or [""])[0],
                "fields": sorted({x.split()[0] for x in g("dc.okm.discipline")}),
                "local_authors": clean_authors(g("dc.okm.affiliatedauthor")),
                "units": [re.sub(r"^fi=[^|]*\|en=|\|$", "", u) for u in g("dc.contributor.organization")],
                "utupub_uuid": it["uuid"],
                "dspace_base": base_url,
            })
        page += 1
        if page >= res["page"]["totalPages"]:
            return items


def utupub_text(uuid, base_url=UTUPUB):
    """Extracted full text, or None when there is no file or it is embargoed."""
    b = get_json(f"{base_url or UTUPUB}/core/items/{uuid}/bundles?embed=bitstreams")
    for bundle in (b or {}).get("_embedded", {}).get("bundles", []):
        if bundle["name"] != "TEXT":
            continue
        for bs in bundle["_embedded"]["bitstreams"]["_embedded"]["bitstreams"]:
            t = fetch(bs["_links"]["content"]["href"])
            if t and t.strip():  # some TEXT files are only whitespace
                return t
    return None


# ------------------------------------------------------------ Åbo Akademi Pure
def _xml_local(tag):
    return tag.rsplit("}", 1)[-1]


def abo_items(year, base_url=ABO_OAI, set_spec="publications:year{year}", file_prefix=None):
    """Publications of `year` from a Pure OAI-PMH endpoint (default: Åbo Akademi).

    Parse OAI as XML rather than with regexes so namespaces, escaped text and
    harmless formatting changes do not alter the harvest.
    """
    out = {}
    file_prefix = file_prefix or base_url.rsplit("/oai", 1)[0] + "/files/"
    url = f"{base_url}?verb=ListRecords&metadataPrefix=oai_dc&set={set_spec.format(year=year)}"
    while url:
        x = fetch(url, timeout=120)
        if x is None:
            raise RuntimeError("ÅA OAI-PMH harvest failed")
        try:
            root = ET.fromstring(x)
        except ET.ParseError as exc:
            raise RuntimeError("ÅA OAI-PMH returned invalid XML") from exc

        for rec in (node for node in root.iter() if _xml_local(node.tag) == "record"):
            identifiers = []
            titles = []
            creators = []
            files = []
            for node in rec.iter():
                text = (node.text or "").strip()
                if not text:
                    continue
                local = _xml_local(node.tag)
                if local == "title":
                    titles.append(text)
                elif local == "creator":
                    creators.append(text)
                elif local == "identifier":
                    identifiers.append(text)
                    if text.startswith(file_prefix):
                        files.append(text)

            identifier_blob = "\n".join(identifiers)
            dois = {
                _norm_doi(match)
                for match in re.findall(r"10\.\d{4,9}/[^\s<>\"']+", identifier_blob)
            }
            for doi in dois:
                entry = out.setdefault(
                    doi,
                    {"title": titles[0] if titles else "", "files": [], "authors": []},
                )
                entry["files"] = sorted(set(entry["files"]) | set(files))
                entry["authors"] = sorted(set(entry["authors"]) | set(creators))

        token = next(
            (
                (node.text or "").strip()
                for node in root.iter()
                if _xml_local(node.tag) == "resumptionToken" and (node.text or "").strip()
            ),
            "",
        )
        url = (
            f"{base_url}?verb=ListRecords&resumptionToken={urllib.parse.quote(token)}"
            if token else None
        )
    return out

def abo_text(files):
    """Return text from the first readable deposited PDF.

    Pure file URLs are not required to end in .pdf; inspect the bytes instead.
    """
    for url in files:
        data = fetch(url, binary=True)
        if data and data[:4] == b"%PDF":
            text = pdf_text(data)
            if text and text.strip():
                return text
    return None


# ------------------------------------------------------------------ Europe PMC
def europepmc_ack_search(year, names, grants=(), *, timeout=60, max_pages=20,
                           page_size=1000):
    """Facility/funding search with bounded cursor pagination."""
    terms = " OR ".join(f'ACK_FUND:"{n}" OR METHODS:"{n}"' for n in names)
    query = f"(({terms}) AND (ACK_FUND:Turku OR METHODS:Turku OR AFF:Turku))"
    if grants:
        query += " OR " + " OR ".join(f'ACK_FUND:"{g}"' for g in grants)
    query = f"({query}) AND PUB_YEAR:{year}"

    hits, cursor, pages = [], "*", 0
    page_size = max(1, min(int(page_size), 1000))
    while cursor and pages < int(max_pages):
        pages += 1
        q = urllib.parse.urlencode({
            "query": query,
            "format": "json",
            "pageSize": page_size,
            "cursorMark": cursor,
            "resultType": "lite",
        })
        d = get_json(f"{EPMC}/search?{q}", timeout=timeout)
        if not d:
            # never return silently truncated results: 8 papers in 2025 came only from here
            raise RuntimeError(f"Europe PMC acknowledgement search failed after {len(hits)} hits")
        page = d.get("resultList", {}).get("result", [])
        hits += page
        nxt = d.get("nextCursorMark")
        if not page or not nxt or nxt == cursor:
            cursor = None
            break
        cursor = nxt

    truncated = bool(cursor and pages >= int(max_pages))
    rows = [{
        "doi": _norm_doi(h.get("doi")),
        "title": h.get("title", ""),
        "journal": h.get("journalTitle", ""),
        "pmcid": h.get("pmcid"),
        # preprints have no PMCID; their full text is served under the PPR id
        "epmc_id": h.get("id") if h.get("source") == "PPR" else None,
        "year": year,
    } for h in hits if h.get("doi")]
    if truncated:
        for row in rows:
            row["discovery_truncated"] = True
    return rows


def europepmc_text(pmcid):
    if not pmcid:
        return None
    x = fetch(f"{EPMC}/{pmcid}/fullTextXML")
    import html  # entities such as "Cell Imaging &amp; Cytometry Core" must be decoded
    return html.unescape(re.sub(r"<[^>]+>", " ", x)) if x else None


# ------------------------------------------- facility website (benchmark only)
def website_list(year, page_url, core_slug):
    """DOIs on the facility's own publication page for `year`.

    The page is cached, so its AJAX nonce is stale; a cache-busting query
    string yields a fresh one.
    """
    import http.cookiejar
    import random
    import urllib.request
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    ua = {"User-Agent": "Mozilla/5.0"}
    html = opener.open(urllib.request.Request(f"{page_url}?nc={random.randint(1, 10**9)}", headers=ua),
                       timeout=60).read().decode("utf-8", "ignore")
    nonce = re.search(r'data-nonce="([^"]+)"', html).group(1)
    ajax = re.search(r'"ajax_url"\s*:\s*"([^"]+)"', html)
    ajax = ajax.group(1).replace("\\/", "/") if ajax else "https://bioscience.fi/wp-admin/admin-ajax.php"
    body = urllib.parse.urlencode({"action": "load_publications_by_year", "security": nonce,
                                   "year": year, "core": core_slug}).encode()
    import json
    resp = json.loads(opener.open(urllib.request.Request(ajax, data=body, headers=ua), timeout=60).read())
    h = resp["data"]["html"]
    return sorted({_norm_doi(d) for d in re.findall(r'doi\.org/(10\.[^"\s<>]+)', h)})

"""Load facilities/<facility>/facility.yaml into compiled patterns.

Everything facility-specific lives in one folder, facilities/<facility>/: the rules
(facility.yaml), the confirmed papers (papers/<year>.yaml).
Another facility copies facilities/template/ and sets PUBS_FACILITY (a folder name under
facilities/, or a path).
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FACILITIES = ROOT / "facilities"
DEFAULT_FACILITY = "aic-turku"


def data_root() -> Path:
    """Working data (candidates, screening, full-text cache, embeddings, sheets):
    $PUBS_DATA (the notebooks: a Google Drive folder), else data/ in the checkout."""
    return Path(os.environ.get("PUBS_DATA") or ROOT / "data")


def private_root() -> Path:
    """Private inputs and everything derived from them: $PUBS_PRIVATE (the notebooks: the
    temporary Colab disk), else private/ in the checkout. Never in Drive or the repository."""
    return Path(os.environ.get("PUBS_PRIVATE") or ROOT / "private")


def facility_dir(name: str | None = None) -> Path:
    """The facility folder: `name`, else $PUBS_FACILITY, else facilities/aic-turku."""
    name = name or os.environ.get("PUBS_FACILITY") or DEFAULT_FACILITY
    path = Path(name)
    return path if path.is_dir() else FACILITIES / name


def config_path():
    """facility.yaml of the current facility (resolved at call time, so --facility works)."""
    return facility_dir() / "facility.yaml"




def _rx(p):
    return re.compile(re.sub(r"\s*\n\s*", "", p.strip()), re.I)


@dataclass
class Instrument:
    id: str
    strength: str
    pattern: re.Pattern
    exclude: re.Pattern | None = None
    components: list = field(default_factory=list)

    def matches(self, sentence):
        return bool(self.pattern.search(sentence)) and not (
            self.exclude and self.exclude.search(sentence))


@dataclass
class Technique:
    id: str
    vocab: str
    strength: str
    pattern: re.Pattern


@dataclass
class Config:
    raw: dict
    acknowledgement: list = field(default_factory=list)
    flowing: re.Pattern = None
    affiliation: re.Pattern = None
    network: list = field(default_factory=list)
    other_local_imaging: list = field(default_factory=list)
    microscopy: re.Pattern = None
    email: re.Pattern = None
    instruments: list = field(default_factory=list)
    techniques: list = field(default_factory=list)
    other_facilities: list = field(default_factory=list)
    generic_facility: re.Pattern = None
    not_light_microscopy: re.Pattern = None
    score: dict = field(default_factory=dict)
    staff: list = field(default_factory=list)
    life_science_fields: tuple = ()
    life_science_units: re.Pattern = None
    review_title: re.Pattern = None
    dataset_prefixes: tuple = ()
    preprint_prefixes: tuple = ()
    turku_words: re.Pattern = None
    other_institution: re.Pattern = None
    postal: re.Pattern = None
    facility_terms: re.Pattern = None
    institutional_sources: list = field(default_factory=list)
    email_domains: tuple = ()

    @property
    def local_sources(self):
        """Names of the institutional sources: their records have local authors."""
        return {s["name"] for s in self.institutional_sources}

    @property
    def sources_without_author_lists(self):
        return {s["name"] for s in self.institutional_sources if s.get("author_list_complete") is False}

    @property
    def evidence_patterns(self):
        """Sentences worth showing a reviewer."""
        return (self.acknowledgement + self.network + self.other_local_imaging
                + [i.pattern for i in self.instruments]
                + [t.pattern for t in self.techniques if t.strength == "specialist"]
                + [re.compile(r"\b(Zeiss|Leica|Nikon|Olympus|Evident|Andor|Abberior|Yokogawa|"
                              r"core facilit|imaging (core|facilit|unit|cent))", re.I)])


REQUIRED = ("facility", "institutional_sources", "acknowledgement_patterns", "false_positive_contexts",
            "network_patterns", "other_local_imaging", "microscopy_terms", "instruments",
            "generic_imaging_facility", "not_light_microscopy", "score", "life_science_fields",
            "life_science_units", "review_title", "dataset_doi_prefixes", "preprint_doi_prefixes",
            "other_institution", "local_email_domains", "europepmc_search_terms")
ADAPTERS = ("dspace7", "pure_oai")


def _validate(raw: dict, path: Path) -> None:
    """Fail early, naming the file and the key, rather than half-working later."""
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: not a YAML mapping")
    missing = [k for k in REQUIRED if k not in raw]
    if not (raw.get("local_place_words") or raw.get("turku_words")):
        missing.append("local_place_words")
    if missing:
        raise ValueError(f"{path}: missing {', '.join(missing)} (see facilities/template/facility.yaml)")
    if raw.get("institutional_fields", "science") not in ("science", "all"):
        raise ValueError(f"{path}: institutional_fields must be 'science' or 'all', "
                         f"not {raw['institutional_fields']!r}")
    sources = raw["institutional_sources"]
    if not sources:
        raise ValueError(f"{path}: institutional_sources is empty: the candidate backbone would be empty")
    for src in sources:
        if not src.get("name") or src.get("adapter") not in ADAPTERS:
            raise ValueError(f"{path}: institutional source {src!r} needs a name and an adapter "
                             f"({' or '.join(ADAPTERS)})")
    for name in ("affiliation",):
        if name not in raw["false_positive_contexts"]:
            raise ValueError(f"{path}: false_positive_contexts.{name} is missing")


def load(path: Path | str | None = None) -> "Config":
    """The facility's rules, compiled. Raises ValueError on a missing or invalid setting."""
    path = Path(path or config_path())
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _validate(raw, path)
    fp = raw["false_positive_contexts"]
    domains = "|".join(re.escape(d) for d in raw["local_email_domains"])
    return Config(
        raw=raw,
        acknowledgement=[_rx(p) for p in raw["acknowledgement_patterns"]],
        flowing=_rx(fp["flowing_software"]) if fp.get("flowing_software") else re.compile(r"(?!x)x"),
        affiliation=_rx(fp["affiliation"]),
        network=[_rx(p) for p in raw["network_patterns"]],
        other_local_imaging=[_rx(p) for p in raw["other_local_imaging"]],
        microscopy=re.compile("|".join(raw["microscopy_terms"]), re.I),
        email=re.compile(rf"[\w.\-]+@({domains})\b", re.I),
        instruments=[Instrument(k, v["strength"], _rx(v["pattern"]),
                                _rx(v["exclude"]) if v.get("exclude") else None,
                                [_rx(c) for c in v.get("components", [])])
                     for k, v in raw["instruments"].items()],
        other_facilities=[_rx(p) for p in raw.get("other_facilities", [])],
        generic_facility=_rx(raw["generic_imaging_facility"]),
        not_light_microscopy=_rx(raw["not_light_microscopy"]),
        score=raw["score"],
        staff=raw.get("facility_staff") or [],
        life_science_fields=tuple(raw["life_science_fields"]),
        life_science_units=_rx(raw["life_science_units"]),
        review_title=_rx(raw["review_title"]),
        dataset_prefixes=tuple(raw["dataset_doi_prefixes"]),
        preprint_prefixes=tuple(raw["preprint_doi_prefixes"]),
        turku_words=_rx(raw.get("local_place_words") or raw["turku_words"]),
        other_institution=_rx(raw["other_institution"]),
        postal=_rx(raw["postal_patterns"]) if raw.get("postal_patterns") else re.compile(r"(?!x)x"),
        facility_terms=_rx(raw.get("facility_name_terms") or "acknowledg|thank|grateful|funded|grant"),
        institutional_sources=list(raw.get("institutional_sources") or []),
        email_domains=tuple(raw["local_email_domains"]),
        techniques=[Technique(k, v["vocab"], v["strength"], re.compile(v["pattern"], re.I))
                    for k, v in raw.get("techniques", {}).items()],
    )

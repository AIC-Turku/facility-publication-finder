from facility_pubs import fulltext


def test_crossref_links_only_keep_textual_content(monkeypatch):
    monkeypatch.setattr(
        fulltext.sources,
        "crossref_work",
        lambda doi: {
            "link": [
                {"URL": "https://example.org/a.pdf", "content-type": "application/pdf"},
                {"URL": "https://example.org/a.xml", "content-type": "application/xml"},
                {"URL": "https://example.org/data.zip", "content-type": "application/zip"},
                {"URL": "https://example.org/similarity.pdf", "content-type": "application/pdf",
                 "intended-application": "similarity-checking"},
            ]
        },
    )
    links = fulltext.crossref_text_links("10.1000/x")
    assert [x["url"] for x in links] == [
        "https://example.org/a.pdf",
        "https://example.org/a.xml",
    ]


def test_openalex_oa_locations_require_open_pdf(monkeypatch):
    monkeypatch.setattr(
        fulltext,
        "openalex_record",
        lambda doi, api_key=None: {
            "locations": [
                {"pdf_url": "https://example.org/open.pdf", "is_oa": True,
                 "license": "cc-by", "version": "acceptedVersion"},
                {"pdf_url": "https://example.org/closed.pdf", "is_oa": False},
                {"landing_page_url": "https://example.org/no-pdf", "is_oa": True},
            ]
        },
    )
    rows = fulltext.openalex_oa_locations("10.1000/x")
    assert rows == [{
        "url": "https://example.org/open.pdf",
        "license": "cc-by",
        "version": "acceptedVersion",
        "landing_page_url": None,
    }]


def test_resolver_prefers_local_repository(monkeypatch):
    article = "Cells were imaged by confocal microscopy in this local repository text. " * 60
    monkeypatch.setattr(fulltext.sources, "utupub_text", lambda uuid, base=None: article)
    monkeypatch.setattr(fulltext, "crossref_text_links", lambda doi: (_ for _ in ()).throw(
        AssertionError("Crossref should not be reached")
    ))
    result = fulltext.resolve_text({"doi": "10.1000/x", "utupub_uuid": "u1"})
    assert result.text == article
    assert result.source == "utupub"


def test_resolver_uses_crossref_before_openalex(monkeypatch):
    monkeypatch.setattr(fulltext.sources, "europepmc_lookup_doi", lambda doi: None)
    monkeypatch.setattr(
        fulltext,
        "crossref_text_links",
        lambda doi: [{"url": "https://publisher.example/full.xml"}],
    )
    monkeypatch.setattr(fulltext, "_download_text", lambda url: "microscopy methods")
    monkeypatch.setattr(fulltext, "openalex_oa_locations", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("OpenAlex should not be reached")
    ))
    result = fulltext.resolve_text({"doi": "10.1000/x"})
    assert result.source == "crossref_fulltext"
    assert result.text == "microscopy methods"


def test_publisher_landing_url_from_crossref(monkeypatch):
    monkeypatch.setattr(
        fulltext.sources,
        "crossref_work",
        lambda doi: {"URL": "https://publisher.example/article"},
    )
    assert fulltext.crossref_landing_url("10.1000/x") == "https://publisher.example/article"


def test_crossref_text_links_deduplicate_urls(monkeypatch):
    monkeypatch.setattr(
        fulltext.sources,
        "crossref_work",
        lambda doi: {
            "link": [
                {"URL": "https://example.org/a.pdf", "content-type": "application/pdf"},
                {"URL": "https://example.org/a.pdf", "content-type": "application/pdf"},
            ]
        },
    )
    rows = fulltext.crossref_text_links("10.1000/x")
    assert [row["url"] for row in rows] == ["https://example.org/a.pdf"]


def test_openalex_locations_are_deduplicated_and_version_ranked(monkeypatch):
    monkeypatch.setattr(
        fulltext,
        "openalex_record",
        lambda doi, api_key=None: {
            "locations": [
                {
                    "pdf_url": "https://example.org/preprint.pdf",
                    "is_oa": True,
                    "version": "submittedVersion",
                },
                {
                    "pdf_url": "https://example.org/published.pdf",
                    "is_oa": True,
                    "version": "publishedVersion",
                },
                {
                    "pdf_url": "https://example.org/published.pdf",
                    "is_oa": True,
                    "version": "publishedVersion",
                },
                {
                    "pdf_url": "https://example.org/accepted.pdf",
                    "is_oa": True,
                    "version": "acceptedVersion",
                },
            ]
        },
    )
    rows = fulltext.openalex_oa_locations("10.1000/x")
    assert [row["version"] for row in rows] == [
        "publishedVersion",
        "acceptedVersion",
        "submittedVersion",
    ]


def test_whitespace_repository_text_falls_through_to_abo(monkeypatch):
    """10.1016/j.matdes.2025.114920: UTUPub TEXT was 12 newlines, the ÅA PDF acknowledges AIC."""
    article = "The Cell Imaging and Cytometry Core is acknowledged for imaging support. " * 60
    monkeypatch.setattr(fulltext.sources, "utupub_text", lambda uuid, base=None: "\n" * 12)
    monkeypatch.setattr(fulltext.sources, "abo_text", lambda files: article)
    result = fulltext.resolve_text({"doi": "10.1000/x", "utupub_uuid": "u1", "abo_files": ["f"]})
    assert result.source == "abo" and result.text == article


def test_preprint_full_text_via_europepmc_ppr_id(monkeypatch):
    """10.1101/2025.00.00.000009: acknowledges the CIC; Europe PMC serves it as PPR1017423."""
    article = "Imaging was performed at the Cell Imaging and Cytometry Core, Turku Bioscience Centre. " * 40
    monkeypatch.setattr(fulltext.sources, "europepmc_lookup_doi",
                        lambda doi: {"pmcid": None, "epmc_id": "PPR1017423"})
    monkeypatch.setattr(fulltext.sources, "europepmc_text",
                        lambda i: article if i == "PPR1017423" else None)
    monkeypatch.setattr(fulltext, "crossref_text_links", lambda doi: [])
    r = fulltext.resolve_text({"doi": "10.1101/2025.00.00.000009"})
    assert r.source == "europepmc" and r.text == article

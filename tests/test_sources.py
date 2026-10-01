from facility_pubs import sources


def test_abo_oai_xml_parser_handles_namespaces_and_escaping(monkeypatch):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
  <ListRecords>
    <record>
      <header><identifier>oai:pure.abo.fi:1</identifier></header>
      <metadata>
        <oai_dc:dc>
          <dc:title>A &amp; B microscopy paper</dc:title>
          <dc:creator>Example, Erik</dc:creator>
          <dc:identifier>https://doi.org/10.1000/ABC</dc:identifier>
          <dc:identifier>https://research.abo.fi/ws/files/123/article.pdf</dc:identifier>
        </oai_dc:dc>
      </metadata>
    </record>
    <resumptionToken></resumptionToken>
  </ListRecords>
</OAI-PMH>"""
    monkeypatch.setattr(sources, "fetch", lambda url, timeout=120: xml)
    rows = sources.abo_items(2025)
    assert rows == {
        "10.1000/abc": {
            "title": "A & B microscopy paper",
            "files": ["https://research.abo.fi/ws/files/123/article.pdf"],
            "authors": ["Example, Erik"],
        }
    }


def test_abo_oai_xml_parser_follows_resumption_token(monkeypatch):
    pages = [
        """<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
                     xmlns:dc="http://purl.org/dc/elements/1.1/"
                     xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
          <ListRecords>
            <record><metadata><oai_dc:dc>
              <dc:title>First</dc:title>
              <dc:identifier>10.1000/first</dc:identifier>
            </oai_dc:dc></metadata></record>
            <resumptionToken>next page</resumptionToken>
          </ListRecords>
        </OAI-PMH>""",
        """<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
                     xmlns:dc="http://purl.org/dc/elements/1.1/"
                     xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
          <ListRecords>
            <record><metadata><oai_dc:dc>
              <dc:title>Second</dc:title>
              <dc:identifier>10.1000/second</dc:identifier>
            </oai_dc:dc></metadata></record>
            <resumptionToken></resumptionToken>
          </ListRecords>
        </OAI-PMH>""",
    ]
    calls = []
    def fake(url, timeout=120):
        calls.append(url)
        return pages[len(calls) - 1]

    monkeypatch.setattr(sources, "fetch", fake)
    rows = sources.abo_items(2025)
    assert set(rows) == {"10.1000/first", "10.1000/second"}
    assert "resumptionToken=next%20page" in calls[1]


def test_abo_oai_ignores_doi_outside_identifier(monkeypatch):
    xml = """<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
                     xmlns:dc="http://purl.org/dc/elements/1.1/"
                     xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
      <ListRecords>
        <record><metadata><oai_dc:dc>
          <dc:title>Paper</dc:title>
          <dc:description>Previous work 10.1000/not-this-paper is discussed.</dc:description>
          <dc:identifier>https://doi.org/10.1000/actual</dc:identifier>
        </oai_dc:dc></metadata></record>
        <resumptionToken></resumptionToken>
      </ListRecords>
    </OAI-PMH>"""
    monkeypatch.setattr(sources, "fetch", lambda url, timeout=120: xml)
    rows = sources.abo_items(2025)
    assert set(rows) == {"10.1000/actual"}


def test_abo_text_detects_pdf_without_pdf_suffix(monkeypatch):
    monkeypatch.setattr(
        sources,
        "fetch",
        lambda url, binary=True: b"%PDF fake bytes",
    )
    monkeypatch.setattr(sources, "pdf_text", lambda data: "full article text")
    assert sources.abo_text(
        ["https://research.abo.fi/ws/files/12345/download"]
    ) == "full article text"


def test_europepmc_ack_search_respects_page_limit(monkeypatch):
    calls = []
    def fake(url, timeout=60):
        calls.append(url)
        page = len(calls)
        return {
            "resultList": {"result": [{
                "doi": f"10.1000/{page}",
                "title": f"Paper {page}",
                "journalTitle": "J",
            }]},
            "nextCursorMark": f"cursor-{page}",
        }

    monkeypatch.setattr(sources, "get_json", fake)
    rows = sources.europepmc_ack_search(
        2025,
        ["Advanced Imaging Core"],
        timeout=5,
        max_pages=2,
        page_size=1,
    )
    assert [row["doi"] for row in rows] == ["10.1000/1", "10.1000/2"]
    assert len(calls) == 2
    assert all("pageSize=1" in url for url in calls)
    assert all(row["discovery_truncated"] is True for row in rows)

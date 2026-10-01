import urllib.error

from aic_pubs import http


class _Headers:
    def __init__(self, content_type="text/plain"):
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type


class _Response:
    def __init__(self, body=b"ok", status=200, url="https://example.org/final",
                 content_type="text/plain"):
        self._body = body
        self.status = status
        self._url = url
        self.headers = _Headers(content_type)

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_result_preserves_success_metadata(monkeypatch):
    monkeypatch.setattr(
        http.urllib.request,
        "urlopen",
        lambda req, timeout=60: _Response(
            body=b"article",
            status=200,
            url="https://publisher.example/article",
            content_type="text/html",
        ),
    )
    result = http.fetch_result("https://doi.org/10.1000/x", tries=1)
    assert result.ok
    assert result.body == b"article"
    assert result.status == 200
    assert result.final_url == "https://publisher.example/article"
    assert result.content_type == "text/html"


def test_fetch_result_preserves_restricted_status(monkeypatch):
    def denied(req, timeout=60):
        raise urllib.error.HTTPError(
            req.full_url,
            403,
            "Forbidden",
            _Headers("text/html"),
            None,
        )

    monkeypatch.setattr(http.urllib.request, "urlopen", denied)
    result = http.fetch_result("https://example.org/restricted", tries=1)
    assert not result.ok
    assert result.status == 403
    assert result.error == "http_403"
    assert http.fetch("https://example.org/restricted", tries=1) is None


def test_retry_after_header_is_bounded():
    headers = {"Retry-After": "17"}
    assert http._retry_after_seconds(headers, 10) == 17
    assert http._retry_after_seconds({"Retry-After": "999"}, 10) == 120
    assert http._retry_after_seconds({"Retry-After": "n/a"}, 10) == 10


def test_exhausted_host_is_skipped_for_the_rest_of_the_run(monkeypatch):
    """OpenAlex answers anonymous requests with 429 'Insufficient budget'; retrying
    stalled every later request for minutes (seen 2026-09-28)."""
    import io
    import urllib.error
    from aic_pubs import http

    http.reset_circuit_breaker()
    calls = []

    from email.message import Message
    headers = Message()
    headers["Retry-After"] = "40000"

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", headers,
                                     io.BytesIO(b'{"message": "Insufficient budget."}'))

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept")))
    first = http.fetch_result("https://api.openalex.org/works?x=1")
    second = http.fetch_result("https://api.openalex.org/works?x=2")
    assert first.error == second.error == "host_exhausted"
    assert len(calls) == 1  # the second request never leaves the machine
    http.reset_circuit_breaker()


def test_openalex_is_not_called_without_a_key(monkeypatch):
    from aic_pubs import fulltext

    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr(fulltext.discovery, "europepmc_lookup_doi", lambda doi: None)
    monkeypatch.setattr(fulltext, "crossref_text_links", lambda doi: [])
    monkeypatch.setattr(fulltext, "openalex_oa_locations",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("OpenAlex called")))
    assert fulltext.resolve_text({"doi": "10.1000/x"}).text is None

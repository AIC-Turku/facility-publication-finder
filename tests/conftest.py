import pytest


@pytest.fixture(autouse=True)
def empty_confirmed_papers(monkeypatch, tmp_path_factory):
    """Tests never see the real confirmed papers unless they ask for them."""
    from aic_pubs import papers
    folder = tmp_path_factory.mktemp("papers")
    monkeypatch.setattr(papers, "papers_dir", lambda facility=None: folder)
    monkeypatch.setattr(papers, "inbox_path", lambda facility=None: folder.parent / "inbox.txt")
    return folder


@pytest.fixture(autouse=True)
def temporary_private_folder(monkeypatch, tmp_path_factory):
    """Anything derived from private inputs goes to a temporary folder in tests."""
    from aic_pubs import bookings
    folder = tmp_path_factory.mktemp("private")
    monkeypatch.setattr(bookings, "PRIVATE", folder)
    return folder

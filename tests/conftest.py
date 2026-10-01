import pytest


@pytest.fixture(autouse=True)
def isolated_folders(monkeypatch, tmp_path_factory):
    """Every test gets its own working-data and private folders (never the real ones)."""
    data = tmp_path_factory.mktemp("data")
    monkeypatch.setenv("PUBS_DATA", str(data))
    monkeypatch.setenv("PUBS_PRIVATE", str(tmp_path_factory.mktemp("private")))
    return data


@pytest.fixture(autouse=True)
def empty_confirmed_papers(monkeypatch, tmp_path_factory):
    """Tests never see the real confirmed papers unless they ask for them."""
    from aic_pubs import papers
    folder = tmp_path_factory.mktemp("papers")
    monkeypatch.setattr(papers, "papers_dir", lambda facility=None: folder)
    monkeypatch.setattr(papers, "inbox_path", lambda facility=None: folder.parent / "inbox.txt")
    return folder

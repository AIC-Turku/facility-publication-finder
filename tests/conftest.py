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
    from facility_pubs import papers
    folder = tmp_path_factory.mktemp("papers")
    monkeypatch.setattr(papers, "papers_dir", lambda facility=None: folder)
    return folder

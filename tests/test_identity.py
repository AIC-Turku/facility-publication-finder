import pytest

from aic_pubs.identity import load_users, normalise_orcid


def test_normalise_orcid_accepts_url_and_canonicalises():
    assert normalise_orcid(
        "https://orcid.org/0000-0002-1825-0097"
    ) == "0000-0002-1825-0097"


def test_normalise_orcid_rejects_bad_checksum():
    with pytest.raises(ValueError, match="checksum"):
        normalise_orcid("0000-0002-9286-9200")


def test_load_users_deduplicates_same_orcid(tmp_path):
    path = tmp_path / "users.csv"
    path.write_text(
        "name,institution,orcid\n"
        "Erik Example,Abo Akademi University,0000-0002-1825-0097\n"
        "E. Example,Abo Akademi University,https://orcid.org/0000-0002-1825-0097\n",
        encoding="utf-8",
    )
    users = load_users(path)
    assert len(users) == 1
    assert users[0].orcid == "0000-0002-1825-0097"


def test_load_users_requires_name_column(tmp_path):
    path = tmp_path / "users.csv"
    path.write_text("person,orcid\nSomeone,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="'name' column"):
        load_users(path)

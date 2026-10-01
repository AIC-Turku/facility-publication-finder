from aic_pubs.identity import audit_users


def test_audit_users_reports_private_input_issues_without_names(tmp_path):
    path = tmp_path / "users.csv"
    path.write_text(
        "name,institution,orcid,cris_id\n"
        "Alice Example,University of Turku,0000-0002-1825-0097,\n"
        "Alice Example,University of Turku,0000-0002-1825-0097,\n"
        "Bob Example,University of Turku,,\n"
        "Carol Example,Elsewhere,0000-0000-0000-0000,\n",
        encoding="utf-8",
    )
    out = audit_users(path)
    assert out["rows"] == 4
    assert out["with_orcid"] == 2
    assert out["local_without_orcid"] == 1
    assert out["duplicate_orcid_rows"] == 1
    assert out["duplicate_identity_rows"] == 1
    assert out["ok"] is False
    rendered = str(out)
    assert "Alice" not in rendered
    assert "Bob" not in rendered
    assert "Carol" not in rendered
    assert "0000-0002-1825-0097" not in rendered


def test_audit_users_missing_orcid_is_not_fatal(tmp_path):
    path = tmp_path / "users.csv"
    path.write_text(
        "name,institution,orcid\n"
        "Alice Example,University of Turku,\n",
        encoding="utf-8",
    )
    out = audit_users(path)
    assert out["ok"] is True
    assert out["without_orcid"] == 1
    assert out["local_without_orcid"] == 1

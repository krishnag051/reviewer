"""Regression coverage for tests/conftest.py's own helpers. The single
biggest environment issue in this whole build was `_url_with_dbname` using
bare `str(url_obj)`, which SQLAlchemy masks to a literal "***" password by
default — genuinely wrong credentials were being sent, and Postgres
correctly rejected them. Nothing caught this until it was root-caused by
hand; this guards against it silently coming back.
"""
from tests.conftest import _url_with_dbname


def test_url_with_dbname_preserves_real_password_not_masked():
    url = "postgresql+psycopg2://tpuser:tppass@localhost:5432/tpreview_test"
    result = _url_with_dbname(url, "postgres")

    assert "tppass" in result, "the real password must be present in the built connection string"
    assert "***" not in result, "str(URL) masks the password by default — never reintroduce it here"
    assert result.endswith("/postgres")
    assert "tpuser" in result

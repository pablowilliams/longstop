import http.client
import urllib.error

import pytest

from longstop.edgar import client as edgar_client


def test_it_refuses_to_fetch_without_a_contact_address(monkeypatch):
    monkeypatch.delenv(edgar_client.CONTACT_ENV, raising=False)
    with pytest.raises(edgar_client.ContactNotSet):
        edgar_client.user_agent()


def test_a_contact_address_must_look_like_an_email(monkeypatch):
    monkeypatch.setenv(edgar_client.CONTACT_ENV, "not-an-address")
    with pytest.raises(edgar_client.ContactNotSet):
        edgar_client.user_agent()
    monkeypatch.setenv(edgar_client.CONTACT_ENV, "you@example.com")
    assert "you@example.com" in edgar_client.user_agent()


@pytest.mark.parametrize(
    "error",
    [
        # IncompleteRead is an HTTPException, not a URLError. Omitting it from
        # the retry tuple killed a ninety-six quarter crawl at quarter fifty-two.
        http.client.IncompleteRead(b"partial"),
        urllib.error.URLError("reset"),
        TimeoutError("slow"),
        ConnectionResetError("reset by peer"),
    ],
)
def test_transient_read_failures_are_retried_not_fatal(monkeypatch, tmp_path, error):
    monkeypatch.setenv(edgar_client.CONTACT_ENV, "you@example.com")
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _: None)

    attempts = {"n": 0}

    class Response:
        headers = {}

        def read(self):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise error
            return b"recovered"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(edgar_client.urllib.request, "urlopen", lambda *a, **k: Response())
    fetched = edgar_client.EdgarClient(cache_dir=tmp_path).get("https://example.invalid/x")
    assert fetched == b"recovered"
    assert attempts["n"] == 2


def test_a_404_can_be_tolerated_for_quarters_that_do_not_exist_yet(monkeypatch, tmp_path):
    monkeypatch.setenv(edgar_client.CONTACT_ENV, "you@example.com")

    def raise_404(*_a, **_k):
        raise urllib.error.HTTPError("u", 404, "gone", {}, None)

    monkeypatch.setattr(edgar_client.urllib.request, "urlopen", raise_404)
    assert edgar_client.EdgarClient(cache_dir=tmp_path).get("https://x.invalid", allow_404=True) is None

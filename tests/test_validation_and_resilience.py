import glob, json
import pytest
import config
from core import pipeline
from core.data_fetcher import DataFetcher
from core.validation import is_valid_btc_address


def test_valid_addresses_accepted():
    for a in ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94",
              "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
              "BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4",
              "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"]:
        assert is_valid_btc_address(a), a


def test_invalid_addresses_rejected():
    for a in ["", "hello", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdx",
              "'; DROP TABLE investigations;--", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e", None, "A" * 500]:
        assert not is_valid_btc_address(a)


def test_every_bundled_threat_intel_address_is_a_valid_address():
    for f in glob.glob(str((config.DATA_DIR / "threat_intel") / "*.json")):
        for entry in json.load(open(f)):
            assert is_valid_btc_address(entry["address"]), f"{f}: {entry['address']}"


class _Resp:
    def __init__(self, code, body=None, headers=None):
        self.status_code, self._b, self.headers = code, body, headers or {}
    def json(self):
        return self._b


def test_fetcher_falls_back_to_mirror(monkeypatch):
    monkeypatch.setattr(config, "API_RETRY_BACKOFF_SECONDS", 0)
    f = DataFetcher(base_url="https://primary.test/api", fallbacks=["https://mirror.test/api"])
    monkeypatch.setattr(f.session, "get",
                        lambda url, timeout: _Resp(503) if "primary" in url else _Resp(200, {"ok": 1}))
    assert f._get("/address/A") == {"ok": 1}


def test_fetcher_retries_after_rate_limit(monkeypatch):
    monkeypatch.setattr(config, "API_RETRY_BACKOFF_SECONDS", 0)
    f = DataFetcher(fallbacks=[])
    seq = iter([_Resp(429, headers={"Retry-After": "0"}), _Resp(200, [1])])
    monkeypatch.setattr(f.session, "get", lambda url, timeout: next(seq))
    assert f._get("/x") == [1]


def test_fetcher_reports_error_when_everything_fails(monkeypatch):
    monkeypatch.setattr(config, "API_RETRY_BACKOFF_SECONDS", 0)
    f = DataFetcher(fallbacks=[])
    monkeypatch.setattr(f.session, "get", lambda url, timeout: _Resp(500))
    assert f._get("/x") is None and "500" in f.last_error


def test_pipeline_raises_instead_of_reporting_an_empty_success(monkeypatch):
    monkeypatch.setattr(pipeline.DataFetcher, "get_address_info", lambda self, a: None)
    with pytest.raises(pipeline.FetchError):
        pipeline.run_investigation("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", max_hops=1)


def test_error_message_names_every_failing_server_and_ssl_hint(monkeypatch):
    import requests
    monkeypatch.setattr(config, "API_RETRY_BACKOFF_SECONDS", 0)
    f = DataFetcher(base_url="https://a.test/api", fallbacks=["https://b.test/api"])
    def boom(url, timeout):
        raise requests.exceptions.SSLError("bad cert")
    monkeypatch.setattr(f.session, "get", boom)
    assert f._get("/x") is None
    assert "a.test" in f.last_error and "b.test" in f.last_error and "HTTPS" in f.last_error

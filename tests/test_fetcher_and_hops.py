import config
from core import pipeline
from core.data_fetcher import DataFetcher


def _raw(txid, confirmed=True):
    return {"txid": txid, "status": {"confirmed": confirmed}, "vin": [], "vout": []}


def test_pagination_follows_chain_cursor(monkeypatch):
    monkeypatch.setattr(config, "API_PAGE_DELAY_SECONDS", 0)
    pages = {
        "/address/A/txs": [_raw(f"a{i}") for i in range(25)],
        "/address/A/txs/chain/a24": [_raw(f"b{i}") for i in range(25)],
        "/address/A/txs/chain/b24": [_raw(f"c{i}") for i in range(10)],
    }
    f = DataFetcher()
    monkeypatch.setattr(f, "_get", lambda path: pages.get(path))
    assert len(f.get_address_txs("A", max_txs=500)) == 60
    assert len(f.get_address_txs("A", max_txs=30)) == 30


def test_pagination_stops_on_short_first_page(monkeypatch):
    f = DataFetcher()
    calls = []
    monkeypatch.setattr(f, "_get", lambda path: calls.append(path) or [_raw("x")])
    assert len(f.get_address_txs("A", max_txs=100)) == 1
    assert len(calls) == 1


def test_hop_expansion_fetches_neighbours(monkeypatch):
    def norm(txid, a_in, a_out):
        return {"txid": txid, "inputs": [{"address": a_in, "value_btc": 1.0}],
                "outputs": [{"address": a_out, "value_btc": 0.9}]}

    class FakeFetcher:
        history = {"ROOT": [norm("t1", "N1", "ROOT")], "N1": [norm("t2", "N2", "N1")]}
        def get_address_txs(self, addr, max_txs=0):
            return self.history.get(addr, [])
        @staticmethod
        def normalize_tx(tx):
            return tx

    store = {t["txid"]: t for t in FakeFetcher.history["ROOT"]}
    n = pipeline._expand_hops(FakeFetcher(), "ROOT", store, max_hops=2)
    assert "t2" in store and n >= 2
    store1 = {t["txid"]: t for t in FakeFetcher.history["ROOT"]}
    pipeline._expand_hops(FakeFetcher(), "ROOT", store1, max_hops=1)
    assert "t2" not in store1

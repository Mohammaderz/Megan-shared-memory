from instant_sources import AlertStore, SourceAlert, ethereum_addresses, split_sources


def test_extracts_unique_ethereum_addresses_and_rejects_partial_matches():
    a = "0x" + "aB" * 20
    b = "0x" + "12" * 20
    text = f"new token {a} duplicate {a} invalid 0x1234x {b}x"
    assert ethereum_addresses(text) == [a.lower(), b.lower()]


def test_source_list_parsing():
    assert split_sources(" https://one.test/feed, @channel, ,https://two.test/rss ") == [
        "https://one.test/feed", "@channel", "https://two.test/rss"
    ]


def test_alert_store_deduplicates_source_messages(tmp_path):
    store = AlertStore(str(tmp_path / "alerts.sqlite3"))
    alert = SourceAlert("telegram", "@alerts", "123", None, None, "token", ("0x" + "11" * 20,))
    assert store.add(alert) is True
    assert store.add(alert) is False
    store.close()

from trace_discovery import normalize_erigon_block_trace, normalize_geth_block_trace

TX = "0x" + "ab" * 32
CREATOR = "0x" + "11" * 20
CREATED = "0x" + "22" * 20

def test_normalize_erigon_create_and_create2():
    raw = [
        {"type": "create", "action": {"from": CREATOR, "creationMethod": "create2"},
         "result": {"address": CREATED}, "transactionHash": TX},
        {"type": "create", "action": {"from": CREATOR, "creationMethod": "create"},
         "result": None, "error": "Reverted", "transactionHash": TX},
    ]
    batch = normalize_erigon_block_trace(raw)
    assert batch.provider == "erigon_trace"
    assert len(batch.creations) == 1
    assert batch.creations[0].address == CREATED
    assert batch.creations[0].creation_method == "create2"

def test_normalize_geth_nested_create2():
    raw = [{"txHash": TX, "result": {"type": "CALL", "from": CREATOR,
            "calls": [{"type": "CREATE2", "from": CREATOR, "to": CREATED, "calls": []}]}}]
    batch = normalize_geth_block_trace(raw)
    assert len(batch.creations) == 1
    assert batch.creations[0].address == CREATED
    assert batch.creations[0].creation_method == "create2"

def test_normalize_geth_ignores_reverted_creation():
    raw = [{"txHash": TX, "result": {"type": "CREATE", "from": CREATOR,
            "to": CREATED, "error": "execution reverted"}}]
    assert normalize_geth_block_trace(raw).creations == ()

def test_trace_normalizers_reject_unexpected_shapes():
    import pytest
    with pytest.raises(ValueError):
        normalize_geth_block_trace({})
    with pytest.raises(ValueError):
        normalize_erigon_block_trace({})

def test_auto_mode_falls_back_from_erigon_to_geth():
    from types import SimpleNamespace
    from trace_discovery import TraceDiscovery

    class Provider:
        def __init__(self):
            self.calls = []
        def make_request(self, method, params):
            self.calls.append(method)
            if method == "trace_block":
                return {"error": {"code": -32601, "message": "method not found"}}
            return {"result": [{
                "txHash": TX,
                "result": {"type": "CREATE2", "from": CREATOR, "to": CREATED},
            }]}

    provider = Provider()
    batch = TraceDiscovery(SimpleNamespace(provider=provider), "auto").trace_block(123)
    assert provider.calls == ["trace_block", "debug_traceBlockByNumber"]
    assert batch.provider == "geth_callTracer"
    assert batch.creations[0].creation_method == "create2"


def test_trace_mode_off_does_not_call_rpc():
    from types import SimpleNamespace
    from trace_discovery import TraceDiscovery

    class Provider:
        def make_request(self, method, params):
            raise AssertionError("RPC must not be called in off mode")

    batch = TraceDiscovery(SimpleNamespace(provider=Provider()), "off").trace_block(123)
    assert batch.provider == "disabled"
    assert batch.creations == ()


def _topic_address(address):
    return bytes.fromhex(address[2:].rjust(64, "0"))


def _word(value):
    return int(value).to_bytes(32, "big")


def test_decode_v2_pair_created_event():
    from web3 import Web3
    from megan_watcher import V2_EVENT, decode_v2_pair_created

    token0 = "0x" + "11" * 20
    token1 = "0x" + "22" * 20
    pair = "0x" + "33" * 20
    topics = [bytes.fromhex(V2_EVENT[2:]), _topic_address(token0), _topic_address(token1)]
    data = bytes.fromhex(pair[2:].rjust(64, "0")) + _word(7)
    assert decode_v2_pair_created(topics, data) == (
        Web3.to_checksum_address(token0),
        Web3.to_checksum_address(token1),
        Web3.to_checksum_address(pair),
    )


def test_decode_v3_pool_created_event():
    from web3 import Web3
    from megan_watcher import V3_EVENT, decode_v3_pool_created

    token0 = "0x" + "11" * 20
    token1 = "0x" + "22" * 20
    pool = "0x" + "33" * 20
    fee = 3000
    topics = [
        bytes.fromhex(V3_EVENT[2:]),
        _topic_address(token0),
        _topic_address(token1),
        _word(fee),
    ]
    data = _word(60) + bytes.fromhex(pool[2:].rjust(64, "0"))
    assert decode_v3_pool_created(topics, data) == (
        Web3.to_checksum_address(token0),
        Web3.to_checksum_address(token1),
        Web3.to_checksum_address(pool),
        fee,
    )


def test_v2_decoder_rejects_wrong_topic_and_malformed_data():
    import pytest
    from megan_watcher import decode_v2_pair_created

    with pytest.raises(ValueError):
        decode_v2_pair_created([b"\\x00" * 32] * 3, b"\\x00" * 64)
    with pytest.raises(ValueError):
        decode_v2_pair_created([b"\\x00" * 32] * 3, b"short")


def test_v3_decoder_rejects_invalid_fee_topic():
    import pytest
    from megan_watcher import V3_EVENT, decode_v3_pool_created

    token0 = "0x" + "11" * 20
    token1 = "0x" + "22" * 20
    topics = [bytes.fromhex(V3_EVENT[2:]), _topic_address(token0),
              _topic_address(token1), _word(1 << 32)]
    with pytest.raises(ValueError):
        decode_v3_pool_created(topics, _word(60) + _word(1))

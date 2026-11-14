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

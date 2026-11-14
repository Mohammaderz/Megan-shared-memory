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

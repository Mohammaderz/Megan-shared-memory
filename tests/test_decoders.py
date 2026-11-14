from megan_watcher import decode_text, decode_uint


def abi_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    padded = raw + b"\x00" * ((32 - len(raw) % 32) % 32)
    return (
        (32).to_bytes(32, "big")
        + len(raw).to_bytes(32, "big")
        + padded
    )


def test_decode_abi_string():
    assert decode_text(abi_string("MEGAN")) == "MEGAN"


def test_decode_bytes32_string():
    assert decode_text(b"MEGAN" + b"\x00" * 27) == "MEGAN"


def test_decode_uint():
    assert decode_uint((123456).to_bytes(32, "big")) == 123456


def test_decode_uint_rejects_short_data():
    assert decode_uint(b"\x01\x02") is None


def test_decode_text_rejects_empty_data():
    assert decode_text(b"") is None

import pytest

from megan_watcher import (
    V2_EVENT,
    V3_EVENT,
    decode_text,
    decode_uint,
    decode_v2_pair_created,
    decode_v3_pool_created,
)
from web3 import Web3


def abi_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    padded = raw + b"\x00" * ((32 - len(raw) % 32) % 32)
    return (32).to_bytes(32, "big") + len(raw).to_bytes(32, "big") + padded


def topic_address(value: str) -> bytes:
    return b"\x00" * 12 + bytes.fromhex(value.removeprefix("0x"))


def abi_address_word(value: str) -> bytes:
    return topic_address(value)


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


def test_decode_uniswap_v2_pair_created():
    token0 = "0x0000000000000000000000000000000000000001"
    token1 = "0x0000000000000000000000000000000000000002"
    pair = "0x0000000000000000000000000000000000000003"
    topics = [bytes.fromhex(V2_EVENT[2:]), topic_address(token0), topic_address(token1)]
    data = abi_address_word(pair) + (17).to_bytes(32, "big")

    decoded = decode_v2_pair_created(topics, data)

    assert decoded == (
        Web3.to_checksum_address(token0),
        Web3.to_checksum_address(token1),
        Web3.to_checksum_address(pair),
    )


def test_decode_uniswap_v3_pool_created_fee_is_indexed():
    token0 = "0x0000000000000000000000000000000000000001"
    token1 = "0x0000000000000000000000000000000000000002"
    pool = "0x0000000000000000000000000000000000000003"
    fee = 3000
    topics = [
        bytes.fromhex(V3_EVENT[2:]),
        topic_address(token0),
        topic_address(token1),
        fee.to_bytes(32, "big"),
    ]
    data = (60).to_bytes(32, "big", signed=True) + abi_address_word(pool)

    decoded = decode_v3_pool_created(topics, data)

    assert decoded == (
        Web3.to_checksum_address(token0),
        Web3.to_checksum_address(token1),
        Web3.to_checksum_address(pool),
        fee,
    )


def test_v2_decoder_rejects_wrong_topic():
    topics = [b"\x00" * 32, b"\x00" * 32, b"\x00" * 32]
    with pytest.raises(ValueError):
        decode_v2_pair_created(topics, b"\x00" * 64)


def test_v3_decoder_rejects_missing_fee_topic():
    topics = [bytes.fromhex(V3_EVENT[2:]), b"\x00" * 32, b"\x00" * 32]
    with pytest.raises(ValueError):
        decode_v3_pool_created(topics, b"\x00" * 64)

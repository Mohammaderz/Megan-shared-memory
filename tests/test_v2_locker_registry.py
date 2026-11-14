from pathlib import Path
from types import SimpleNamespace

import pytest

from v2_locker_registry import (
    V2LockerAdapter, load_v2_locker_registry, read_v2_locker_records,
)

PAIR = "0x" + "aa" * 20
LOCKER = "0x" + "bb" * 20
CODE_HASH = "0x" + "ab" * 32


def word(value):
    if isinstance(value, str):
        return bytes.fromhex(value[2:]).rjust(32, bytes(1))
    return int(value).to_bytes(32, "big")


class FakeEth:
    def get_code(self, address, block_identifier=None):
        return b"locker-code"

    def call(self, tx, block_identifier=None):
        if tx["data"].startswith("0x11111111"):
            return (1).to_bytes(32, "big")
        return word("0x" + "cc" * 20) + word(500) + word(1_900_000_000)


class FakeWeb3:
    eth = FakeEth()

    @staticmethod
    def to_checksum_address(value):
        return value.lower()

    @staticmethod
    def keccak(value):
        return SimpleNamespace(hex=lambda: CODE_HASH)


def adapter():
    return V2LockerAdapter(LOCKER, CODE_HASH, "0x11111111", "0x22222222", 20)


def test_v2_locker_records_require_code_hash_and_decode_lock_tuple():
    result = read_v2_locker_records(
        FakeWeb3(), PAIR, 100, (adapter(),), registry_complete=True,
    )
    assert result.complete is True
    assert len(result.locks) == 1
    assert result.locks[0].locker_address == LOCKER
    assert result.locks[0].amount_raw == 500
    assert result.locks[0].unlock_timestamp == 1_900_000_000
    assert result.locks[0].verified is True


def test_v2_registry_not_declared_complete_is_warned():
    result = read_v2_locker_records(FakeWeb3(), PAIR, 100, (adapter(),))
    assert result.complete is False
    assert "locker_registry_not_declared_complete" in result.warnings


def test_v2_code_hash_mismatch_is_not_accepted():
    class WrongHashWeb3(FakeWeb3):
        @staticmethod
        def keccak(value):
            return SimpleNamespace(hex=lambda: "0x" + "cd" * 32)
    result = read_v2_locker_records(
        WrongHashWeb3(), PAIR, 100, (adapter(),), registry_complete=True,
    )
    assert result.complete is False
    assert result.locks == ()
    assert "locker_code_hash_mismatch_or_missing" in result.warnings[0]


def test_v2_registry_validates_chain_pair_and_selectors(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(
        '{"chain_id":1,"pair_address":"' + PAIR +
        '","coverage_complete":true,"lockers":[{"address":"' + LOCKER +
        '","expected_code_hash":"' + CODE_HASH +
        '","lock_count_selector":"0x11111111","lock_info_selector":"0x22222222"}]}'
    )
    loaded = load_v2_locker_registry(str(path), 1, PAIR, lambda value: value.lower())
    assert len(loaded) == 1
    with pytest.raises(ValueError, match="chain_id"):
        load_v2_locker_registry(str(path), 5, PAIR, lambda value: value.lower())
    with pytest.raises(ValueError, match="pair_address"):
        load_v2_locker_registry(str(path), 1, LOCKER, lambda value: value.lower())

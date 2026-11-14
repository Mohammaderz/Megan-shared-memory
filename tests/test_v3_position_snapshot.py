from types import SimpleNamespace

import pytest

from v3_position_snapshot import (
    DEAD, TRANSFER_TOPIC, LockerConfig, fetch_v3_position_snapshot,
    load_locker_registry,
)

MANAGER = "0x" + "aa" * 20
WALLET = "0x" + "11" * 20
LOCKER = "0x" + "22" * 20
TOKEN0 = "0x" + "33" * 20
TOKEN1 = "0x" + "44" * 20
NOW = 1_800_000_000


def topic_address(address):
    return "0x" + "0" * 24 + address[2:]


def transfer(sender, recipient, token_id, index):
    return {
        "topics": [TRANSFER_TOPIC, topic_address(sender), topic_address(recipient),
                   "0x" + token_id.to_bytes(32, "big").hex()],
        "logIndex": index,
    }


class FakeFunction:
    def __init__(self, value):
        self.value = value

    def call(self, block_identifier=None):
        assert block_identifier == 100
        return self.value


class FakeFunctions:
    def ownerOf(self, token_id):
        return FakeFunction(LOCKER)

    def positions(self, token_id):
        return FakeFunction((0, "0x" + "00" * 20, TOKEN0, TOKEN1, 3000,
                             -120, 120, 987654, 0, 0, 12, 34))


class FakeContract:
    functions = FakeFunctions()


class FakeEth:
    chain_id = 1
    block_number = 100
    logs = [transfer("0x" + "00" * 20, LOCKER, 7, 0)]
    owner_code = b"locker-bytecode"
    lock_flag = 1
    unlock_time = NOW + 86400
    block_reads = 0

    def get_block(self, number):
        self.block_reads += 1
        return {"hash": "0x" + "ab" * 32, "timestamp": NOW}

    def get_logs(self, query):
        return list(self.logs)

    def contract(self, address, abi):
        return FakeContract()

    def get_code(self, address, block_identifier=None):
        return self.owner_code if address.lower() == LOCKER.lower() else b""

    def call(self, transaction, block_identifier=None):
        data = transaction["data"]
        value = self.lock_flag if data.startswith("0x12345678") else self.unlock_time
        return value.to_bytes(32, "big")


class FakeWeb3:
    eth = FakeEth()

    @staticmethod
    def to_checksum_address(address):
        return address.lower()

    @staticmethod
    def keccak(value):
        return SimpleNamespace(hex=lambda: "0x" + "ab" * 32)


def config():
    return LockerConfig(LOCKER, "0x" + "ab" * 32, "0x12345678", "0x87654321")


def test_v3_position_contract_custody_is_unknown_without_registry():
    result = fetch_v3_position_snapshot(FakeWeb3(), MANAGER, 1, to_block=100)
    assert result.complete is True
    assert result.minted_position_count == 1
    assert result.active_position_count == 1
    assert result.unknown_count == 1
    assert result.positions[0].custody_status == "unknown"
    assert result.positions[0].liquidity_raw == 987654


def test_v3_verified_locker_requires_matching_code_hash_and_active_lock():
    result = fetch_v3_position_snapshot(
        FakeWeb3(), MANAGER, 1, to_block=100, lockers=[config()]
    )
    assert result.locked_count == 1
    assert result.unknown_count == 0
    assert result.positions[0].custody_status == "locked"
    assert result.positions[0].unlock_timestamp == NOW + 86400


def test_v3_expired_verified_lock_is_unlocked():
    class ExpiredEth(FakeEth):
        unlock_time = NOW - 1
    class ExpiredWeb3(FakeWeb3):
        eth = ExpiredEth()
    result = fetch_v3_position_snapshot(
        ExpiredWeb3(), MANAGER, 1, to_block=100, lockers=[config()]
    )
    assert result.unlocked_count == 1
    assert result.positions[0].custody_status == "unlocked"


def test_v3_code_hash_mismatch_stays_unknown():
    class WrongHashWeb3(FakeWeb3):
        @staticmethod
        def keccak(value):
            return SimpleNamespace(hex=lambda: "0x" + "cd" * 32)
    result = fetch_v3_position_snapshot(
        WrongHashWeb3(), MANAGER, 1, to_block=100, lockers=[config()]
    )
    assert result.unknown_count == 1
    assert "locker_code_hash_mismatch" in result.positions[0].warning


def test_v3_burn_event_does_not_call_owner_of():
    class BurnEth(FakeEth):
        logs = [transfer("0x" + "00" * 20, WALLET, 9, 0),
                transfer(WALLET, "0x" + "00" * 20, 9, 1)]
    class BurnWeb3(FakeWeb3):
        eth = BurnEth()
    result = fetch_v3_position_snapshot(BurnWeb3(), MANAGER, 1, to_block=100)
    assert result.burned_count == 1
    assert result.active_position_count == 0
    assert result.positions[0].custody_status == "burned"


def test_v3_owner_event_mismatch_fails_closed():
    class MismatchFunctions(FakeFunctions):
        def ownerOf(self, token_id):
            return FakeFunction(WALLET)
    class MismatchContract:
        functions = MismatchFunctions()
    class MismatchEth(FakeEth):
        def contract(self, address, abi):
            return MismatchContract()
    class MismatchWeb3(FakeWeb3):
        eth = MismatchEth()
    with pytest.raises(RuntimeError, match="ownerOf/event owner mismatch"):
        fetch_v3_position_snapshot(MismatchWeb3(), MANAGER, 1, to_block=100)


def test_v3_wrong_chain_is_rejected():
    class WrongEth(FakeEth):
        chain_id = 5
    class WrongWeb3(FakeWeb3):
        eth = WrongEth()
    with pytest.raises(ValueError, match="chain_id=1"):
        fetch_v3_position_snapshot(WrongWeb3(), MANAGER, 1, to_block=100)


def test_locker_registry_checks_chain_and_selector_shape(tmp_path):
    path = tmp_path / "lockers.json"
    path.write_text('{"chain_id": 1, "lockers": [{"address": "' + LOCKER +
                    '", "expected_code_hash": "' + "0x" + "ab" * 32 +
                    '", "is_locked_selector": "0x12345678", "unlock_time_selector": "0x87654321"}]}')
    rows = load_locker_registry(str(path), 1, lambda value: value.lower())
    assert len(rows) == 1
    with pytest.raises(ValueError, match="chain_id"):
        load_locker_registry(str(path), 5, lambda value: value.lower())

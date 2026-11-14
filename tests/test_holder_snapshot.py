from types import SimpleNamespace

import pytest

from holder_snapshot import TRANSFER_TOPIC, fetch_erc20_holder_snapshot


TOKEN = "0x" + "aa" * 20
WALLET_A = "0x" + "11" * 20
WALLET_B = "0x" + "22" * 20


def topic(address):
    return "0x" + ("0" * 24) + address[2:].lower()


class FakeCall:
    def __init__(self, value):
        self.value = value

    def call(self, block_identifier=None):
        assert block_identifier == 100
        return self.value


class FakeFunctions:
    def totalSupply(self):
        return FakeCall(1000)

    def balanceOf(self, address):
        return FakeCall({WALLET_A: 700, WALLET_B: 300}[address])


class FakeContract:
    functions = FakeFunctions()


class FakeEth:
    chain_id = 1
    block_number = 100

    def contract(self, address, abi):
        return FakeContract()

    def get_block(self, number):
        return {"hash": "0x" + "ab" * 32, "timestamp": 1_800_000_000}

    def get_code(self, address, block_identifier=None):
        return b""

    def get_logs(self, query):
        assert query["topics"] == [TRANSFER_TOPIC]
        return [{
            "topics": [TRANSFER_TOPIC, topic(WALLET_A), topic(WALLET_B)],
        }]


class FakeWeb3:
    eth = FakeEth()

    @staticmethod
    def to_checksum_address(address):
        return address.lower()


def test_holder_snapshot_reads_logs_and_reconciles_balances():
    result = fetch_erc20_holder_snapshot(
        FakeWeb3(), TOKEN, 90, to_block=100, chunk_size=5
    )
    assert result.chain_id == 1
    assert result.complete is True
    assert result.holder_count == 2
    assert result.transfer_log_count == 1
    assert result.report.status == "complete"
    assert result.report.top10_share_total_supply_pct == 100


def test_snapshot_fails_closed_on_wrong_chain():
    class WrongChain(FakeWeb3):
        class eth(FakeEth):
            chain_id = 5

    with pytest.raises(ValueError, match="chain_id=1"):
        fetch_erc20_holder_snapshot(WrongChain(), TOKEN, 90)


def test_snapshot_rejects_invalid_range():
    with pytest.raises(ValueError, match="Invalid snapshot block range"):
        fetch_erc20_holder_snapshot(FakeWeb3(), TOKEN, 110, to_block=100)


def test_snapshot_marks_supply_mismatch_incomplete():
    class MismatchEth(FakeEth):
        def contract(self, address, abi):
            class Functions:
                def totalSupply(self):
                    return FakeCall(999)
                def balanceOf(self, address):
                    return FakeCall({WALLET_A: 700, WALLET_B: 300}[address])
            return SimpleNamespace(functions=Functions())

    class MismatchWeb3(FakeWeb3):
        eth = MismatchEth()

    result = fetch_erc20_holder_snapshot(MismatchWeb3(), TOKEN, 90, to_block=100)
    assert result.complete is False
    assert result.report.status == "unknown"
    assert "holder_balances_do_not_reconcile_to_total_supply" in result.warnings


def test_log_fetch_reduces_range_after_provider_limit():
    class LimitedEth(FakeEth):
        calls = 0
        def get_logs(self, query):
            self.calls += 1
            if query["toBlock"] - query["fromBlock"] + 1 > 2:
                raise RuntimeError("provider range limit")
            return super().get_logs(query)

    class LimitedWeb3(FakeWeb3):
        eth = LimitedEth()

    result = fetch_erc20_holder_snapshot(
        LimitedWeb3(), TOKEN, 90, to_block=100, chunk_size=8
    )
    assert result.complete is True
    assert LimitedWeb3.eth.calls > 1

def test_snapshot_marks_reorg_during_read_incomplete():
    class ReorgEth(FakeEth):
        block_reads = 0
        def get_block(self, number):
            self.block_reads += 1
            marker = "ab" if self.block_reads == 1 else "cd"
            return {"hash": "0x" + marker * 32, "timestamp": 1_800_000_000}

    class ReorgWeb3(FakeWeb3):
        eth = ReorgEth()

    result = fetch_erc20_holder_snapshot(ReorgWeb3(), TOKEN, 90, to_block=100)
    assert result.complete is False
    assert result.report.status == "unknown"
    assert "snapshot_block_reorged_during_read" in result.warnings


def test_zero_balance_transfer_participants_are_not_reported_as_holders():
    class ZeroBalanceEth(FakeEth):
        def contract(self, address, abi):
            class Functions:
                def totalSupply(self):
                    return FakeCall(700)
                def balanceOf(self, address):
                    return FakeCall(700 if address == WALLET_A else 0)
            return SimpleNamespace(functions=Functions())

    class ZeroBalanceWeb3(FakeWeb3):
        eth = ZeroBalanceEth()

    result = fetch_erc20_holder_snapshot(ZeroBalanceWeb3(), TOKEN, 90, to_block=100)
    assert result.complete is False
    assert result.holder_count == 2

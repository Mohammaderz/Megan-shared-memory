from lp_analysis import LPHolder, VerifiedLock, classify_lp_supply


LOCKER = "0x" + "aa" * 20
EOA = "0x" + "bb" * 20
BURN = "0x000000000000000000000000000000000000dead"
NOW = 1_800_000_000


def test_verified_lock_and_eoa_balance_are_separated():
    result = classify_lp_supply(
        1000,
        [LPHolder(LOCKER, 500, "contract"), LPHolder(EOA, 400, "eoa"),
         LPHolder(BURN, 100, "burn")],
        [VerifiedLock(LOCKER, 500, NOW + 86400, True)],
        holders_complete=True, locks_complete=True, snapshot_timestamp=NOW,
    )
    assert result.status == "mixed"
    assert result.locked_share_pct == 50
    assert result.unlocked_share_pct == 40
    assert result.burned_share_pct == 10
    assert result.unknown_share_pct == 0


def test_contract_custody_without_verified_lock_is_unknown_not_unlocked():
    result = classify_lp_supply(
        1000,
        [LPHolder(LOCKER, 700, "contract"), LPHolder(EOA, 300, "eoa")],
        [],
        holders_complete=True, locks_complete=True, snapshot_timestamp=NOW,
    )
    assert result.status == "unknown"
    assert result.locked_share_pct == 0
    assert result.unlocked_share_pct == 30
    assert result.unknown_share_pct == 70


def test_expired_lock_is_unlocked():
    result = classify_lp_supply(
        100,
        [LPHolder(LOCKER, 100, "contract")],
        [VerifiedLock(LOCKER, 100, NOW - 1, True)],
        holders_complete=True, locks_complete=True, snapshot_timestamp=NOW,
    )
    assert result.status == "unlocked"
    assert result.locked_share_pct == 0
    assert result.unlocked_share_pct == 100


def test_incomplete_holder_or_locker_data_returns_unknown():
    holders = [LPHolder(EOA, 100, "eoa")]
    incomplete_holders = classify_lp_supply(
        100, holders, [], holders_complete=False, locks_complete=True,
        snapshot_timestamp=NOW,
    )
    incomplete_locks = classify_lp_supply(
        100, holders, [], holders_complete=True, locks_complete=False,
        snapshot_timestamp=NOW,
    )
    assert incomplete_holders.status == "unknown"
    assert incomplete_holders.locked_share_pct is None
    assert incomplete_locks.status == "unknown"
    assert incomplete_locks.unlocked_share_pct is None


def test_lock_amount_cannot_exceed_observed_locker_balance():
    result = classify_lp_supply(
        100,
        [LPHolder(LOCKER, 50, "contract"), LPHolder(EOA, 50, "eoa")],
        [VerifiedLock(LOCKER, 60, NOW + 100, True)],
        holders_complete=True, locks_complete=True, snapshot_timestamp=NOW,
    )
    assert result.status == "unknown"
    assert "lock_amount_exceeds_locker_balance" in result.warnings


def test_unverified_lock_is_never_counted_as_locked():
    result = classify_lp_supply(
        100, [LPHolder(LOCKER, 100, "contract")],
        [VerifiedLock(LOCKER, 100, NOW + 100, False)],
        holders_complete=True, locks_complete=True, snapshot_timestamp=NOW,
    )
    assert result.status == "unknown"
    assert result.locked_share_pct is None

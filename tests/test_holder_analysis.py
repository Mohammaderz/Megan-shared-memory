from holder_analysis import HolderBalance, analyze_holders


DEPLOYER = "0x" + "11" * 20
PAIR = "0x" + "22" * 20
BURN = "0x000000000000000000000000000000000000dead"
LOCKER = "0x" + "33" * 20
WALLET_A = "0x" + "44" * 20
WALLET_B = "0x" + "55" * 20


def test_top10_concentration_excludes_verified_non_circulating_roles():
    result = analyze_holders(
        1000,
        [
            HolderBalance(DEPLOYER, 200, "eoa"),
            HolderBalance(PAIR, 300, "lp_pair"),
            HolderBalance(BURN, 100, "burn"),
            HolderBalance(LOCKER, 100, "verified_locker"),
            HolderBalance(WALLET_A, 200, "eoa"),
            HolderBalance(WALLET_B, 100, "eoa"),
        ],
        snapshot_complete=True,
        deployer_address=DEPLOYER,
    )
    assert result.status == "complete"
    assert result.circulating_supply_raw == 500
    assert result.top10_share_circulating_pct == 100
    assert result.top10_share_total_supply_pct == 50
    assert result.deployer_share_total_supply_pct == 20


def test_incomplete_or_unreconciled_holder_snapshot_is_unknown():
    incomplete = analyze_holders(
        100, [HolderBalance(WALLET_A, 60, "eoa")], snapshot_complete=False
    )
    mismatch = analyze_holders(
        100, [HolderBalance(WALLET_A, 60, "eoa")], snapshot_complete=True
    )
    assert incomplete.status == "unknown"
    assert mismatch.status == "unknown"
    assert incomplete.top10_share_circulating_pct is None


def test_unverified_role_is_not_silently_excluded():
    result = analyze_holders(
        100,
        [HolderBalance(WALLET_A, 100, "suspected_locker")],
        snapshot_complete=True,
    )
    assert result.status == "unknown"
    assert "unverified_holder_role" in result.warnings


def test_deployer_missing_from_complete_snapshot_is_explicit():
    result = analyze_holders(
        100, [HolderBalance(WALLET_A, 100, "eoa")],
        snapshot_complete=True, deployer_address=DEPLOYER,
    )
    assert result.status == "complete"
    assert result.deployer_share_total_supply_pct is None
    assert "deployer_not_found_in_complete_holder_snapshot" in result.warnings

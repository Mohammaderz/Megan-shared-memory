from social_discovery import collect_social_evidence

ADDRESS = "0x" + "ab" * 20


def test_dexscreener_requires_exact_ethereum_contract_match():
    profiles = [
        {"chainId": "ethereum", "tokenAddress": ADDRESS,
         "links": [{"type": "telegram", "url": "https://t.me/example_group"}]},
        {"chainId": "base", "tokenAddress": ADDRESS,
         "links": [{"type": "twitter", "url": "https://x.com/wrong_chain"}]},
        {"chainId": "ethereum", "tokenAddress": "0x" + "cd" * 20,
         "links": [{"type": "twitter", "url": "https://x.com/wrong_token"}]},
    ]
    result = collect_social_evidence(ADDRESS, profiles)
    assert result["provider_profile_matches"] == 1
    assert result["links"][0]["platform"] == "telegram"
    assert result["links"][0]["source"] == "dexscreener"
    assert result["links"][0]["official_verified"] is False


def test_dextools_social_info_is_normalized():
    result = collect_social_evidence(ADDRESS, dextools_token={
        "socialInfo": {
            "telegram": "https://t.me/token_group",
            "twitter": "https://twitter.com/token_x",
            "website": "https://token.example",
        }
    })
    by_platform = {row["platform"]: row for row in result["links"]}
    assert set(by_platform) == {"telegram", "x", "website"}
    assert by_platform["x"]["source"] == "dextools"


def test_x_mentions_must_contain_exact_contract_address():
    posts = [
        {"id": "123", "text": f"New token {ADDRESS}", "author_id": "7"},
        {"id": "456", "text": "A different token"},
        {"id": "789", "text": f"lowercase {ADDRESS.lower()}"},
    ]
    result = collect_social_evidence(ADDRESS, x_posts=posts)
    assert [row["post_id"] for row in result["x_mentions"]] == ["123", "789"]


def test_absence_of_social_links_is_not_a_safety_signal():
    result = collect_social_evidence(ADDRESS, [], {}, [])
    assert result["overall_status"] == "no_public_evidence_found"
    assert result["telegram_status"] == "no_provider_link_found"
    assert result["x_status"] == "searched_no_exact_mentions"


def test_non_https_social_links_are_ignored():
    result = collect_social_evidence(ADDRESS, [{
        "chainId": "ethereum", "tokenAddress": ADDRESS,
        "links": [{"type": "telegram", "url": "http://t.me/insecure"}],
    }])
    assert result["links"] == []

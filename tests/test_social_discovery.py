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



def test_telegram_group_search_results_are_not_mistaken_for_official_links():
    groups = [{
        "chat_id": "42", "title": "Token discussion",
        "username": "token_discussion",
        "url": "https://t.me/token_discussion",
        "source": "telegram_mtproto_groups_only",
        "evidence": "exact_contract_address_mention",
        "official_verified": False,
    }]
    result = collect_social_evidence(ADDRESS, telegram_groups=groups)
    assert result["telegram_status"] == "group_found_by_account_search"
    assert result["telegram_groups"][0]["url"] == "https://t.me/token_discussion"
    assert result["overall_status"] == "evidence_found"



def test_telegram_mtproto_search_uses_groups_only_and_returns_exact_mentions(monkeypatch):
    import sys
    from datetime import datetime, timezone
    from types import ModuleType, SimpleNamespace

    captured = {}
    chat = SimpleNamespace(id=77, title="Launch group", username="launch_group", broadcast=False)
    message = SimpleNamespace(
        message=f"Contract: {ADDRESS}",
        peer_id=SimpleNamespace(channel_id=77),
        id=123,
        date=datetime.now(timezone.utc),
    )

    class FakeClient:
        def __init__(self, session, api_id, api_hash):
            captured["session"] = session
            captured["api_id"] = api_id
        async def connect(self):
            return None
        async def is_user_authorized(self):
            return True
        async def __call__(self, request):
            captured["request"] = request
            return SimpleNamespace(chats=[chat], messages=[message])
        async def get_messages(self, chat, limit=100):
            service = SimpleNamespace(
                action=SimpleNamespace(users=[99]), id=124,
                date=datetime.now(timezone.utc),
            )
            return [service]
        async def get_entity(self, user_id):
            return SimpleNamespace(id=user_id, username="helper_bot", bot=True)
        async def get_participants(self, chat, limit=100):
            return [SimpleNamespace(id=99, username="helper_bot", bot=True)]
        async def disconnect(self):
            return None

    module = ModuleType("telethon")
    module.TelegramClient = FakeClient
    module.functions = SimpleNamespace(messages=SimpleNamespace(
        SearchGlobalRequest=lambda **kwargs: kwargs
    ))
    module.types = SimpleNamespace(
        InputMessagesFilterEmpty=lambda: object(),
        InputPeerEmpty=lambda: object(),
    )
    monkeypatch.setitem(sys.modules, "telethon", module)

    from social_discovery import search_telegram_groups
    result = search_telegram_groups(ADDRESS, 1234, "api-hash", "data/test-session")

    assert captured["request"]["groups_only"] is True
    assert captured["session"] == "data/test-session"
    assert result[0]["url"] == "https://t.me/launch_group"
    assert result[0]["official_verified"] is False
    assert result[0]["bot_added_events"][0]["username"] == "helper_bot"
    assert result[0]["bot_accounts_observed"][0]["username"] == "helper_bot"

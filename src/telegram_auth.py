"""Authenticate a local Telegram MTProto session for Megan's read-only group search."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv


async def _login(api_id: int, api_hash: str, session_file: str) -> None:
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise SystemExit("Install Telegram support first: pip install -e '.[telegram]'") from exc
    path = Path(session_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(path), api_id, api_hash)
    try:
        await client.start()
        me = await client.get_me()
        print(f"Telegram session authorized locally for account id {me.id}.")
        print(f"Session file: {path}.session")
        print("Do not upload or share this session file.")
    finally:
        await client.disconnect()


def main() -> int:
    load_dotenv()
    api_id = int(os.getenv("TELEGRAM_API_ID", "0") or 0)
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    session_file = os.getenv("TELEGRAM_SESSION_FILE", "data/telegram_user").strip()
    if api_id <= 0 or not api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in your local .env file")
    asyncio.run(_login(api_id, api_hash, session_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

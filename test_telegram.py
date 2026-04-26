"""One-off check that TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID work."""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "message",
        nargs="*",
        default=None,
        help="optional message (default: short test string)",
    )
    args = parser.parse_args()
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment or .env", file=sys.stderr)
        sys.exit(1)

    text = " ".join(args.message) if args.message else "hermes-bot: Telegram test message OK"
    from alerts import send_alert

    await send_alert(text)
    print("Sent.")


if __name__ == "__main__":
    asyncio.run(main())

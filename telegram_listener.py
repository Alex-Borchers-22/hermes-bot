"""
Telegram command handlers (runs alongside market monitors).

Commands:
  /update — portfolio summary + each open position (marks when live prices exist).
  /help   — list commands

Only TELEGRAM_CHAT_ID may trigger commands (same as alerts).
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from summary import portfolio_summary_message

load_dotenv()


def _chat_allowed(update: Update) -> bool:
    expected = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    if not update.effective_chat:
        return False
    return str(update.effective_chat.id) == expected


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_lookup = context.application.bot_data["price_lookup"]
    if not _chat_allowed(update):
        if update.message:
            await update.message.reply_text("Unauthorized.")
        return
    msg = await portfolio_summary_message(price_lookup)
    if update.message:
        await update.message.reply_text(msg)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        if update.message:
            await update.message.reply_text("Unauthorized.")
        return
    if update.message:
        await update.message.reply_text(
            "Hermes commands:\n"
            "/update — portfolio value, P/L, cash, open position count\n"
            "/help — this message"
        )


async def run_telegram_listener(price_lookup) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return

    application = (
        Application.builder()
        .token(token)
        .build()
    )
    application.bot_data["price_lookup"] = price_lookup

    application.add_handler(CommandHandler("update", cmd_update))
    application.add_handler(CommandHandler("help", cmd_help))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    try:
        await asyncio.Event().wait()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

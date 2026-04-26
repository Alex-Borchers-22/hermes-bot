import os
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


async def send_alert(message: str):
    await bot.send_message(chat_id=CHAT_ID, text=message)
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")


dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "🎮 Привет!\n\n"
        "Я помогу найти игру по:\n"
        "📷 скриншоту\n"
        "📝 описанию\n"
        "🎥 видео\n\n"
        "Попробуй отправить скрин 👀"
    )


async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

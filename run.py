import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import settings
from bot.handlers import setup_routers


logging.basicConfig(level=logging.INFO)


async def main():
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )

    dp = Dispatcher()

    dp.include_router(setup_routers())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

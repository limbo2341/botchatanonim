from aiogram import Router
from aiogram.types import Message

from services.game_search_service import GameSearchService

router = Router()

game_service = GameSearchService()


@router.message()
async def search_game(message: Message):
    await message.answer("🔍 Ищу игру...")

    try:
        games = await game_service.search_game(
            message.text
        )

        if not games:
            await message.answer(
                "😔 Не смог найти игру.\n"
                "Попробуй описать подробнее."
            )
            return

        text = "🎮 <b>Похожие игры:</b>\n\n"

        for game in games:
            name = game.get("name", "Неизвестно")
            rating = game.get("rating", "Нет")
            released = game.get("released", "Неизвестно")

            text += (
                f"🎯 <b>{name}</b>\n"
                f"⭐ Рейтинг: {rating}\n"
                f"📅 Год: {released}\n\n"
            )

        await message.answer(text)

    except Exception as e:
        await message.answer(
            "❌ Ошибка поиска игры"
        )
        print(e)

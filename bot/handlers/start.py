from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def start_command(message: Message):
    await message.answer(
        "🎮 <b>ИгроПамять</b>\n\n"
        "Я помогу найти игру по памяти.\n\n"
        "📝 Опиши игру\n"
        "📷 Или отправь скриншот\n\n"
        "Пример:\n"
        "<i>игра где пустыня и машины</i>"
    )

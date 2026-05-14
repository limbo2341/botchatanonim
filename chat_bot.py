import asyncio
import asyncpg
import logging
import os
import random
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

TOKEN = "8784182805:AAGk8Tw2Kan-Yj-Jxq_YujXqCMFcKYUWp-M"
ADMINS = [8528807150, 7245932902, 8784182805]
DATABASE_URL = os.environ.get("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
pool: asyncpg.Pool = None

JOKES = [
    "Почему программисты не любят природу? Слишком много багов 🐛",
    "— Ты спишь? — Нет. — Тогда пошли гулять! — Сплю 😴",
    "Оптимист видит стакан наполовину полным. Пессимист — наполовину пустым. Программист — что стакан в два раза больше, чем нужно 🖥",
    "Жизнь коротка. Улыбайся, пока не кончились зубы 😁",
    "— Как дела? — Как у Wi-Fi в подвале 📶",
    "Мозг — удивительный орган. Работает с рождения и до момента, когда ты влюбляешься ❤️",
    "Я не ленивый, я просто в режиме энергосбережения 🔋",
    "— Сколько программистов нужно, чтобы вкрутить лампочку? — Ни одного, это проблема железа 💡",
]
FACTS = [
    "🐙 Осьминоги имеют три сердца и синюю кровь.",
    "🍯 Мёд никогда не портится — в египетских пирамидах нашли мёду 3000 лет, он был съедобным.",
    "🦷 Акулы — единственные животные, которые практически не болеют раком.",
    "🌙 На Луне следы астронавтов сохранятся ещё 100 миллионов лет.",
    "🐘 Слоны — единственные животные, которые не умеют прыгать.",
    "🧠 Мозг человека активнее ночью, чем днём.",
    "🐟 Рыбы-клоуны могут менять пол: все они рождаются самцами.",
    "⚡ Молния ударяет в Землю около 100 раз в секунду.",
]
COMPLIMENTS = [
    "Ты невероятно интересный собеседник! 🌟",
    "У тебя отличное чувство юмора 😄",
    "Ты очень умный человек 🧠",
    "Общаться с тобой — одно удовольствие ☀️",
    "Ты делаешь этот чат лучше своим присутствием 💫",
    "У тебя прекрасная душа ❤️",
    "Ты точно особенный человек ✨",
    "Твои мысли всегда интересны 🎯",
]
TRUTHS = [
    "Признайся: ты когда-нибудь притворялся спящим, чтобы не отвечать на звонок? 📱",
    "Какая твоя самая странная привычка? 🤔",
    "Что ты никогда не делал, но очень хочешь попробовать? 🌍",
    "Признайся в чём-то, чего никто не знает о тебе 🤫",
    "Что тебя больше всего раздражает в людях? 😤",
    "Какой твой самый большой страх? 😨",
    "Какую ложь ты говоришь чаще всего? 🤥",
]
DARES = [
    "Напиши случайному контакту: 'Я всё знаю' 😏",
    "Отправь голосовое и спой первые строчки любой песни 🎤",
    "Напиши 5 вещей, за которые благодарен прямо сейчас 🙏",
    "Расскажи самый смешной случай из своей жизни 😂",
    "Опиши свой идеальный день 🌅",
]

AD_PATTERNS = [
    r"t\.me/[a-zA-Z0-9_+]+",
    r"telegram\.me/[a-zA-Z0-9_+]+",
    r"@[a-zA-Z0-9_]{5,}",
    r"https?://t\.me",
    r"https?://telegram",
    r"tg://resolve\?domain=",
]

def is_ad_message(text: str) -> bool:
    if not text:
        return False
    for pattern in AD_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

# ================================================================
# СОСТОЯНИЯ
# ================================================================
class States(StatesGroup):
    broadcasting        = State()
    broadcast_photo     = State()
    giving_prem_id      = State()
    wait_proof          = State()
    admin_reply         = State()
    admin_ban_input     = State()
    admin_mute_input    = State()
    admin_unban_id      = State()
    admin_unmute_id     = State()
    admin_warn_input    = State()
    admin_unwarn_input  = State()
    admin_msg_user      = State()
    admin_lookup_user   = State()
    admin_reset_warns   = State()
    admin_revoke_prem   = State()
    user_tech_support   = State()
    add_ad_channel      = State()

# ================================================================
# БАЗА ДАННЫХ
# ================================================================
async def db_exec(sql, params=(), fetch="none"):
    async with pool.acquire() as conn:
        if fetch == "one":
            return await conn.fetchrow(sql, *params)
        elif fetch == "all":
            return await conn.fetch(sql, *params)
        else:
            await conn.execute(sql, *params)

async def init_db():
    await db_exec("""CREATE TABLE IF NOT EXISTS users (
        id           BIGINT PRIMARY KEY,
        username     TEXT,
        refs         INTEGER DEFAULT 0,
        prem_until   TIMESTAMP,
        gender       TEXT,
        age          TEXT,
        banned_until TIMESTAMP,
        muted_until  TIMESTAMP,
        warns        INTEGER DEFAULT 0
    )""")
    await db_exec("""CREATE TABLE IF NOT EXISTS reports (
        id           SERIAL PRIMARY KEY,
        reporter_id  BIGINT,
        target_id    BIGINT,
        last_message TEXT,
        created_at   TIMESTAMP DEFAULT NOW()
    )""")
    await db_exec("""CREATE TABLE IF NOT EXISTS ad_channels (
        id    SERIAL PRIMARY KEY,
        url   TEXT NOT NULL,
        title TEXT
    )""")

# ================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ================================================================
async def is_prem(uid):
    if uid in ADMINS:
        return True
    r = await db_exec("SELECT prem_until FROM users WHERE id=$1", (uid,), "one")
    return bool(r and r['prem_until'] and r['prem_until'] > datetime.now())

async def is_banned(uid):
    if uid in ADMINS:
        return False, None
    r = await db_exec("SELECT banned_until FROM users WHERE id=$1", (uid,), "one")
    if r and r['banned_until'] and r['banned_until'] > datetime.now():
        return True, r['banned_until'].strftime("%d.%m.%Y %H:%M")
    if r and r['banned_until']:
        await db_exec("UPDATE users SET banned_until=NULL WHERE id=$1", (uid,))
    return False, None

async def is_muted(uid):
    if uid in ADMINS:
        return False, None
    r = await db_exec("SELECT muted_until FROM users WHERE id=$1", (uid,), "one")
    if r and r['muted_until'] and r['muted_until'] > datetime.now():
        return True, r['muted_until'].strftime("%d.%m.%Y %H:%M")
    if r and r['muted_until']:
        await db_exec("UPDATE users SET muted_until=NULL WHERE id=$1", (uid,))
    return False, None

async def get_warns(uid):
    r = await db_exec("SELECT warns FROM users WHERE id=$1", (uid,), "one")
    return r['warns'] if r and r['warns'] else 0

async def get_rank(uid):
    if uid in ADMINS:
        return "👑 Администратор"
    if await is_prem(uid):
        return "💎 Premium"
    return "👤 Пользователь"

async def get_user_info_full(uid):
    r = await db_exec("SELECT username,gender,age FROM users WHERE id=$1", (uid,), "one")
    if not r:
        return f"ID: `{uid}`\nИнфо не найдено"
    gender_str = {"М": "👨 Мужской", "Ж": "👩 Женский"}.get(r['gender'], "—")
    rank = await get_rank(uid)
    warns = await get_warns(uid)
    return (
        f"🆔 ID: `{uid}`\n"
        f"👤 Ник: @{r['username'] or '—'}\n"
        f"🚻 Пол: {gender_str}\n"
        f"🎂 Возраст: {r['age'] or '—'}\n"
        f"🎖 Ранг: {rank}\n"
        f"⚠️ Варнов: {warns}/3"
    )

async def get_basic_card(uid):
    r = await db_exec("SELECT username,gender,age FROM users WHERE id=$1", (uid,), "one")
    if not r:
        return f"ID: `{uid}`"
    gender_str = {"М": "👨 Мужской", "Ж": "👩 Женский"}.get(r['gender'], "—")
    return (
        f"🆔 ID: `{uid}`\n"
        f"👤 Ник: @{r['username'] or '—'}\n"
        f"🚻 Пол: {gender_str}\n"
        f"🎂 Возраст: {r['age'] or '—'}"
    )

async def do_warn(tid):
    """Выдаёт варн. Возвращает (warns, banned)"""
    await db_exec("UPDATE users SET warns=COALESCE(warns,0)+1 WHERE id=$1", (tid,))
    warns = await get_warns(tid)
    banned = False
    if warns >= 3:
        until = datetime.now() + timedelta(days=3)
        await db_exec("UPDATE users SET banned_until=$1, warns=0 WHERE id=$2", (until, tid))
        if tid in active_chats:
            pid = active_chats.pop(tid)
            active_chats.pop(pid, None)
            try:
                await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
            except:
                pass
        try:
            await bot.send_message(
                tid,
                f"🚫 *3 предупреждения — автобан на 3 дня!*\n"
                f"Разблокировка: {until.strftime('%d.%m.%Y %H:%M')}",
                parse_mode="Markdown"
            )
        except:
            pass
        banned = True
    else:
        try:
            await bot.send_message(
                tid,
                f"⚠️ *Предупреждение от администрации!*\nВарнов: *{warns}/3*. При 3 — бан на 3 дня.",
                parse_mode="Markdown"
            )
        except:
            pass
    return warns, banned

# ================================================================
# РЕКЛАМНЫЕ КАНАЛЫ
# ================================================================
async def get_ad_channels():
    return await db_exec("SELECT id,url,title FROM ad_channels ORDER BY id", fetch="all")

async def check_user_subscribed(uid, channel_url):
    try:
        username = "@" + channel_url.strip().split("/")[-1].lstrip("@")
        member = await bot.get_chat_member(username, uid)
        return member.status not in ("left", "kicked")
    except:
        return True

async def check_all_subscriptions(uid):
    channels = await get_ad_channels()
    if not channels:
        return []
    not_sub = []
    for ch in channels:
        if not await check_user_subscribed(uid, ch['url']):
            not_sub.append(ch)
    return not_sub

async def handle_ad_warn(uid: int, message: types.Message):
    await db_exec("UPDATE users SET warns=COALESCE(warns,0)+1 WHERE id=$1", (uid,))
    warns = await get_warns(uid)
    if warns >= 3:
        until = datetime.now() + timedelta(days=3)
        await db_exec("UPDATE users SET banned_until=$1, warns=0 WHERE id=$2", (until, uid))
        if uid in active_chats:
            pid = active_chats.pop(uid)
            active_chats.pop(pid, None)
            last_messages.pop(uid, None)
            last_messages.pop(pid, None)
            try:
                await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
            except:
                pass
        await message.answer(
            f"🚫 *Реклама запрещена! 3-й варн — автобан на 3 дня.*\n"
            f"Разблокировка: {until.strftime('%d.%m.%Y %H:%M')}",
            parse_mode="Markdown", reply_markup=main_kb(uid)
        )
    else:
        await message.answer(
            f"🚫 *Реклама запрещена в чате!*\n⚠️ Варн *{warns}/3*. При 3 — автобан.",
            parse_mode="Markdown"
        )

# ================================================================
# КЛАВИАТУРЫ
# ================================================================
def main_kb(uid):
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="🔎 Поиск"),
           types.KeyboardButton(text="🎭 По интересам"))
    kb.row(types.KeyboardButton(text="👤 Профиль"),
           types.KeyboardButton(text="💎 Реферал"))
    kb.row(types.KeyboardButton(text="👑 Купить Premium"),
           types.KeyboardButton(text="🏆 ТОП"))
    kb.row(types.KeyboardButton(text="🎲 Развлечения"),
           types.KeyboardButton(text="👨‍💻 Поддержка"))
    if uid in ADMINS:
        kb.row(types.KeyboardButton(text="⚙️ Админ Панель"))
    return kb.as_markup(resize_keyboard=True)

def chat_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="➡️ Следующий"),
           types.KeyboardButton(text="❌ Выйти"))
    kb.row(types.KeyboardButton(text="🚩 Пожаловаться"),
           types.KeyboardButton(text="👤 Поделиться юзом"))
    return kb.as_markup(resize_keyboard=True)

# ================================================================
# ОЧЕРЕДЬ ПОИСКА
# ================================================================
active_chats  = {}
last_messages = {}
queues = {
    "all": [], "М": [], "Ж": [], "Music": [], "Games": [],
    "Anime": [], "Code": [], "18+": [], "25+": [], "<18": [], "VIP": []
}

async def enter_queue(uid, cat):
    if uid in active_chats:
        return
    for k in queues:
        if uid in queues[k]:
            queues[k].remove(uid)
    if cat not in queues:
        queues[cat] = []
    lst = queues[cat]
    if lst:
        pid = lst.pop(0)
        if pid == uid:
            queues[cat].append(uid)
            return
        active_chats[uid] = pid
        active_chats[pid] = uid
        last_messages[uid] = None
        last_messages[pid] = None
        uid_card = await get_user_info_full(pid) if await is_prem(uid) else await get_basic_card(pid)
        pid_card = await get_user_info_full(uid) if await is_prem(pid) else await get_basic_card(uid)
        await bot.send_message(uid, f"🎁 *Собеседник найден!*\n\n{uid_card}", reply_markup=chat_kb(), parse_mode="Markdown")
        await bot.send_message(pid, f"🎁 *Собеседник найден!*\n\n{pid_card}", reply_markup=chat_kb(), parse_mode="Markdown")
    else:
        queues[cat].append(uid)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="stop_q")
        await bot.send_message(uid, f"⏳ Поиск в категории [{cat}]...", reply_markup=kb.as_markup())

# ================================================================
# КНОПКИ ЧАТА — StateFilter("*") чтобы работали при любом стейте
# ================================================================
@dp.message(StateFilter("*"), F.text == "❌ Выйти")
async def chat_exit(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    await state.clear()
    if uid in active_chats:
        pid = active_chats.pop(uid)
        active_chats.pop(pid, None)
        last_messages.pop(uid, None)
        last_messages.pop(pid, None)
        await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
        await message.answer("Вы вышли из чата.", reply_markup=main_kb(uid))
        return
    removed = False
    for k in queues:
        if uid in queues[k]:
            queues[k].remove(uid)
            removed = True
    if removed:
        await message.answer("❌ Поиск отменён.", reply_markup=main_kb(uid))
    else:
        await message.answer("Вы не в чате.", reply_markup=main_kb(uid))

@dp.message(StateFilter("*"), F.text == "➡️ Следующий")
async def chat_next(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    await state.clear()
    if uid in active_chats:
        pid = active_chats.pop(uid)
        active_chats.pop(pid, None)
        last_messages.pop(uid, None)
        last_messages.pop(pid, None)
        await bot.send_message(pid, "💔 Собеседник ушёл искать другого...", reply_markup=main_kb(pid))
        await enter_queue(uid, "all")
        return
    for k in queues:
        if uid in queues[k]:
            await message.answer("⏳ Вы уже в поиске. Нажмите ❌ Выйти для отмены.")
            return
    await enter_queue(uid, "all")

@dp.message(StateFilter("*"), F.text == "🚩 Пожаловаться")
async def chat_report(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in active_chats:
        await message.answer("❌ Вы не в чате.")
        return
    pid = active_chats[uid]
    last_msg = last_messages.get(pid) or "(нет сообщений)"
    await db_exec(
        "INSERT INTO reports (reporter_id,target_id,last_message) VALUES ($1,$2,$3)",
        (uid, pid, last_msg)
    )
    rep = await db_exec("SELECT id FROM reports ORDER BY id DESC LIMIT 1", fetch="one")
    rep_id = rep['id'] if rep else 0
    pid_info = await get_user_info_full(pid)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔨 Бан 3 дня",      callback_data=f"rban_3_{pid}_{rep_id}")
    kb.button(text="🔇 Мут 1 день",     callback_data=f"rmute_1_{pid}_{rep_id}")
    kb.button(text="⚠️ Предупреждение", callback_data=f"rwarn_{pid}_{rep_id}")
    kb.button(text="✅ Без наказания",   callback_data=f"rnoban_{pid}_{rep_id}")
    for adm in ADMINS:
        try:
            await bot.send_message(
                adm,
                f"🚩 *Новая жалоба!*\n\n*Нарушитель:*\n{pid_info}\n\n*Сообщение:*\n`{last_msg}`",
                reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown"
            )
        except:
            pass
    await message.answer("✅ Жалоба отправлена администрации!")

@dp.message(StateFilter("*"), F.text == "👤 Поделиться юзом")
async def share_username(message: types.Message):
    uid = message.from_user.id
    if uid not in active_chats:
        await message.answer("❌ Вы не в чате.")
        return
    pid = active_chats[uid]
    username = message.from_user.username
    text = f"👤 Собеседник поделился юзером:\n@{username}" if username else f"👤 Собеседник поделился ID:\n`{uid}`"
    try:
        await bot.send_message(pid, text, parse_mode="Markdown")
        await message.answer("✅ Юзернейм отправлен собеседнику!")
    except:
        await message.answer("❌ Не удалось отправить.")

# ================================================================
# /start
# ================================================================
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    uid  = message.from_user.id
    args = message.text.split()
    ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    existing = await db_exec("SELECT id FROM users WHERE id=$1", (uid,), "one")
    is_new = not existing
    if is_new:
        await db_exec(
            "INSERT INTO users (id,username,refs) VALUES ($1,$2,0) ON CONFLICT (id) DO NOTHING",
            (uid, message.from_user.username)
        )
        if ref_id and ref_id != uid:
            ref_exists = await db_exec("SELECT id FROM users WHERE id=$1", (ref_id,), "one")
            if ref_exists:
                await db_exec("UPDATE users SET refs=refs+1 WHERE id=$1", (ref_id,))
                u_refs = (await db_exec("SELECT refs FROM users WHERE id=$1", (ref_id,), "one"))['refs']
                try:
                    await bot.send_message(
                        ref_id,
                        f"🎉 По вашей ссылке зарегистрировался новый пользователь!\n👥 Рефералов: *{u_refs}*",
                        parse_mode="Markdown"
                    )
                except:
                    pass
                if u_refs % 10 == 0:
                    cur = await db_exec("SELECT prem_until FROM users WHERE id=$1", (ref_id,), "one")
                    base = datetime.now()
                    if cur and cur['prem_until'] and cur['prem_until'] > base:
                        base = cur['prem_until']
                    until = base + timedelta(days=2)
                    await db_exec("UPDATE users SET prem_until=$1 WHERE id=$2", (until, ref_id))
                    try:
                        await bot.send_message(ref_id, f"🏆 {u_refs} рефералов — *+2 дня Premium*!", parse_mode="Markdown")
                    except:
                        pass

    channels = await get_ad_channels()
    if channels and is_new:
        kb = InlineKeyboardBuilder()
        for ch in channels:
            kb.button(text=f"👉 {ch['title'] or ch['url']}", url=ch['url'])
        kb.button(text="✅ Я подписался!", callback_data="check_sub_reg")
        txt = "📢 *Для регистрации подпишись на каналы:*\n\n"
        for ch in channels:
            txt += f"• {ch['title'] or ch['url']}: {ch['url']}\n"
        txt += "\nПосле подписки нажми ✅"
        await message.answer(txt, reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown")
        return

    kb = InlineKeyboardBuilder()
    for a in ["< 18", "18+", "25+", "65+"]:
        kb.button(text=a, callback_data=f"set_age_{a}")
    await message.answer("👋 Добро пожаловать! Укажи свой возраст:", reply_markup=kb.adjust(2).as_markup())

@dp.callback_query(F.data == "check_sub_reg")
async def check_sub_reg(call: types.CallbackQuery):
    uid = call.from_user.id
    not_sub = await check_all_subscriptions(uid)
    if not_sub:
        kb = InlineKeyboardBuilder()
        for ch in not_sub:
            kb.button(text=f"👉 {ch['title'] or ch['url']}", url=ch['url'])
        kb.button(text="✅ Я подписался!", callback_data="check_sub_reg")
        await call.answer("❌ Ещё не подписан на все каналы!", show_alert=True)
        txt = "❌ *Не хватает подписки:*\n\n"
        for ch in not_sub:
            txt += f"• {ch['title'] or ch['url']}: {ch['url']}\n"
        await call.message.edit_text(txt + "\nПодпишись и нажми ✅", reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown")
        return
    kb = InlineKeyboardBuilder()
    for a in ["< 18", "18+", "25+", "65+"]:
        kb.button(text=a, callback_data=f"set_age_{a}")
    await call.message.edit_text("✅ Отлично! Укажи возраст:", reply_markup=kb.adjust(2).as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("set_age_"))
async def cb_age(call: types.CallbackQuery):
    await db_exec("UPDATE users SET age=$1 WHERE id=$2", (call.data[8:], call.from_user.id))
    kb = InlineKeyboardBuilder()
    kb.button(text="👨 Мужской", callback_data="set_sex_М")
    kb.button(text="👩 Женский", callback_data="set_sex_Ж")
    await call.message.edit_text("Выбери пол:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("set_sex_"))
async def cb_sex(call: types.CallbackQuery):
    await db_exec("UPDATE users SET gender=$1 WHERE id=$2", (call.data[8:], call.from_user.id))
    await call.message.answer("🎉 Регистрация завершена! Теперь ты можешь искать общение.", reply_markup=main_kb(call.from_user.id))
    await call.message.delete()

# ================================================================
# ГЛАВНОЕ МЕНЮ — StateFilter("*") чтобы работали при любом стейте
# ================================================================
@dp.message(StateFilter("*"), F.text == "👤 Профиль")
async def menu_profile(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        return
    await state.clear()
    banned, until = await is_banned(uid)
    if banned:
        await message.answer(f"🚫 Вы заблокированы до *{until}*.", parse_mode="Markdown")
        return
    u = await db_exec(
        "SELECT id,username,refs,prem_until,gender,age,warns FROM users WHERE id=$1", (uid,), "one"
    )
    if not u:
        await message.answer("Сначала пройди регистрацию через /start")
        return
    p_status = "✅ Активен" if await is_prem(uid) else "❌ Не активен"
    rank = await get_rank(uid)
    warns = u['warns'] or 0
    prem_until = u['prem_until']
    prem_date = prem_until.strftime('%d.%m.%Y') if prem_until and prem_until > datetime.now() else "—"
    gender_str = {"М": "👨 Мужской", "Ж": "👩 Женский"}.get(u['gender'], "—")
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Редактировать профиль", callback_data="edit_profile")
    await message.answer(
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👤 *ВАШ ПРОФИЛЬ*\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🆔 ID: `{uid}`\n"
        f"🎖 Ранг: {rank}\n"
        f"💎 Premium: {p_status}" + (f" (до {prem_date})" if prem_date != "—" else "") + "\n"
        f"🤝 Рефералов: {u['refs'] or 0}\n"
        f"🚻 Пол: {gender_str} | 🎂 Возраст: {u['age'] or '—'}\n"
        f"⚠️ Варнов: {warns}/3\n"
        f"➖➖➖➖➖➖➖➖➖➖",
        reply_markup=kb.as_markup(), parse_mode="Markdown"
    )

@dp.message(StateFilter("*"), F.text == "👨‍💻 Поддержка")
async def menu_support(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        return
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Написать в поддержку", callback_data="open_support")
    await message.answer(
        "👨‍💻 *Техническая поддержка*\n\n"
        "Нажмите кнопку и опишите проблему.\n"
        "Администраторы ответят в ближайшее время.",
        reply_markup=kb.as_markup(), parse_mode="Markdown"
    )

@dp.message(StateFilter("*"), F.text == "🔎 Поиск")
async def menu_search(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        return
    await state.clear()
    banned, until = await is_banned(uid)
    if banned:
        await message.answer(f"🚫 Вы заблокированы до *{until}*.", parse_mode="Markdown")
        return
    if await is_prem(uid):
        kb = InlineKeyboardBuilder()
        kb.button(text="Все",        callback_data="q_all")
        kb.button(text="Девушки 👩", callback_data="q_Ж")
        kb.button(text="Парни 👨",   callback_data="q_М")
        kb.button(text="До 18 лет",  callback_data="q_<18")
        kb.button(text="18+ лет",    callback_data="q_18+")
        kb.button(text="25+ лет",    callback_data="q_25+")
        kb.button(text="💎 VIP-чат", callback_data="q_VIP")
        await message.answer(
            "💎 *Premium Поиск*\nВыбери критерий:\n\n✨ *VIP-чат* — только для Premium!",
            reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown"
        )
    else:
        await enter_queue(uid, "all")

@dp.message(StateFilter("*"), F.text == "🏆 ТОП")
async def menu_top(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        return
    await state.clear()
    top = await db_exec("SELECT username,refs FROM users ORDER BY refs DESC LIMIT 10", fetch="all")
    medals = ["🥇", "🥈", "🥉"]
    txt = "🏆 *ТОП РЕФЕРАЛОВ*\n\n"
    for i, r in enumerate(top, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        txt += f"{medal} {r['username'] or 'User'} — {r['refs']} чел.\n"
    await message.answer(txt, parse_mode="Markdown")

@dp.message(StateFilter("*"), F.text == "💎 Реферал")
async def menu_referral(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        return
    await state.clear()
    me  = await bot.get_me()
    u   = await db_exec("SELECT refs FROM users WHERE id=$1", (uid,), "one")
    refs = u['refs'] if u else 0
    await message.answer(
        f"🎁 *Реферальная программа*\n\n"
        f"👥 Ты пригласил: *{refs}* человек\n"
        f"🔥 За каждые *10 приглашённых* — *2 дня Premium*!\n\n"
        f"🔗 Твоя ссылка:\n`https://t.me/{me.username}?start={uid}`",
        parse_mode="Markdown"
    )

@dp.message(StateFilter("*"), F.text == "👑 Купить Premium")
async def menu_buy_prem(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        return
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="1 день — 25 грн",    callback_data="buy_1")
    kb.button(text="30 дней — 100 грн",  callback_data="buy_30")
    kb.button(text="Навсегда — 200 грн", callback_data="buy_999")
    await message.answer(
        "💎 *Выбери тариф:*\n\n"
        "🎁 *Premium возможности:*\n"
        "• Поиск по полу и возрасту\n"
        "• Виден ранг и варны собеседника\n"
        "• 💎 VIP-чат — только среди Premium\n"
        "• Значок 💎 в профиле\n"
        "• Приоритет в поиске",
        reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown"
    )

@dp.message(StateFilter("*"), F.text == "🎭 По интересам")
async def interests_menu(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        return
    await state.clear()
    banned, until = await is_banned(uid)
    if banned:
        await message.answer(f"🚫 Вы заблокированы до *{until}*.", parse_mode="Markdown")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="🎵 Музыка",  callback_data="q_Music")
    kb.button(text="🎮 Игры",    callback_data="q_Games")
    kb.button(text="⛩ Аниме",   callback_data="q_Anime")
    kb.button(text="💻 Кодинг",  callback_data="q_Code")
    await message.answer("🎯 Выбери интерес для поиска:", reply_markup=kb.adjust(2).as_markup())

@dp.message(StateFilter("*"), F.text == "🎲 Развлечения")
async def fun_menu(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        return
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="😂 Анекдот",            callback_data="fun_joke")
    kb.button(text="🧠 Интересный факт",    callback_data="fun_fact")
    kb.button(text="🎱 Магический шар",     callback_data="fun_8ball")
    kb.button(text="🌸 Комплимент",         callback_data="fun_compliment")
    kb.button(text="🎯 Правда или Действие",callback_data="fun_tod")
    if await is_prem(uid):
        kb.button(text="💎 Гороскоп",        callback_data="fun_horoscope")
        kb.button(text="💎 Число удачи",     callback_data="fun_lucky")
    await message.answer(
        "🎲 *Развлечения*\nВыбери что-нибудь интересное:",
        reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown"
    )

@dp.message(StateFilter("*"), F.text == "⚙️ Админ Панель")
async def adm_panel(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Рассылка",          callback_data="adm_broad")
    kb.button(text="🖼 Рассылка с фото",   callback_data="adm_broad_photo")
    kb.button(text="🚩 Жалобы",            callback_data="adm_reps")
    kb.button(text="🎁 Выдать Прем",       callback_data="adm_give_manual")
    kb.button(text="📊 Статистика",        callback_data="a_stats")
    kb.button(text="🔨 Бан по ID/ник",     callback_data="adm_ban")
    kb.button(text="🔇 Мут по ID/ник",     callback_data="adm_mute")
    kb.button(text="🔓 Разбан по ID",      callback_data="adm_unban_id")
    kb.button(text="🔓 Разбан по нику",    callback_data="adm_unban_un")
    kb.button(text="🔊 Размут по ID",      callback_data="adm_unmute_id")
    kb.button(text="🔊 Размут по нику",    callback_data="adm_unmute_un")
    kb.button(text="⚠️ Варн по ID/ник",    callback_data="adm_warn")
    kb.button(text="🗑 Снять варн",         callback_data="adm_unwarn")
    kb.button(text="🔄 Сбросить варны",    callback_data="adm_reset_warns")
    kb.button(text="📋 Список банов",       callback_data="adm_banlist")
    kb.button(text="✉️ Сообщение юзеру",   callback_data="adm_msg_user")
    kb.button(text="🔍 Найти юзера",       callback_data="adm_lookup")
    kb.button(text="❌ Снять Прем",        callback_data="adm_revoke_prem")
    kb.button(text="📣 Реклама каналов",   callback_data="adm_ad_channels")
    await message.answer("🛠 *Панель администратора*", reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")

# ================================================================
# РАЗВЛЕЧЕНИЯ — колбэки
# ================================================================
@dp.callback_query(F.data == "fun_joke")
async def fun_joke(call: types.CallbackQuery):
    await call.message.answer(f"😂 {random.choice(JOKES)}")
    await call.answer()

@dp.callback_query(F.data == "fun_fact")
async def fun_fact_cb(call: types.CallbackQuery):
    await call.message.answer(f"🧠 *Интересный факт:*\n\n{random.choice(FACTS)}", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "fun_8ball")
async def fun_8ball(call: types.CallbackQuery):
    answers = [
        "🟢 Определённо да!", "🟢 Скорее всего да.", "🟢 Бесспорно!",
        "🟡 Не уверен...", "🟡 Попробуй снова.", "🟡 Пока непонятно.",
        "🔴 Нет.", "🔴 Скорее всего нет.", "🔴 Даже не думай об этом."
    ]
    await call.message.answer(f"🎱 *Магический шар:*\n\n{random.choice(answers)}", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "fun_compliment")
async def fun_compliment(call: types.CallbackQuery):
    await call.message.answer(f"🌸 *Комплимент дня:*\n\n{random.choice(COMPLIMENTS)}", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "fun_tod")
async def fun_tod(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 Правда",    callback_data="tod_truth")
    kb.button(text="💪 Действие", callback_data="tod_dare")
    await call.message.answer("🎮 *Правда или Действие?*", reply_markup=kb.as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "tod_truth")
async def tod_truth(call: types.CallbackQuery):
    await call.message.answer(f"🎯 *Правда:*\n\n{random.choice(TRUTHS)}", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "tod_dare")
async def tod_dare(call: types.CallbackQuery):
    await call.message.answer(f"💪 *Действие:*\n\n{random.choice(DARES)}", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "fun_horoscope")
async def fun_horoscope(call: types.CallbackQuery):
    if not await is_prem(call.from_user.id):
        await call.answer("💎 Только для Premium!", show_alert=True)
        return
    signs = ["♈ Овен", "♉ Телец", "♊ Близнецы", "♋ Рак", "♌ Лев", "♍ Дева",
             "♎ Весы", "♏ Скорпион", "♐ Стрелец", "♑ Козерог", "♒ Водолей", "♓ Рыбы"]
    moods = ["отличный", "хороший", "нейтральный", "переменный"]
    luck  = ["высокая", "средняя", "растёт к вечеру"]
    await call.message.answer(
        f"🔮 *Гороскоп на сегодня*\n\n"
        f"Знак: {random.choice(signs)}\n"
        f"😊 Настроение дня: {random.choice(moods)}\n"
        f"🍀 Удача: {random.choice(luck)}\n"
        f"🔢 Счастливое число: {random.randint(1,99)}\n\n"
        f"✨ _Звёзды говорят: сегодня хороший день для новых знакомств!_",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "fun_lucky")
async def fun_lucky(call: types.CallbackQuery):
    if not await is_prem(call.from_user.id):
        await call.answer("💎 Только для Premium!", show_alert=True)
        return
    color = random.choice(["🔴 Красный", "🔵 Синий", "🟢 Зелёный", "🟡 Жёлтый", "🟣 Фиолетовый"])
    await call.message.answer(
        f"🍀 *Твоё число удачи: {random.randint(1,100)}*\n\n"
        f"🎨 Счастливый цвет: {color}\n"
        f"⏰ Удачное время: {random.randint(10,22)}:00",
        parse_mode="Markdown"
    )
    await call.answer()

# ================================================================
# РЕДАКТИРОВАНИЕ ПРОФИЛЯ
# ================================================================
@dp.callback_query(F.data == "edit_profile")
async def edit_profile_cb(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🚻 Изменить пол",     callback_data="ep_gender")
    kb.button(text="🎂 Изменить возраст", callback_data="ep_age")
    await call.message.answer("⚙️ *Редактирование профиля*", reply_markup=kb.as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "ep_gender")
async def ep_gender(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="👨 Мужской", callback_data="epg_М")
    kb.button(text="👩 Женский", callback_data="epg_Ж")
    await call.message.edit_text("Выбери новый пол:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("epg_"))
async def ep_gender_set(call: types.CallbackQuery):
    gender = call.data[4:]
    await db_exec("UPDATE users SET gender=$1 WHERE id=$2", (gender, call.from_user.id))
    g_str = "👨 Мужской" if gender == "М" else "👩 Женский"
    await call.message.edit_text(f"✅ Пол изменён на {g_str}!")

@dp.callback_query(F.data == "ep_age")
async def ep_age(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    for a in ["< 18", "18+", "25+", "65+"]:
        kb.button(text=a, callback_data=f"epa_{a}")
    await call.message.edit_text("Выбери новый возраст:", reply_markup=kb.adjust(2).as_markup())

@dp.callback_query(F.data.startswith("epa_"))
async def ep_age_set(call: types.CallbackQuery):
    age = call.data[4:]
    await db_exec("UPDATE users SET age=$1 WHERE id=$2", (age, call.from_user.id))
    await call.message.edit_text(f"✅ Возраст изменён на {age}!")

# ================================================================
# ПОИСК CALLBACKS
# ================================================================
@dp.callback_query(F.data.startswith("q_"))
async def q_callback(call: types.CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    banned, until = await is_banned(uid)
    if banned:
        await call.answer(f"Вы заблокированы до {until}", show_alert=True)
        return
    cat = call.data[2:]
    if cat == "VIP" and not await is_prem(uid):
        await call.answer("💎 VIP только для Premium!", show_alert=True)
        return
    await state.clear()
    try:
        await call.message.delete()
    except:
        pass
    await enter_queue(uid, cat)

@dp.callback_query(F.data == "stop_q")
async def stop_q_cb(call: types.CallbackQuery):
    uid = call.from_user.id
    for k in queues:
        if uid in queues[k]:
            queues[k].remove(uid)
    try:
        await call.message.edit_text("❌ Поиск отменён.")
    except:
        pass
    await call.answer()

# ================================================================
# ПОКУПКА PREMIUM
# ================================================================
@dp.callback_query(F.data.startswith("buy_"))
async def buy_cb(call: types.CallbackQuery, state: FSMContext):
    days = call.data.split("_")[1]
    prices = {"1": "25 грн", "30": "100 грн", "999": "200 грн"}
    await state.update_data(chosen_days=days)
    await state.set_state(States.wait_proof)
    await call.message.edit_text(
        f"💳 Карта: `4874070057830877`\nСумма: *{prices.get(days, '?')}*\n\n"
        f"После оплаты отправьте скриншот чека 👇",
        parse_mode="Markdown"
    )

@dp.message(States.wait_proof, F.photo)
async def wait_proof_photo(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    days = data.get("chosen_days", "30")
    for a in ADMINS:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Подтвердить", callback_data=f"pay_yes_{uid}_{days}")
        kb.button(text="❌ Отказать",    callback_data=f"pay_no_{uid}")
        await bot.send_photo(
            a, message.photo[-1].file_id,
            caption=f"💳 Чек на *{days} дн.* от `{uid}`",
            reply_markup=kb.as_markup(), parse_mode="Markdown"
        )
    await message.answer("✅ Чек отправлен на проверку!")
    await state.clear()

@dp.callback_query(F.data.startswith("pay_"))
async def pay_adm(call: types.CallbackQuery):
    p = call.data.split("_")
    action, target_id = p[1], int(p[2])
    days = int(p[3]) if len(p) > 3 else 30
    if action == "yes":
        if days == 999:
            until = datetime.now() + timedelta(days=36500)
            msg = "💎 *Premium активирован навсегда!*"
        else:
            cur = await db_exec("SELECT prem_until FROM users WHERE id=$1", (target_id,), "one")
            base = datetime.now()
            if cur and cur['prem_until'] and cur['prem_until'] > base:
                base = cur['prem_until']
            until = base + timedelta(days=days)
            msg = f"💎 *Premium на {days} дней!* До: {until.strftime('%d.%m.%Y')}"
        await db_exec("UPDATE users SET prem_until=$1 WHERE id=$2", (until, target_id))
        try:
            await bot.send_message(target_id, msg, parse_mode="Markdown")
        except:
            pass
        try:
            await call.message.edit_caption(caption=f"✅ Оплата подтверждена для {target_id}.")
        except:
            await call.message.edit_text(f"✅ Оплата подтверждена для {target_id}.")
    else:
        try:
            await bot.send_message(target_id, "❌ Оплата отклонена. Обратитесь в поддержку.")
        except:
            pass
        try:
            await call.message.edit_caption(caption=f"❌ Оплата отклонена для {target_id}.")
        except:
            await call.message.edit_text(f"❌ Оплата отклонена для {target_id}.")

# ================================================================
# ТЕХПОДДЕРЖКА
# ================================================================
@dp.callback_query(F.data == "open_support")
async def open_support_cb(call: types.CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    banned, until = await is_banned(uid)
    if banned:
        await call.answer(f"Заблокированы до {until}", show_alert=True)
        return
    await state.set_state(States.user_tech_support)
    await call.message.answer("📝 *Опишите вашу проблему:*", parse_mode="Markdown")
    await call.answer()

@dp.message(States.user_tech_support)
async def user_tech_support_msg(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    username = message.from_user.username or "—"
    text = message.text or "(без текста)"
    rank = await get_rank(uid)
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Ответить", callback_data=f"reply_{uid}")
    for adm in ADMINS:
        try:
            await bot.send_message(
                adm,
                f"📩 *Обращение в поддержку*\n\n"
                f"👤 @{username} | ID: `{uid}` | {rank}\n\n💬 {text}",
                reply_markup=kb.as_markup(), parse_mode="Markdown"
            )
        except:
            pass
    await message.answer("✅ Обращение отправлено! Ожидайте ответа.", parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data.startswith("reply_"))
async def adm_reply_start(call: types.CallbackQuery, state: FSMContext):
    target_id = call.data.split("_")[1]
    await state.update_data(rep_to=target_id)
    await call.message.answer(f"✏️ Пишите ответ для `{target_id}`:", parse_mode="Markdown")
    await state.set_state(States.admin_reply)
    await call.answer()

@dp.message(States.admin_reply)
async def adm_reply_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target = data.get("rep_to")
    try:
        await bot.send_message(int(target), f"📩 *Ответ от поддержки:*\n\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Ответ отправлен.")
    except:
        await message.answer("❌ Не удалось отправить.")
    await state.clear()

# ================================================================
# ЖАЛОБЫ — обработка кнопок
# ================================================================
@dp.callback_query(F.data.startswith("rban_"))
async def r_ban_cb(call: types.CallbackQuery):
    p = call.data.split("_")
    days, tid, rep_id = int(p[1]), int(p[2]), int(p[3])
    until = datetime.now() + timedelta(days=days)
    await db_exec("UPDATE users SET banned_until=$1 WHERE id=$2", (until, tid))
    if rep_id > 0:
        await db_exec("DELETE FROM reports WHERE id=$1", (rep_id,))
    if tid in active_chats:
        pid = active_chats.pop(tid)
        active_chats.pop(pid, None)
        try:
            await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
        except:
            pass
    try:
        await bot.send_message(tid, f"🔨 Вы заблокированы *на {days} дн.* за нарушение.", parse_mode="Markdown")
    except:
        pass
    try:
        await call.message.edit_text(f"✅ `{tid}` забанен на {days} дн.", parse_mode="Markdown")
    except:
        pass

@dp.callback_query(F.data.startswith("rmute_"))
async def r_mute_cb(call: types.CallbackQuery):
    p = call.data.split("_")
    days, tid, rep_id = int(p[1]), int(p[2]), int(p[3])
    until = datetime.now() + timedelta(days=days)
    await db_exec("UPDATE users SET muted_until=$1 WHERE id=$2", (until, tid))
    if rep_id > 0:
        await db_exec("DELETE FROM reports WHERE id=$1", (rep_id,))
    try:
        await bot.send_message(tid, f"🔇 Вы замучены *на {days} дн.*", parse_mode="Markdown")
    except:
        pass
    try:
        await call.message.edit_text(f"✅ `{tid}` замучен на {days} дн.", parse_mode="Markdown")
    except:
        pass

@dp.callback_query(F.data.startswith("rwarn_"))
async def r_warn_cb(call: types.CallbackQuery):
    p = call.data.split("_")
    tid, rep_id = int(p[1]), int(p[2])
    if rep_id > 0:
        await db_exec("DELETE FROM reports WHERE id=$1", (rep_id,))
    warns, banned = await do_warn(tid)
    try:
        if banned:
            await call.message.edit_text(f"🔨 `{tid}` — 3 варна, автобан 3 дня!", parse_mode="Markdown")
        else:
            await call.message.edit_text(f"✅ Варн выдан `{tid}`. Варнов: {warns}/3", parse_mode="Markdown")
    except:
        pass

@dp.callback_query(F.data.startswith("rnoban_"))
async def r_noban_cb(call: types.CallbackQuery):
    rep_id = int(call.data.split("_")[2])
    if rep_id > 0:
        await db_exec("DELETE FROM reports WHERE id=$1", (rep_id,))
    try:
        await call.message.edit_text("✅ Жалоба отклонена. Нарушений не выявлено.")
    except:
        pass

# ================================================================
# БЫСТРЫЕ ДЕЙСТВИЯ (из карточки юзера)
# ================================================================
@dp.callback_query(F.data.startswith("quick_"))
async def quick_action_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    parts = call.data.split("_")
    action, tid = parts[1], int(parts[2])

    if action == "warn":
        if tid in ADMINS:
            await call.answer("❌ Нельзя варнить администратора!", show_alert=True)
            return
        warns, banned = await do_warn(tid)
        msg = f"🔨 3 варна → автобан 3 дня!" if banned else f"✅ Варн выдан. Варнов: {warns}/3"
        await call.answer(msg, show_alert=True)

    elif action == "unwarn":
        warns = await get_warns(tid)
        if warns <= 0:
            await call.answer("ℹ️ Варнов нет.", show_alert=True)
            return
        await db_exec("UPDATE users SET warns=warns-1 WHERE id=$1", (tid,))
        try:
            await bot.send_message(tid, f"✅ Варн снят. Осталось: *{warns-1}/3*", parse_mode="Markdown")
        except:
            pass
        await call.answer(f"✅ Варн снят. Осталось: {warns-1}/3", show_alert=True)

    elif action == "ban":
        until = datetime.now() + timedelta(days=3)
        await db_exec("UPDATE users SET banned_until=$1 WHERE id=$2", (until, tid))
        if tid in active_chats:
            pid = active_chats.pop(tid)
            active_chats.pop(pid, None)
            try:
                await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
            except:
                pass
        try:
            await bot.send_message(tid, "🔨 Вы заблокированы *на 3 дня*.", parse_mode="Markdown")
        except:
            pass
        await call.answer("✅ Забанен на 3 дня.", show_alert=True)

    elif action == "unban":
        await db_exec("UPDATE users SET banned_until=NULL WHERE id=$1", (tid,))
        try:
            await bot.send_message(tid, "✅ Вы разблокированы!")
        except:
            pass
        await call.answer("✅ Разбанен.", show_alert=True)

    elif action == "mute":
        until = datetime.now() + timedelta(days=1)
        await db_exec("UPDATE users SET muted_until=$1 WHERE id=$2", (until, tid))
        try:
            await bot.send_message(tid, "🔇 Вы замучены *на 1 день*.", parse_mode="Markdown")
        except:
            pass
        await call.answer("✅ Замучен на 1 день.", show_alert=True)

    elif action == "unmute":
        await db_exec("UPDATE users SET muted_until=NULL WHERE id=$1", (tid,))
        try:
            await bot.send_message(tid, "🔊 Мут снят!")
        except:
            pass
        await call.answer("✅ Размучен.", show_alert=True)

# ================================================================
# АДМИН — рассылка текст
# ================================================================
@dp.callback_query(F.data == "adm_broad")
async def broad_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.broadcasting)
    await call.message.answer("📢 Введите текст рассылки:")
    await call.answer()

@dp.message(States.broadcasting)
async def broad_process(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await state.clear()
        return
    users = await db_exec("SELECT id FROM users", fetch="all")
    count = 0
    for u in users:
        try:
            await bot.send_message(u['id'], f"📣 *Объявление:*\n\n{message.text}", parse_mode="Markdown")
            count += 1
        except:
            pass
    await message.answer(f"✅ Рассылка завершена! Получили {count} юзеров.")
    await state.clear()

# ================================================================
# АДМИН — рассылка с фото
# ================================================================
@dp.callback_query(F.data == "adm_broad_photo")
async def broad_photo_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.broadcast_photo)
    await call.message.answer("🖼 Отправьте фото с подписью для рассылки:")
    await call.answer()

@dp.message(States.broadcast_photo, F.photo)
async def broad_photo_process(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await state.clear()
        return
    users = await db_exec("SELECT id FROM users", fetch="all")
    count = 0
    caption = message.caption or "📣 Объявление"
    for u in users:
        try:
            await bot.send_photo(u['id'], message.photo[-1].file_id, caption=caption)
            count += 1
        except:
            pass
    await message.answer(f"✅ Рассылка с фото завершена! Получили {count} юзеров.")
    await state.clear()

# ================================================================
# АДМИН — выдать прем
# ================================================================
@dp.callback_query(F.data == "adm_give_manual")
async def give_manual_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.giving_prem_id)
    await call.message.answer(
        "🎁 Введите ID и кол-во дней через пробел.\n"
        "Пример: `123456789 30`\n"
        "Просто ID — даст 30 дней: `123456789`",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(States.giving_prem_id)
async def give_manual_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await state.clear()
        return
    parts = message.text.strip().split()
    try:
        target = int(parts[0])
        days = int(parts[1]) if len(parts) > 1 else 30
    except:
        await message.answer("❌ Неверный формат. Пример: `123456789 30`", parse_mode="Markdown")
        await state.clear()
        return
    row = await db_exec("SELECT prem_until FROM users WHERE id=$1", (target,), "one")
    if row is None:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    base = datetime.now()
    if row['prem_until'] and row['prem_until'] > base:
        base = row['prem_until']
    until = base + timedelta(days=days)
    await db_exec("UPDATE users SET prem_until=$1 WHERE id=$2", (until, target))
    try:
        await bot.send_message(
            target,
            f"💎 Вам выдан *Premium на {days} дней*!\nДо: {until.strftime('%d.%m.%Y')}",
            parse_mode="Markdown"
        )
    except:
        pass
    await message.answer(f"✅ Premium на {days} дн. выдан `{target}`.", parse_mode="Markdown")
    await state.clear()

# ================================================================
# АДМИН — жалобы
# ================================================================
@dp.callback_query(F.data == "adm_reps")
async def adm_reps_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    r = await db_exec(
        "SELECT id,reporter_id,target_id,last_message,created_at FROM reports ORDER BY id ASC LIMIT 1",
        fetch="one"
    )
    if not r:
        await call.answer("Жалоб нет!", show_alert=True)
        return
    rep_id, reporter_id, target_id = r['id'], r['reporter_id'], r['target_id']
    total_row = await db_exec("SELECT COUNT(*) AS cnt FROM reports", fetch="one")
    total = total_row['cnt'] if total_row else 0
    pid_info = await get_user_info_full(target_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔨 Бан 3 дня",      callback_data=f"rban_3_{target_id}_{rep_id}")
    kb.button(text="🔇 Мут 1 день",     callback_data=f"rmute_1_{target_id}_{rep_id}")
    kb.button(text="⚠️ Предупреждение", callback_data=f"rwarn_{target_id}_{rep_id}")
    kb.button(text="✅ Без наказания",   callback_data=f"rnoban_{target_id}_{rep_id}")
    await call.message.answer(
        f"🚩 *Жалоба #{rep_id}* (всего: {total})\nОт: `{reporter_id}`\n\n"
        f"*Нарушитель:*\n{pid_info}\n\n"
        f"*Сообщение:*\n`{r['last_message'] or '(нет)'}`",
        reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown"
    )
    await call.answer()

# ================================================================
# АДМИН — статистика
# ================================================================
@dp.callback_query(F.data == "a_stats")
async def a_stats_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    now = datetime.now()
    all_ids = await db_exec("SELECT id FROM users", fetch="all")
    active_count = 0
    removed = []
    for row in all_ids:
        try:
            await bot.get_chat(row['id'])
            active_count += 1
        except:
            removed.append(row['id'])
    for uid in removed:
        await db_exec("DELETE FROM users WHERE id=$1", (uid,))

    def cnt(r):
        return r['cnt'] if r else 0

    prem_c = cnt(await db_exec("SELECT COUNT(*) AS cnt FROM users WHERE prem_until > $1", (now,), "one"))
    ban_c  = cnt(await db_exec("SELECT COUNT(*) AS cnt FROM users WHERE banned_until > $1", (now,), "one"))
    mute_c = cnt(await db_exec("SELECT COUNT(*) AS cnt FROM users WHERE muted_until > $1", (now,), "one"))
    warn_c = cnt(await db_exec("SELECT COUNT(*) AS cnt FROM users WHERE warns > 0", fetch="one"))
    rep_c  = cnt(await db_exec("SELECT COUNT(*) AS cnt FROM reports", fetch="one"))
    ch_c   = cnt(await db_exec("SELECT COUNT(*) AS cnt FROM ad_channels", fetch="one"))
    online = len(active_chats) // 2

    await call.message.answer(
        f"📊 *Статистика бота*\n\n"
        f"👥 Всего юзеров: {active_count}\n"
        f"💎 Premium: {prem_c}\n"
        f"🚫 Забаненных: {ban_c}\n"
        f"🔇 Замученных: {mute_c}\n"
        f"⚠️ С варнами: {warn_c}\n"
        f"🚩 Жалоб в очереди: {rep_c}\n"
        f"💬 Активных чатов: {online}\n"
        f"📣 Рекл. каналов: {ch_c}",
        parse_mode="Markdown"
    )
    await call.answer()

# ================================================================
# АДМИН — бан по ID/ник
# ================================================================
@dp.callback_query(F.data == "adm_ban")
async def adm_ban_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.admin_ban_input)
    kb = InlineKeyboardBuilder()
    kb.button(text="1 день",   callback_data="banperiod_1")
    kb.button(text="7 дней",   callback_data="banperiod_7")
    kb.button(text="30 дней",  callback_data="banperiod_30")
    kb.button(text="Навсегда", callback_data="banperiod_999")
    await call.message.answer("🔨 *Бан*\nВыберите срок:", reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("banperiod_"))
async def adm_ban_period(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    days = call.data.split("_")[1]
    await state.update_data(ban_days=days)
    label = "навсегда" if days == "999" else f"{days} дн."
    await call.message.answer(f"Срок: *{label}*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_ban_input)
async def adm_ban_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    data = await state.get_data()
    days_str = data.get("ban_days")
    if not days_str:
        await message.answer("Сначала выберите срок через кнопку.")
        return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        row = await db_exec("SELECT id,username FROM users WHERE id=$1", (int(raw),), "one")
    except:
        row = await db_exec("SELECT id,username FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname = row['id'], row['username']
    days = int(days_str)
    until = datetime.now() + timedelta(days=36500 if days == 999 else days)
    label = "навсегда" if days == 999 else f"на {days} дн."
    await db_exec("UPDATE users SET banned_until=$1 WHERE id=$2", (until, tid))
    if tid in active_chats:
        pid = active_chats.pop(tid)
        active_chats.pop(pid, None)
        try:
            await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
        except:
            pass
    try:
        await bot.send_message(tid, f"🔨 Вы заблокированы *{label}*.", parse_mode="Markdown")
    except:
        pass
    await message.answer(f"✅ @{tname or tid} заблокирован {label}.")
    await state.clear()

# ================================================================
# АДМИН — мут по ID/ник
# ================================================================
@dp.callback_query(F.data == "adm_mute")
async def adm_mute_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.admin_mute_input)
    kb = InlineKeyboardBuilder()
    kb.button(text="1 день",   callback_data="muteperiod_1")
    kb.button(text="7 дней",   callback_data="muteperiod_7")
    kb.button(text="30 дней",  callback_data="muteperiod_30")
    kb.button(text="Навсегда", callback_data="muteperiod_999")
    await call.message.answer("🔇 *Мут*\nВыберите срок:", reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("muteperiod_"))
async def adm_mute_period(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    days = call.data.split("_")[1]
    await state.update_data(mute_days=days)
    label = "навсегда" if days == "999" else f"{days} дн."
    await call.message.answer(f"Срок: *{label}*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_mute_input)
async def adm_mute_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    data = await state.get_data()
    days_str = data.get("mute_days")
    if not days_str:
        await message.answer("Сначала выберите срок.")
        return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        row = await db_exec("SELECT id,username FROM users WHERE id=$1", (int(raw),), "one")
    except:
        row = await db_exec("SELECT id,username FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname = row['id'], row['username']
    days = int(days_str)
    until = datetime.now() + timedelta(days=36500 if days == 999 else days)
    label = "навсегда" if days == 999 else f"на {days} дн."
    await db_exec("UPDATE users SET muted_until=$1 WHERE id=$2", (until, tid))
    try:
        await bot.send_message(tid, f"🔇 Вы замучены *{label}*.", parse_mode="Markdown")
    except:
        pass
    await message.answer(f"✅ @{tname or tid} замучен {label}.")
    await state.clear()

# ================================================================
# АДМИН — разбан
# ================================================================
@dp.callback_query(F.data == "adm_unban_id")
async def adm_unban_id_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.update_data(unban_mode="id")
    await state.set_state(States.admin_unban_id)
    await call.message.answer("🔓 *Разбан*\nВведите числовой ID:", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "adm_unban_un")
async def adm_unban_un_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.update_data(unban_mode="username")
    await state.set_state(States.admin_unban_id)
    await call.message.answer("🔓 *Разбан*\nВведите @username (без @):", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_unban_id)
async def adm_unban_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    data = await state.get_data()
    raw = message.text.strip().lstrip("@")
    row = None
    if data.get("unban_mode") == "id":
        try:
            row = await db_exec("SELECT id,username FROM users WHERE id=$1", (int(raw),), "one")
        except:
            await message.answer("❌ Введите числовой ID.")
            await state.clear()
            return
    else:
        row = await db_exec("SELECT id,username FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname = row['id'], row['username']
    await db_exec("UPDATE users SET banned_until=NULL WHERE id=$1", (tid,))
    try:
        await bot.send_message(tid, "✅ Вы разблокированы! Добро пожаловать!")
    except:
        pass
    await message.answer(f"✅ @{tname or tid} разблокирован.")
    await state.clear()

# ================================================================
# АДМИН — размут
# ================================================================
@dp.callback_query(F.data == "adm_unmute_id")
async def adm_unmute_id_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.update_data(unmute_mode="id")
    await state.set_state(States.admin_unmute_id)
    await call.message.answer("🔊 *Размут*\nВведите числовой ID:", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "adm_unmute_un")
async def adm_unmute_un_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.update_data(unmute_mode="username")
    await state.set_state(States.admin_unmute_id)
    await call.message.answer("🔊 *Размут*\nВведите @username (без @):", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_unmute_id)
async def adm_unmute_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    data = await state.get_data()
    raw = message.text.strip().lstrip("@")
    row = None
    if data.get("unmute_mode") == "id":
        try:
            row = await db_exec("SELECT id,username FROM users WHERE id=$1", (int(raw),), "one")
        except:
            await message.answer("❌ Введите числовой ID.")
            await state.clear()
            return
    else:
        row = await db_exec("SELECT id,username FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname = row['id'], row['username']
    await db_exec("UPDATE users SET muted_until=NULL WHERE id=$1", (tid,))
    try:
        await bot.send_message(tid, "🔊 Мут снят!")
    except:
        pass
    await message.answer(f"✅ @{tname or tid} размучен.")
    await state.clear()

# ================================================================
# АДМИН — варн по ID/ник
# ================================================================
@dp.callback_query(F.data == "adm_warn")
async def adm_warn_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.admin_warn_input)
    await call.message.answer("⚠️ *Варн*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_warn_input)
async def adm_warn_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        row = await db_exec("SELECT id,username FROM users WHERE id=$1", (int(raw),), "one")
    except:
        row = await db_exec("SELECT id,username FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname = row['id'], row['username']
    if tid in ADMINS:
        await message.answer("❌ Нельзя варнить администратора.")
        await state.clear()
        return
    warns, banned = await do_warn(tid)
    name = f"@{tname}" if tname else str(tid)
    if banned:
        await message.answer(f"🔨 {name} — 3 варна, автобан 3 дня!")
    else:
        await message.answer(f"✅ Варн выдан {name}. Варнов: {warns}/3")
    await state.clear()

# ================================================================
# АДМИН — снять варн
# ================================================================
@dp.callback_query(F.data == "adm_unwarn")
async def adm_unwarn_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.admin_unwarn_input)
    await call.message.answer("🗑 *Снять варн*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_unwarn_input)
async def adm_unwarn_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        row = await db_exec("SELECT id,username,warns FROM users WHERE id=$1", (int(raw),), "one")
    except:
        row = await db_exec("SELECT id,username,warns FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname, warns = row['id'], row['username'], row['warns'] or 0
    name = f"@{tname}" if tname else str(tid)
    if warns <= 0:
        await message.answer(f"ℹ️ У {name} нет варнов.")
        await state.clear()
        return
    await db_exec("UPDATE users SET warns=warns-1 WHERE id=$1", (tid,))
    try:
        await bot.send_message(tid, f"✅ Варн снят. Осталось: *{warns-1}/3*", parse_mode="Markdown")
    except:
        pass
    await message.answer(f"✅ Варн снят с {name}. Осталось: {warns-1}/3")
    await state.clear()

# ================================================================
# АДМИН — сбросить варны
# ================================================================
@dp.callback_query(F.data == "adm_reset_warns")
async def adm_reset_warns_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.admin_reset_warns)
    await call.message.answer("🔄 *Сбросить все варны*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_reset_warns)
async def adm_reset_warns_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        row = await db_exec("SELECT id,username,warns FROM users WHERE id=$1", (int(raw),), "one")
    except:
        row = await db_exec("SELECT id,username,warns FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname, warns = row['id'], row['username'], row['warns'] or 0
    name = f"@{tname}" if tname else str(tid)
    await db_exec("UPDATE users SET warns=0 WHERE id=$1", (tid,))
    try:
        await bot.send_message(tid, "✅ Все ваши предупреждения сброшены администрацией!")
    except:
        pass
    await message.answer(f"✅ Все варны ({warns}) сброшены у {name}.")
    await state.clear()

# ================================================================
# АДМИН — список банов
# ================================================================
@dp.callback_query(F.data == "adm_banlist")
async def adm_banlist(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    now = datetime.now()
    banned = await db_exec(
        "SELECT id,username,banned_until FROM users WHERE banned_until > $1 ORDER BY banned_until DESC LIMIT 10",
        (now,), "all"
    )
    muted = await db_exec(
        "SELECT id,username,muted_until FROM users WHERE muted_until > $1 ORDER BY muted_until DESC LIMIT 10",
        (now,), "all"
    )
    warned = await db_exec(
        "SELECT id,username,warns FROM users WHERE warns > 0 ORDER BY warns DESC LIMIT 10",
        (), "all"
    )

    txt = "📋 *Активные наказания*\n\n🔨 *Забаненные:*\n"
    if banned:
        for r in banned:
            txt += f"• `{r['id']}` @{r['username'] or '—'} до {r['banned_until'].strftime('%d.%m.%Y')}\n"
    else:
        txt += "Нет\n"

    txt += "\n🔇 *Замученные:*\n"
    if muted:
        for r in muted:
            txt += f"• `{r['id']}` @{r['username'] or '—'} до {r['muted_until'].strftime('%d.%m.%Y')}\n"
    else:
        txt += "Нет\n"

    txt += "\n⚠️ *С варнами:*\n"
    if warned:
        for r in warned:
            txt += f"• `{r['id']}` @{r['username'] or '—'} — {r['warns']}/3\n"
    else:
        txt += "Нет\n"

    await call.message.answer(txt, parse_mode="Markdown")
    await call.answer()

# ================================================================
# АДМИН — найти юзера
# ================================================================
@dp.callback_query(F.data == "adm_lookup")
async def adm_lookup_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.admin_lookup_user)
    await call.message.answer("🔍 *Найти пользователя*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_lookup_user)
async def adm_lookup_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        row = await db_exec(
            "SELECT id,username,refs,prem_until,gender,age,banned_until,muted_until,warns FROM users WHERE id=$1",
            (int(raw),), "one"
        )
    except:
        row = await db_exec(
            "SELECT id,username,refs,prem_until,gender,age,banned_until,muted_until,warns FROM users WHERE username=$1",
            (raw,), "one"
        )
    if not row:
        await message.answer("❌ Не найден в базе.")
        await state.clear()
        return

    now  = datetime.now()
    uid2 = row['id']
    gender_str = {"М": "👨 Мужской", "Ж": "👩 Женский"}.get(row['gender'], "—")
    prem_str = "❌ Нет"
    if row['prem_until']:
        prem_str = f"✅ до {row['prem_until'].strftime('%d.%m.%Y')}" if row['prem_until'] > now else "❌ Истёк"
    ban_str  = f"🔨 до {row['banned_until'].strftime('%d.%m.%Y %H:%M')}" if row['banned_until'] and row['banned_until'] > now else "—"
    mute_str = f"🔇 до {row['muted_until'].strftime('%d.%m.%Y %H:%M')}"  if row['muted_until'] and row['muted_until'] > now else "—"
    in_chat  = "💬 В чате" if uid2 in active_chats else "🔴 Не в чате"

    txt = (
        f"🔍 *Профиль*\n━━━━━━━━━━━━━━━\n"
        f"🆔 ID: `{uid2}`\n"
        f"👤 Ник: @{row['username'] or '—'}\n"
        f"🚻 Пол: {gender_str}\n"
        f"🎂 Возраст: {row['age'] or '—'}\n"
        f"🎖 Ранг: {await get_rank(uid2)}\n"
        f"💎 Premium: {prem_str}\n"
        f"👥 Рефералов: {row['refs'] or 0}\n"
        f"⚠️ Варнов: {row['warns'] or 0}/3\n"
        f"🔨 Бан: {ban_str}\n"
        f"🔇 Мут: {mute_str}\n"
        f"📡 Статус: {in_chat}\n"
        f"━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="⚠️ Варн",       callback_data=f"quick_warn_{uid2}")
    kb.button(text="🗑 Снять варн",  callback_data=f"quick_unwarn_{uid2}")
    kb.button(text="🔨 Бан 3 дня",  callback_data=f"quick_ban_{uid2}")
    kb.button(text="🔓 Разбан",     callback_data=f"quick_unban_{uid2}")
    kb.button(text="🔇 Мут 1 день", callback_data=f"quick_mute_{uid2}")
    kb.button(text="🔊 Размут",     callback_data=f"quick_unmute_{uid2}")
    await message.answer(txt, reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
    await state.clear()

# ================================================================
# АДМИН — снять Premium
# ================================================================
@dp.callback_query(F.data == "adm_revoke_prem")
async def adm_revoke_prem_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.admin_revoke_prem)
    await call.message.answer("❌ *Снять Premium*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_revoke_prem)
async def adm_revoke_prem_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        row = await db_exec("SELECT id,username,prem_until FROM users WHERE id=$1", (int(raw),), "one")
    except:
        row = await db_exec("SELECT id,username,prem_until FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname, prem_until = row['id'], row['username'], row['prem_until']
    name = f"@{tname}" if tname else str(tid)
    if not prem_until or prem_until <= datetime.now():
        await message.answer(f"ℹ️ У {name} нет активного Premium.")
        await state.clear()
        return
    await db_exec("UPDATE users SET prem_until=NULL WHERE id=$1", (tid,))
    try:
        await bot.send_message(tid, "❌ Ваш Premium был отозван администрацией.")
    except:
        pass
    await message.answer(f"✅ Premium снят у {name}.")
    await state.clear()

# ================================================================
# АДМИН — сообщение юзеру
# ================================================================
@dp.callback_query(F.data == "adm_msg_user")
async def adm_msg_user_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.admin_msg_user)
    await call.message.answer(
        "✉️ *Сообщение юзеру*\nФормат: `ID текст`\nПример: `123456789 Привет!`",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(States.admin_msg_user)
async def adm_msg_user_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    parts = message.text.strip().split(" ", 1)
    if len(parts) < 2:
        await message.answer("❌ Формат: `ID текст`", parse_mode="Markdown")
        await state.clear()
        return
    raw, text = parts[0].lstrip("@"), parts[1]
    row = None
    try:
        row = await db_exec("SELECT id,username FROM users WHERE id=$1", (int(raw),), "one")
    except:
        row = await db_exec("SELECT id,username FROM users WHERE username=$1", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    tid, tname = row['id'], row['username']
    try:
        await bot.send_message(tid, f"📩 *Сообщение от администрации:*\n\n{text}", parse_mode="Markdown")
        await message.answer(f"✅ Отправлено @{tname or tid}.")
    except:
        await message.answer("❌ Не удалось — юзер заблокировал бота.")
    await state.clear()

# ================================================================
# РЕКЛАМНЫЕ КАНАЛЫ (ADMIN)
# ================================================================
@dp.callback_query(F.data == "adm_ad_channels")
async def adm_ad_channels(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    channels = await get_ad_channels()
    ch_list = "\n".join(f"• {ch['title'] or ch['url']}" for ch in channels) if channels else "Нет каналов"
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить канал/группу", callback_data="adm_ad_add")
    kb.button(text="🗑 Удалить канал/группу",  callback_data="adm_ad_delete")
    await call.message.answer(
        f"📣 *Рекламные каналы*\n\nТекущие:\n{ch_list}\n\n"
        f"При регистрации юзеры обязаны подписаться на все каналы.",
        reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "adm_ad_add")
async def adm_ad_add_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        return
    await state.set_state(States.add_ad_channel)
    await call.message.answer(
        "➕ *Добавить канал*\n\nОтправь ссылку: `https://t.me/channel` или `@channel`\n\n"
        "❗ Бот должен быть администратором канала для проверки подписки.",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(States.add_ad_channel)
async def adm_ad_add_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    url = message.text.strip()
    if not (url.startswith("http") or url.startswith("@")):
        await message.answer("❌ Неверный формат. Пример: https://t.me/channel")
        await state.clear()
        return
    title = None
    try:
        username = "@" + url.strip().split("/")[-1].lstrip("@")
        chat_info = await bot.get_chat(username)
        title = chat_info.title or chat_info.username
    except:
        title = url
    await db_exec("INSERT INTO ad_channels (url,title) VALUES ($1,$2)", (url, title))
    await message.answer(f"✅ Канал *{title}* добавлен!", parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "adm_ad_delete")
async def adm_ad_delete_start(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    channels = await get_ad_channels()
    if not channels:
        await call.answer("Нет каналов.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    for ch in channels:
        kb.button(text=f"🗑 {ch['title'] or ch['url']}", callback_data=f"adm_ad_del_{ch['id']}")
    await call.message.answer("🗑 *Выбери канал для удаления:*", reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("adm_ad_del_") & ~F.data.startswith("adm_ad_delconfirm_"))
async def adm_ad_del_confirm(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    ch_id = int(call.data.split("_")[-1])
    ch = await db_exec("SELECT id,url,title FROM ad_channels WHERE id=$1", (ch_id,), "one")
    if not ch:
        await call.answer("Уже удалён.", show_alert=True)
        return
    title = ch['title'] or ch['url']
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, удалить", callback_data=f"adm_ad_delconfirm_{ch_id}")
    kb.button(text="❌ Нет",         callback_data="adm_ad_channels")
    await call.message.edit_text(
        f"❓ Удалить канал *{title}*?\n`{ch['url']}`",
        reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("adm_ad_delconfirm_"))
async def adm_ad_delconfirm(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    ch_id = int(call.data.split("_")[-1])
    ch = await db_exec("SELECT title,url FROM ad_channels WHERE id=$1", (ch_id,), "one")
    if not ch:
        await call.answer("Уже удалён.", show_alert=True)
        return
    title = ch['title'] or ch['url']
    await db_exec("DELETE FROM ad_channels WHERE id=$1", (ch_id,))
    await call.message.edit_text(f"✅ Канал *{title}* удалён.", parse_mode="Markdown")
    await call.answer()

# ================================================================
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК — пересылка в чате
# ================================================================
@dp.message(StateFilter("*"))
async def global_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    banned, until = await is_banned(uid)
    if banned:
        await message.answer(
            f"🚫 Вы заблокированы до *{until}*.\nОбратитесь в поддержку.",
            parse_mode="Markdown"
        )
        return

    if uid not in active_chats:
        return

    pid = active_chats[uid]
    muted, muted_until = await is_muted(uid)
    if muted:
        await message.answer(f"🔇 Вы замучены до *{muted_until}*.", parse_mode="Markdown")
        return

    if message.text:
        if is_ad_message(message.text):
            await handle_ad_warn(uid, message)
            return
        last_messages[uid] = f"[текст]: {message.text}"
    elif message.caption and is_ad_message(message.caption):
        await handle_ad_warn(uid, message)
        return
    elif message.photo:
        last_messages[uid] = "[фото]"
    elif message.sticker:
        last_messages[uid] = f"[стикер]: {message.sticker.emoji or ''}"
    elif message.voice:
        last_messages[uid] = "[голосовое]"
    elif message.video:
        last_messages[uid] = "[видео]"
    else:
        last_messages[uid] = "[медиа]"

    try:
        await bot.copy_message(pid, uid, message.message_id)
    except:
        pass

# ================================================================
# ЗАПУСК
# ================================================================
async def main():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import asyncpg
import logging
import os
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- КОНФИГ ---
TOKEN = "8784182805:AAGk8Tw2Kan-Yj-Jxq_YujXqCMFcKYUWp-M"
ADMINS = [8528807150, 7245932902, 8784182805]
DATABASE_URL = os.environ.get("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Глобальный пул соединений
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

# --- СОСТОЯНИЯ ---
class States(StatesGroup):
    broadcasting         = State()
    giving_prem_id       = State()
    wait_proof           = State()
    tech_support         = State()
    admin_reply          = State()
    admin_ban_input      = State()
    admin_mute_input     = State()
    admin_unban_id       = State()
    admin_unmute_id      = State()
    admin_warn_input     = State()
    admin_unwarn_input   = State()
    admin_msg_user       = State()
    admin_lookup_user    = State()
    admin_reset_warns    = State()
    admin_revoke_prem    = State()
    user_tech_support    = State()
    prem_search_topic    = State()

# ================================================================
# БАЗА ДАННЫХ (PostgreSQL через asyncpg)
# ================================================================
async def db_exec(sql, params=(), fetch="none"):
    """Универсальная функция выполнения SQL-запросов."""
    # Конвертируем SQLite-стиль ? в PostgreSQL-стиль $1, $2, ...
    pg_sql = sql
    counter = [0]
    def replacer(match):
        counter[0] += 1
        return f"${counter[0]}"
    import re
    pg_sql = re.sub(r'\?', replacer, sql)

    async with pool.acquire() as conn:
        if fetch == "one":
            return await conn.fetchrow(pg_sql, *params)
        elif fetch == "all":
            return await conn.fetch(pg_sql, *params)
        else:
            await conn.execute(pg_sql, *params)

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

async def is_prem(uid):
    if uid in ADMINS: return True
    r = await db_exec("SELECT prem_until FROM users WHERE id=?", (uid,), "one")
    return bool(r and r[0] and r[0] > datetime.now())

async def is_banned(uid):
    if uid in ADMINS: return False, None
    r = await db_exec("SELECT banned_until FROM users WHERE id=?", (uid,), "one")
    if r and r[0]:
        t = r[0]
        if t > datetime.now():
            return True, t.strftime("%d.%m.%Y %H:%M")
        await db_exec("UPDATE users SET banned_until=NULL WHERE id=?", (uid,))
    return False, None

async def is_muted(uid):
    if uid in ADMINS: return False, None
    r = await db_exec("SELECT muted_until FROM users WHERE id=?", (uid,), "one")
    if r and r[0]:
        t = r[0]
        if t > datetime.now():
            return True, t.strftime("%d.%m.%Y %H:%M")
        await db_exec("UPDATE users SET muted_until=NULL WHERE id=?", (uid,))
    return False, None

async def get_warns(uid):
    r = await db_exec("SELECT warns FROM users WHERE id=?", (uid,), "one")
    return r[0] if r and r[0] else 0

async def get_rank(uid):
    if uid in ADMINS: return "👑 Администратор"
    if await is_prem(uid): return "💎 Premium"
    return "👤 Пользователь"

async def get_user_info(uid):
    r = await db_exec("SELECT username, gender, age, prem_until FROM users WHERE id=?", (uid,), "one")
    if not r:
        return f"ID: `{uid}`\nИнфо не найдено"
    username, gender, age, prem_until = r
    rank = await get_rank(uid)
    gender_str = {"М": "👨 Мужской", "Ж": "👩 Женский"}.get(gender, "—")
    warns = await get_warns(uid)
    return (
        f"🆔 ID: `{uid}`\n"
        f"👤 Ник: @{username or '—'}\n"
        f"🚻 Пол: {gender_str}\n"
        f"🎂 Возраст: {age or '—'}\n"
        f"🎖 Ранг: {rank}\n"
        f"⚠️ Варнов: {warns}/3"
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
    kb.row(types.KeyboardButton(text="🚩 Пожаловаться"))
    return kb.as_markup(resize_keyboard=True)

# ================================================================
# ЛОГИКА ПОИСКА
# ================================================================
active_chats  = {}
last_messages = {}
queues = {"all": [], "М": [], "Ж": [], "Music": [], "Games": [], "Anime": [], "Code": [], "18+": [], "25+": [], "<18": [], "VIP": []}

async def _basic_card(uid):
    """Базовая карточка собеседника для обычных юзеров (без варнов и ранга)."""
    r = await db_exec("SELECT username, gender, age FROM users WHERE id=?", (uid,), "one")
    if not r:
        return f"ID: `{uid}`\nИнфо не найдено"
    username, gender, age = r
    gender_str = {"М": "👨 Мужской", "Ж": "👩 Женский"}.get(gender, "—")
    return (
        f"🆔 ID: `{uid}`\n"
        f"👤 Ник: @{username or '—'}\n"
        f"🚻 Пол: {gender_str}\n"
        f"🎂 Возраст: {age or '—'}"
    )

async def enter_queue(uid, cat):
    if uid in active_chats: return
    for k in queues:
        if uid in queues[k]: queues[k].remove(uid)
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

        uid_card = await get_user_info(pid)
        pid_card = await get_user_info(uid)

        uid_card_basic = uid_card if await is_prem(uid) else await _basic_card(pid)
        pid_card_basic = pid_card if await is_prem(pid) else await _basic_card(uid)

        await bot.send_message(uid, f"🎁 *Собеседник найден!*\n\n{uid_card_basic}", reply_markup=chat_kb(), parse_mode="Markdown")
        await bot.send_message(pid, f"🎁 *Собеседник найден!*\n\n{pid_card_basic}", reply_markup=chat_kb(), parse_mode="Markdown")
    else:
        queues[cat].append(uid)
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="stop_q")
        await bot.send_message(uid, f"⏳ Поиск в категории [{cat}]...", reply_markup=kb.as_markup())

# ================================================================
# КНОПКИ ЧАТА
# ================================================================
@dp.message(StateFilter("*"), F.text == "❌ Выйти")
async def chat_exit(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in active_chats: return
    await state.clear()
    pid = active_chats.pop(uid)
    active_chats.pop(pid, None)
    last_messages.pop(uid, None)
    last_messages.pop(pid, None)
    await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
    await message.answer("Вы вышли из чата.", reply_markup=main_kb(uid))

@dp.message(StateFilter("*"), F.text == "➡️ Следующий")
async def chat_next(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in active_chats: return
    await state.clear()
    pid = active_chats.pop(uid)
    active_chats.pop(pid, None)
    last_messages.pop(uid, None)
    last_messages.pop(pid, None)
    await bot.send_message(pid, "💔 Собеседник ушёл искать другого...", reply_markup=main_kb(pid))
    await enter_queue(uid, "all")

@dp.message(StateFilter("*"), F.text == "🚩 Пожаловаться")
async def chat_report(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in active_chats:
        await message.answer("❌ Вы не в чате.")
        return
    await state.clear()
    pid = active_chats[uid]
    last_msg = last_messages.get(pid) or "(нет сообщений)"

    await db_exec("INSERT INTO reports (reporter_id, target_id, last_message) VALUES (?,?,?)", (uid, pid, last_msg))
    rep_row = await db_exec("SELECT id FROM reports ORDER BY id DESC LIMIT 1", fetch="one")
    rep_id = rep_row[0] if rep_row else 0

    pid_info = await get_user_info(pid)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔨 Бан 3 дня",      callback_data=f"rban_3_{pid}_{rep_id}")
    kb.button(text="🔇 Мут 1 день",     callback_data=f"rmute_1_{pid}_{rep_id}")
    kb.button(text="⚠️ Предупреждение", callback_data=f"rwarn_{pid}_{rep_id}")
    kb.button(text="✅ Без наказания",  callback_data=f"rnoban_{pid}_{rep_id}")
    text = (
        f"🚩 *Новая жалоба!*\n\n*Нарушитель:*\n{pid_info}\n\n"
        f"*Последнее сообщение нарушителя:*\n`{last_msg}`"
    )
    for adm in ADMINS:
        try:
            await bot.send_message(adm, text, reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
        except:
            pass
    await message.answer("✅ Жалоба отправлена администрации!\nПродолжайте чат или выйдите.")

# ================================================================
# /start
# ================================================================
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    uid  = message.from_user.id
    args = message.text.split()
    ref_id = args[1] if len(args) > 1 else None

    is_new = not await db_exec("SELECT id FROM users WHERE id=?", (uid,), "one")
    if is_new:
        await db_exec("INSERT INTO users (id, username, refs) VALUES (?,?,0)", (uid, message.from_user.username))
        if ref_id:
            try:
                rid = int(ref_id)
                if rid != uid and await db_exec("SELECT id FROM users WHERE id=?", (rid,), "one"):
                    await db_exec("UPDATE users SET refs=refs+1 WHERE id=?", (rid,))
                    u_refs_row = await db_exec("SELECT refs FROM users WHERE id=?", (rid,), "one")
                    u_refs = u_refs_row[0] if u_refs_row else 0
                    try:
                        await bot.send_message(rid, f"🎉 По вашей реф-ссылке зарегистрировался новый пользователь!\n👥 Ваших рефералов: *{u_refs}*", parse_mode="Markdown")
                    except: pass
                    if u_refs % 10 == 0:
                        cur_row = await db_exec("SELECT prem_until FROM users WHERE id=?", (rid,), "one")
                        cur = cur_row[0] if cur_row else None
                        base = datetime.now()
                        if cur and cur > base:
                            base = cur
                        until = base + timedelta(days=2)
                        await db_exec("UPDATE users SET prem_until=? WHERE id=?", (until, rid))
                        try:
                            await bot.send_message(rid, f"🏆 Вы пригласили *{u_refs}* человек — получаете *+2 дня Premium*!", parse_mode="Markdown")
                        except: pass
            except (ValueError, TypeError): pass

    kb = InlineKeyboardBuilder()
    for a in ["< 18", "18+", "25+", "65+"]:
        kb.button(text=a, callback_data=f"set_age_{a}")
    await message.answer("👋 Добро пожаловать! Укажи свой возраст:", reply_markup=kb.adjust(2).as_markup())

@dp.callback_query(F.data.startswith("set_age_"))
async def cb_age(call: types.CallbackQuery):
    await db_exec("UPDATE users SET age=? WHERE id=?", (call.data[8:], call.from_user.id))
    kb = InlineKeyboardBuilder()
    kb.button(text="👨 Мужской", callback_data="set_sex_М")
    kb.button(text="👩 Женский", callback_data="set_sex_Ж")
    await call.message.edit_text("Теперь выбери свой пол:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("set_sex_"))
async def cb_sex(call: types.CallbackQuery):
    await db_exec("UPDATE users SET gender=? WHERE id=?", (call.data[8:], call.from_user.id))
    await call.message.answer("🎉 Регистрация завершена! Теперь ты можешь искать общение.", reply_markup=main_kb(call.from_user.id))
    await call.message.delete()

# ================================================================
# ИНТЕРЕСЫ
# ================================================================
@dp.message(F.text == "🎭 По интересам")
async def interests_menu(message: types.Message):
    banned, until = await is_banned(message.from_user.id)
    if banned:
        await message.answer(f"🚫 Вы заблокированы до *{until}*.", parse_mode="Markdown")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="🎵 Музыка",  callback_data="q_Music")
    kb.button(text="🎮 Игры",    callback_data="q_Games")
    kb.button(text="⛩ Аниме",   callback_data="q_Anime")
    kb.button(text="💻 Кодинг", callback_data="q_Code")
    await message.answer("🎯 Выбери интерес для поиска:", reply_markup=kb.adjust(2).as_markup())

# ================================================================
# РАЗВЛЕЧЕНИЯ
# ================================================================
@dp.message(F.text == "🎲 Развлечения")
async def fun_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="😂 Анекдот",        callback_data="fun_joke")
    kb.button(text="🧠 Интересный факт", callback_data="fun_fact")
    kb.button(text="🎱 Магический шар",  callback_data="fun_8ball")
    await message.answer("🎲 *Развлечения*\nВыбери:", reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")

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
    await call.message.answer(f"🎱 *Магический шар говорит:*\n\n{random.choice(answers)}", parse_mode="Markdown")
    await call.answer()

# ================================================================
# РЕДАКТИРОВАНИЕ ПРОФИЛЯ
# ================================================================
@dp.callback_query(F.data == "edit_profile")
async def edit_profile_cb(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🚻 Изменить пол",     callback_data="ep_gender")
    kb.button(text="🎂 Изменить возраст", callback_data="ep_age")
    await call.message.answer("⚙️ *Редактирование профиля*\nЧто хочешь изменить?", reply_markup=kb.as_markup(), parse_mode="Markdown")
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
    await db_exec("UPDATE users SET gender=? WHERE id=?", (gender, call.from_user.id))
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
    await db_exec("UPDATE users SET age=? WHERE id=?", (age, call.from_user.id))
    await call.message.edit_text(f"✅ Возраст изменён на {age}!")

# ================================================================
# АДМИН ПАНЕЛЬ
# ================================================================
@dp.message(F.text == "⚙️ Админ Панель")
async def adm_panel(message: types.Message):
    if message.from_user.id not in ADMINS: return
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Рассылка",        callback_data="adm_broad")
    kb.button(text="🚩 Жалобы",          callback_data="adm_reps")
    kb.button(text="🎁 Выдать Прем",     callback_data="adm_give_manual")
    kb.button(text="📊 Статистика",      callback_data="a_stats")
    kb.button(text="🔨 Бан по ID",       callback_data="adm_ban")
    kb.button(text="🔇 Мут по ID",       callback_data="adm_mute")
    kb.button(text="🔓 Разбан по ID",    callback_data="adm_unban_id")
    kb.button(text="🔓 Разбан по ник",   callback_data="adm_unban_un")
    kb.button(text="🔊 Размут по ID",    callback_data="adm_unmute_id")
    kb.button(text="🔊 Размут по ник",   callback_data="adm_unmute_un")
    kb.button(text="⚠️ Варн по ID/ник",  callback_data="adm_warn")
    kb.button(text="🗑 Снять варн",       callback_data="adm_unwarn")
    kb.button(text="🔄 Сбросить варны",  callback_data="adm_reset_warns")
    kb.button(text="📋 Список банов",     callback_data="adm_banlist")
    kb.button(text="✉️ Сообщение юзеру", callback_data="adm_msg_user")
    kb.button(text="🔍 Найти юзера",     callback_data="adm_lookup")
    kb.button(text="❌ Снять Прем",      callback_data="adm_revoke_prem")
    await message.answer("🛠 *Панель управления администратора*", reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")

# --- Рассылка ---
@dp.callback_query(F.data == "adm_broad")
async def broad_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите текст рассылки:")
    await state.set_state(States.broadcasting)
    await call.answer()

@dp.message(States.broadcasting)
async def broad_process(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await state.clear(); return
    users = await db_exec("SELECT id FROM users", fetch="all")
    count = 0
    for u in users:
        try:
            await bot.send_message(u[0], f"📣 *Объявление:*\n\n{message.text}", parse_mode="Markdown")
            count += 1
        except: pass
    await message.answer(f"✅ Рассылка завершена! Получили {count} юзеров.")
    await state.clear()

# --- Выдать прем ---
@dp.callback_query(F.data == "adm_give_manual")
async def give_manual_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите ID пользователя для выдачи 30 дней Premium:")
    await state.set_state(States.giving_prem_id)
    await call.answer()

@dp.message(States.giving_prem_id)
async def give_manual_proc(message: types.Message, state: FSMContext):
    try:
        target = int(message.text.strip())
        row = await db_exec("SELECT prem_until FROM users WHERE id=?", (target,), "one")
        if row is not None:
            base = datetime.now()
            if row[0] and row[0] > base:
                base = row[0]
            until = base + timedelta(days=30)
            await db_exec("UPDATE users SET prem_until=? WHERE id=?", (until, target))
            try:
                await bot.send_message(target, "💎 Вам выдан *Premium на 30 дней*!", parse_mode="Markdown")
            except: pass
            await message.answer(f"✅ Premium выдан пользователю `{target}`.", parse_mode="Markdown")
        else:
            await message.answer("❌ Пользователь не найден.")
    except ValueError:
        await message.answer("❌ Неверный ID.")
    await state.clear()

# ================================================================
# ЖАЛОБЫ
# ================================================================
@dp.callback_query(F.data == "adm_reps")
async def adm_reps_cb(call: types.CallbackQuery):
    r = await db_exec("SELECT id,reporter_id,target_id,last_message,created_at FROM reports ORDER BY id ASC LIMIT 1", fetch="one")
    if not r:
        await call.answer("Жалоб нет!", show_alert=True)
        return
    rep_id, reporter_id, target_id, last_msg, created_at = r
    total_row = await db_exec("SELECT COUNT(*) FROM reports", fetch="one")
    total = total_row[0] if total_row else 0
    pid_info = await get_user_info(target_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔨 Бан 3 дня",      callback_data=f"rban_3_{target_id}_{rep_id}")
    kb.button(text="🔇 Мут 1 день",     callback_data=f"rmute_1_{target_id}_{rep_id}")
    kb.button(text="⚠️ Предупреждение", callback_data=f"rwarn_{target_id}_{rep_id}")
    kb.button(text="✅ Без наказания",  callback_data=f"rnoban_{target_id}_{rep_id}")
    text = (
        f"🚩 *Жалоба #{rep_id}* (в очереди: {total})\n"
        f"От: `{reporter_id}` | Дата: {created_at}\n\n"
        f"*Нарушитель:*\n{pid_info}\n\n"
        f"*Последнее сообщение:*\n`{last_msg or '(нет текста)'}`"
    )
    await call.message.answer(text, reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("rban_"))
async def r_ban_cb(call: types.CallbackQuery):
    parts = call.data.split("_")
    days, target_id, rep_id = int(parts[1]), int(parts[2]), int(parts[3])
    until = datetime.now() + timedelta(days=days)
    await db_exec("UPDATE users SET banned_until=? WHERE id=?", (until, target_id))
    if rep_id > 0: await db_exec("DELETE FROM reports WHERE id=?", (rep_id,))
    if target_id in active_chats:
        pid = active_chats.pop(target_id)
        active_chats.pop(pid, None)
        try: await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
        except: pass
    try: await bot.send_message(target_id, f"🔨 Вы заблокированы *на {days} дн.* за нарушение правил.", parse_mode="Markdown")
    except: pass
    try: await call.message.edit_text(f"✅ Пользователь `{target_id}` заблокирован на {days} дн.", parse_mode="Markdown")
    except: pass

@dp.callback_query(F.data.startswith("rmute_"))
async def r_mute_cb(call: types.CallbackQuery):
    parts = call.data.split("_")
    days, target_id, rep_id = int(parts[1]), int(parts[2]), int(parts[3])
    until = datetime.now() + timedelta(days=days)
    await db_exec("UPDATE users SET muted_until=? WHERE id=?", (until, target_id))
    if rep_id > 0: await db_exec("DELETE FROM reports WHERE id=?", (rep_id,))
    try: await bot.send_message(target_id, f"🔇 Вы замучены *на {days} дн.*", parse_mode="Markdown")
    except: pass
    try: await call.message.edit_text(f"✅ Пользователь `{target_id}` замучен на {days} дн.", parse_mode="Markdown")
    except: pass

@dp.callback_query(F.data.startswith("rwarn_"))
async def r_warn_cb(call: types.CallbackQuery):
    parts = call.data.split("_")
    target_id, rep_id = int(parts[1]), int(parts[2])
    if rep_id > 0: await db_exec("DELETE FROM reports WHERE id=?", (rep_id,))

    await db_exec("UPDATE users SET warns=COALESCE(warns,0)+1 WHERE id=?", (target_id,))
    warns = await get_warns(target_id)

    if warns >= 3:
        until = datetime.now() + timedelta(days=3)
        await db_exec("UPDATE users SET banned_until=?, warns=0 WHERE id=?", (until, target_id))
        if target_id in active_chats:
            pid = active_chats.pop(target_id)
            active_chats.pop(pid, None)
            try: await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
            except: pass
        try:
            await bot.send_message(target_id,
                "🚫 *Вы получили 3 предупреждения и автоматически заблокированы на 3 дня!*\n"
                f"Разблокировка: {until.strftime('%d.%m.%Y %H:%M')}",
                parse_mode="Markdown")
        except: pass
        try: await call.message.edit_text(f"🔨 У юзера `{target_id}` 3 варна — выдан автобан на 3 дня!", parse_mode="Markdown")
        except: pass
    else:
        try:
            await bot.send_message(target_id,
                f"⚠️ *Предупреждение от администрации!*\n"
                f"Вы нарушаете правила.\nВарнов: *{warns}/3*. При 3 варнах — автоматический бан на 3 дня.",
                parse_mode="Markdown")
        except: pass
        try: await call.message.edit_text(f"✅ Варн выдан `{target_id}`. Варнов: {warns}/3", parse_mode="Markdown")
        except: pass

@dp.callback_query(F.data.startswith("rnoban_"))
async def r_noban_cb(call: types.CallbackQuery):
    parts = call.data.split("_")
    rep_id = int(parts[2])
    if rep_id > 0: await db_exec("DELETE FROM reports WHERE id=?", (rep_id,))
    try: await call.message.edit_text("✅ Жалоба отклонена. Нарушений не выявлено.")
    except: pass

# ================================================================
# ВАРН ПО ID/НИК (из панели)
# ================================================================
@dp.callback_query(F.data == "adm_warn")
async def adm_warn_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_warn_input)
    await call.message.answer("⚠️ *Выдать варн*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_warn_input)
async def adm_warn_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = await db_exec("SELECT id,username FROM users WHERE id=?", (tid,), "one")
    except ValueError:
        row = await db_exec("SELECT id,username FROM users WHERE username=?", (raw,), "one")

    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername = row
    if tid in ADMINS:
        await message.answer("❌ Нельзя выдать варн администратору.")
        await state.clear(); return

    await db_exec("UPDATE users SET warns=COALESCE(warns,0)+1 WHERE id=?", (tid,))
    warns = await get_warns(tid)
    name = f"@{tusername}" if tusername else str(tid)

    if warns >= 3:
        until = datetime.now() + timedelta(days=3)
        await db_exec("UPDATE users SET banned_until=?, warns=0 WHERE id=?", (until, tid))
        if tid in active_chats:
            pid = active_chats.pop(tid)
            active_chats.pop(pid, None)
            try: await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
            except: pass
        try:
            await bot.send_message(tid, "🚫 *Вы получили 3 предупреждения и автоматически заблокированы на 3 дня!*", parse_mode="Markdown")
        except: pass
        await message.answer(f"🔨 {name} получил 3-й варн — выдан автобан на 3 дня!")
    else:
        try:
            await bot.send_message(tid,
                f"⚠️ *Предупреждение от администрации!*\nВарнов: *{warns}/3*. При 3 варнах — автоматический бан на 3 дня.",
                parse_mode="Markdown")
        except: pass
        await message.answer(f"✅ Варн выдан {name}. Варнов: {warns}/3")
    await state.clear()

# ================================================================
# СНЯТЬ ВАРН (из панели)
# ================================================================
@dp.callback_query(F.data == "adm_unwarn")
async def adm_unwarn_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_unwarn_input)
    await call.message.answer("🗑 *Снять варн*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_unwarn_input)
async def adm_unwarn_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = await db_exec("SELECT id,username,warns FROM users WHERE id=?", (tid,), "one")
    except ValueError:
        row = await db_exec("SELECT id,username,warns FROM users WHERE username=?", (raw,), "one")

    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername, warns = row
    warns = warns or 0
    name = f"@{tusername}" if tusername else str(tid)

    if warns <= 0:
        await message.answer(f"ℹ️ У {name} нет варнов.")
        await state.clear(); return

    new_warns = warns - 1
    await db_exec("UPDATE users SET warns=? WHERE id=?", (new_warns, tid))
    try:
        await bot.send_message(tid, f"✅ Один варн снят администрацией.\nВарнов осталось: *{new_warns}/3*", parse_mode="Markdown")
    except: pass
    await message.answer(f"✅ Варн снят с {name}. Варнов осталось: {new_warns}/3")
    await state.clear()

# ================================================================
# СПИСОК БАНОВ
# ================================================================
@dp.callback_query(F.data == "adm_banlist")
async def adm_banlist(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS: return
    now = datetime.now()
    banned = await db_exec("SELECT id,username,banned_until FROM users WHERE banned_until > ? ORDER BY banned_until DESC LIMIT 10", (now,), "all")
    muted  = await db_exec("SELECT id,username,muted_until FROM users WHERE muted_until > ? ORDER BY muted_until DESC LIMIT 10", (now,), "all")
    warned = await db_exec("SELECT id,username,warns FROM users WHERE warns > 0 ORDER BY warns DESC LIMIT 10", fetch="all")

    txt = "📋 *Активные наказания*\n\n🔨 *Забаненные:*\n"
    if banned:
        for r in banned:
            t = r[2].strftime('%d.%m.%Y')
            txt += f"• `{r[0]}` @{r[1] or '—'} до {t}\n"
    else:
        txt += "Нет\n"

    txt += "\n🔇 *Замученные:*\n"
    if muted:
        for r in muted:
            t = r[2].strftime('%d.%m.%Y')
            txt += f"• `{r[0]}` @{r[1] or '—'} до {t}\n"
    else:
        txt += "Нет\n"

    txt += "\n⚠️ *С варнами:*\n"
    if warned:
        for r in warned:
            txt += f"• `{r[0]}` @{r[1] or '—'} — {r[2]}/3\n"
    else:
        txt += "Нет\n"

    await call.message.answer(txt, parse_mode="Markdown")
    await call.answer()

# ================================================================
# ПОИСК / ПРОСМОТР ЮЗЕРА (ADMIN)
# ================================================================
@dp.callback_query(F.data == "adm_lookup")
async def adm_lookup_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_lookup_user)
    await call.message.answer("🔍 *Найти пользователя*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_lookup_user)
async def adm_lookup_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = await db_exec("SELECT id,username,refs,prem_until,gender,age,banned_until,muted_until,warns FROM users WHERE id=?", (tid,), "one")
    except ValueError:
        row = await db_exec("SELECT id,username,refs,prem_until,gender,age,banned_until,muted_until,warns FROM users WHERE username=?", (raw,), "one")

    if not row:
        await message.answer("❌ Пользователь не найден в базе.")
        await state.clear(); return

    uid2, username, refs, prem_until, gender, age, banned_until, muted_until, warns = row
    now = datetime.now()

    rank = await get_rank(uid2)
    gender_str = {"М": "👨 Мужской", "Ж": "👩 Женский"}.get(gender, "—")
    warns = warns or 0

    prem_str = "❌ Нет"
    if prem_until:
        prem_str = f"✅ до {prem_until.strftime('%d.%m.%Y')}" if prem_until > now else "❌ Истёк"

    ban_str = "—"
    if banned_until and banned_until > now:
        ban_str = f"🔨 до {banned_until.strftime('%d.%m.%Y %H:%M')}"

    mute_str = "—"
    if muted_until and muted_until > now:
        mute_str = f"🔇 до {muted_until.strftime('%d.%m.%Y %H:%M')}"

    in_chat = "💬 В чате" if uid2 in active_chats else "🔴 Не в чате"

    txt = (
        f"🔍 *Профиль пользователя*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: `{uid2}`\n"
        f"👤 Ник: @{username or '—'}\n"
        f"🚻 Пол: {gender_str}\n"
        f"🎂 Возраст: {age or '—'}\n"
        f"🎖 Ранг: {rank}\n"
        f"💎 Premium: {prem_str}\n"
        f"👥 Рефералов: {refs or 0}\n"
        f"⚠️ Варнов: {warns}/3\n"
        f"🔨 Бан: {ban_str}\n"
        f"🔇 Мут: {mute_str}\n"
        f"📡 Статус: {in_chat}\n"
        f"━━━━━━━━━━━━━━━━━"
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

@dp.callback_query(F.data.startswith("quick_"))
async def quick_action_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS: return
    parts = call.data.split("_")
    action = parts[1]
    tid = int(parts[2])

    if action == "warn":
        if tid in ADMINS:
            await call.answer("❌ Нельзя варнить администратора!", show_alert=True); return
        await db_exec("UPDATE users SET warns=COALESCE(warns,0)+1 WHERE id=?", (tid,))
        warns = await get_warns(tid)
        if warns >= 3:
            until = datetime.now() + timedelta(days=3)
            await db_exec("UPDATE users SET banned_until=?, warns=0 WHERE id=?", (until, tid))
            if tid in active_chats:
                pid = active_chats.pop(tid)
                active_chats.pop(pid, None)
                try: await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
                except: pass
            try: await bot.send_message(tid, "🚫 *Вы получили 3 предупреждения и автоматически заблокированы на 3 дня!*", parse_mode="Markdown")
            except: pass
            await call.answer(f"🔨 3 варна → автобан 3 дня!", show_alert=True)
        else:
            try: await bot.send_message(tid, f"⚠️ *Предупреждение от администрации!*\nВарнов: *{warns}/3*.", parse_mode="Markdown")
            except: pass
            await call.answer(f"✅ Варн выдан. Варнов: {warns}/3", show_alert=True)

    elif action == "unwarn":
        warns = await get_warns(tid)
        if warns <= 0:
            await call.answer("ℹ️ Варнов нет.", show_alert=True); return
        await db_exec("UPDATE users SET warns=warns-1 WHERE id=?", (tid,))
        new = warns - 1
        try: await bot.send_message(tid, f"✅ Один варн снят. Осталось: *{new}/3*", parse_mode="Markdown")
        except: pass
        await call.answer(f"✅ Варн снят. Осталось: {new}/3", show_alert=True)

    elif action == "ban":
        until = datetime.now() + timedelta(days=3)
        await db_exec("UPDATE users SET banned_until=? WHERE id=?", (until, tid))
        if tid in active_chats:
            pid = active_chats.pop(tid)
            active_chats.pop(pid, None)
            try: await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
            except: pass
        try: await bot.send_message(tid, "🔨 Вы заблокированы *на 3 дня* администрацией.", parse_mode="Markdown")
        except: pass
        await call.answer("✅ Забанен на 3 дня.", show_alert=True)

    elif action == "unban":
        await db_exec("UPDATE users SET banned_until=NULL WHERE id=?", (tid,))
        try: await bot.send_message(tid, "✅ Вы разблокированы. Добро пожаловать обратно!")
        except: pass
        await call.answer("✅ Разбанен.", show_alert=True)

    elif action == "mute":
        until = datetime.now() + timedelta(days=1)
        await db_exec("UPDATE users SET muted_until=? WHERE id=?", (until, tid))
        try: await bot.send_message(tid, "🔇 Вы замучены *на 1 день* администрацией.", parse_mode="Markdown")
        except: pass
        await call.answer("✅ Замучен на 1 день.", show_alert=True)

    elif action == "unmute":
        await db_exec("UPDATE users SET muted_until=NULL WHERE id=?", (tid,))
        try: await bot.send_message(tid, "🔊 Мут снят!")
        except: pass
        await call.answer("✅ Размучен.", show_alert=True)

# ================================================================
# СБРОСИТЬ ВСЕ ВАРНЫ (ADMIN)
# ================================================================
@dp.callback_query(F.data == "adm_reset_warns")
async def adm_reset_warns_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_reset_warns)
    await call.message.answer("🔄 *Сбросить все варны*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_reset_warns)
async def adm_reset_warns_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = await db_exec("SELECT id,username,warns FROM users WHERE id=?", (tid,), "one")
    except ValueError:
        row = await db_exec("SELECT id,username,warns FROM users WHERE username=?", (raw,), "one")

    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername, warns = row
    warns = warns or 0
    name = f"@{tusername}" if tusername else str(tid)
    await db_exec("UPDATE users SET warns=0 WHERE id=?", (tid,))
    try:
        await bot.send_message(tid, "✅ Все ваши предупреждения были сброшены администрацией. Начните с чистого листа!")
    except: pass
    await message.answer(f"✅ Все варны ({warns}) сброшены у {name}.")
    await state.clear()

# ================================================================
# СНЯТЬ PREMIUM (ADMIN)
# ================================================================
@dp.callback_query(F.data == "adm_revoke_prem")
async def adm_revoke_prem_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_revoke_prem)
    await call.message.answer("❌ *Снять Premium*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_revoke_prem)
async def adm_revoke_prem_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = await db_exec("SELECT id,username,prem_until FROM users WHERE id=?", (tid,), "one")
    except ValueError:
        row = await db_exec("SELECT id,username,prem_until FROM users WHERE username=?", (raw,), "one")

    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername, prem_until = row
    name = f"@{tusername}" if tusername else str(tid)

    if not prem_until or prem_until <= datetime.now():
        await message.answer(f"ℹ️ У {name} нет активного Premium.")
        await state.clear(); return

    await db_exec("UPDATE users SET prem_until=NULL WHERE id=?", (tid,))
    try:
        await bot.send_message(tid, "❌ Ваш Premium был отозван администрацией.")
    except: pass
    await message.answer(f"✅ Premium снят у {name}.")
    await state.clear()

# ================================================================
# СООБЩЕНИЕ КОНКРЕТНОМУ ЮЗЕРУ
# ================================================================
@dp.callback_query(F.data == "adm_msg_user")
async def adm_msg_user_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_msg_user)
    await call.message.answer(
        "✉️ *Сообщение юзеру*\nВведите ID или @username, затем через пробел текст.\n"
        "Пример: `123456789 Привет!`", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_msg_user)
async def adm_msg_user_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    parts = message.text.strip().split(" ", 1)
    if len(parts) < 2:
        await message.answer("❌ Формат: ID/username пробел текст")
        await state.clear(); return

    raw, text = parts[0].lstrip("@"), parts[1]
    row = None
    try:
        tid = int(raw)
        row = await db_exec("SELECT id,username FROM users WHERE id=?", (tid,), "one")
    except ValueError:
        row = await db_exec("SELECT id,username FROM users WHERE username=?", (raw,), "one")

    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername = row
    try:
        await bot.send_message(tid, f"📩 *Сообщение от администрации:*\n\n{text}", parse_mode="Markdown")
        name = f"@{tusername}" if tusername else str(tid)
        await message.answer(f"✅ Сообщение отправлено {name}.")
    except:
        await message.answer("❌ Не удалось отправить — юзер заблокировал бота.")
    await state.clear()

# ================================================================
# БАН ПО ID
# ================================================================
@dp.callback_query(F.data == "adm_ban")
async def adm_ban_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_ban_input)
    kb = InlineKeyboardBuilder()
    kb.button(text="1 день",   callback_data="banperiod_1")
    kb.button(text="7 дней",   callback_data="banperiod_7")
    kb.button(text="30 дней",  callback_data="banperiod_30")
    kb.button(text="Навсегда", callback_data="banperiod_999")
    await call.message.answer("🔨 *Бан пользователя*\nВыберите срок:", reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("banperiod_"))
async def adm_ban_period(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    days = call.data.split("_")[1]
    await state.update_data(ban_days=days)
    label = "навсегда" if days == "999" else f"{days} дн."
    await call.message.answer(f"Срок: *{label}*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_ban_input)
async def adm_ban_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    data = await state.get_data()
    days_str = data.get("ban_days")
    if not days_str:
        await message.answer("Сначала выберите срок."); return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = await db_exec("SELECT id,username FROM users WHERE id=?", (tid,), "one")
    except ValueError:
        row = await db_exec("SELECT id,username FROM users WHERE username=?", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername = row
    days = int(days_str)
    if days == 999:
        until = datetime.now() + timedelta(days=36500)
        label, msg = "навсегда", "⛔ Вы заблокированы *навсегда* администрацией."
    else:
        until = datetime.now() + timedelta(days=days)
        label = f"на {days} дн."
        msg = f"🔨 Вы заблокированы *на {days} дн.*\nРазблокировка: {until.strftime('%d.%m.%Y %H:%M')}"

    await db_exec("UPDATE users SET banned_until=? WHERE id=?", (until, tid))
    if tid in active_chats:
        pid = active_chats.pop(tid)
        active_chats.pop(pid, None)
        try: await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
        except: pass
    try: await bot.send_message(tid, msg, parse_mode="Markdown")
    except: pass
    name = f"@{tusername}" if tusername else str(tid)
    await message.answer(f"✅ {name} заблокирован {label}.")
    await state.clear()

# ================================================================
# МУТ ПО ID
# ================================================================
@dp.callback_query(F.data == "adm_mute")
async def adm_mute_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_mute_input)
    kb = InlineKeyboardBuilder()
    kb.button(text="1 день",   callback_data="muteperiod_1")
    kb.button(text="7 дней",   callback_data="muteperiod_7")
    kb.button(text="30 дней",  callback_data="muteperiod_30")
    kb.button(text="Навсегда", callback_data="muteperiod_999")
    await call.message.answer("🔇 *Мут пользователя*\nВыберите срок:", reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("muteperiod_"))
async def adm_mute_period(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    days = call.data.split("_")[1]
    await state.update_data(mute_days=days)
    label = "навсегда" if days == "999" else f"{days} дн."
    await call.message.answer(f"Срок: *{label}*\nВведите ID или @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_mute_input)
async def adm_mute_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    data = await state.get_data()
    days_str = data.get("mute_days")
    if not days_str:
        await message.answer("Сначала выберите срок."); return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = await db_exec("SELECT id,username FROM users WHERE id=?", (tid,), "one")
    except ValueError:
        row = await db_exec("SELECT id,username FROM users WHERE username=?", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername = row
    days = int(days_str)
    if days == 999:
        until = datetime.now() + timedelta(days=36500)
        label, msg = "навсегда", "🔇 Вы замучены *навсегда*."
    else:
        until = datetime.now() + timedelta(days=days)
        label = f"на {days} дн."
        msg = f"🔇 Вы замучены *на {days} дн.*\nОкончание: {until.strftime('%d.%m.%Y %H:%M')}"

    await db_exec("UPDATE users SET muted_until=? WHERE id=?", (until, tid))
    try: await bot.send_message(tid, msg, parse_mode="Markdown")
    except: pass
    name = f"@{tusername}" if tusername else str(tid)
    await message.answer(f"✅ {name} замучен {label}.")
    await state.clear()

# ================================================================
# РАЗБАН
# ================================================================
@dp.callback_query(F.data == "adm_unban_id")
async def adm_unban_id_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.update_data(unban_mode="id")
    await state.set_state(States.admin_unban_id)
    await call.message.answer("🔓 *Разбан по ID*\nВведите числовой ID:", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "adm_unban_un")
async def adm_unban_un_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.update_data(unban_mode="username")
    await state.set_state(States.admin_unban_id)
    await call.message.answer("🔓 *Разбан по нику*\nВведите @username (без @):", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_unban_id)
async def adm_unban_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    data = await state.get_data()
    mode = data.get("unban_mode", "id")
    raw  = message.text.strip().lstrip("@")
    row  = None
    if mode == "id":
        try:
            tid = int(raw)
            row = await db_exec("SELECT id,username FROM users WHERE id=?", (tid,), "one")
        except ValueError:
            await message.answer("❌ Введите корректный числовой ID.")
            await state.clear(); return
    else:
        row = await db_exec("SELECT id,username FROM users WHERE username=?", (raw,), "one")

    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername = row
    await db_exec("UPDATE users SET banned_until=NULL WHERE id=?", (tid,))
    try: await bot.send_message(tid, "✅ Вы были разблокированы администрацией. Добро пожаловать обратно!")
    except: pass
    name = f"@{tusername}" if tusername else str(tid)
    await message.answer(f"✅ {name} разблокирован.")
    await state.clear()

# ================================================================
# РАЗМУТ
# ================================================================
@dp.callback_query(F.data == "adm_unmute_id")
async def adm_unmute_id_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.update_data(unmute_mode="id")
    await state.set_state(States.admin_unmute_id)
    await call.message.answer("🔊 *Размут по ID*\nВведите числовой ID:", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "adm_unmute_un")
async def adm_unmute_un_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.update_data(unmute_mode="username")
    await state.set_state(States.admin_unmute_id)
    await call.message.answer("🔊 *Размут по нику*\nВведите @username (без @):", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_unmute_id)
async def adm_unmute_proc(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    data = await state.get_data()
    mode = data.get("unmute_mode", "id")
    raw  = message.text.strip().lstrip("@")
    row  = None
    if mode == "id":
        try:
            tid = int(raw)
            row = await db_exec("SELECT id,username FROM users WHERE id=?", (tid,), "one")
        except ValueError:
            await message.answer("❌ Введите корректный числовой ID.")
            await state.clear(); return
    else:
        row = await db_exec("SELECT id,username FROM users WHERE username=?", (raw,), "one")

    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return

    tid, tusername = row
    await db_exec("UPDATE users SET muted_until=NULL WHERE id=?", (tid,))
    try: await bot.send_message(tid, "🔊 Мут снят. Вы снова можете писать в чате!")
    except: pass
    name = f"@{tusername}" if tusername else str(tid)
    await message.answer(f"✅ {name} размучен.")
    await state.clear()

# ================================================================
# ОТВЕТ АДМИНИСТРАТОРА
# ================================================================
@dp.callback_query(F.data.startswith("reply_"))
async def adm_reply_start(call: types.CallbackQuery, state: FSMContext):
    target_id = call.data.split("_")[1]
    await state.update_data(rep_to=target_id)
    await call.message.answer(f"✏️ Пишите ответ для `{target_id}`:", parse_mode="Markdown")
    await state.set_state(States.admin_reply)
    await call.answer()

@dp.message(States.admin_reply)
async def adm_reply_send(message: types.Message, state: FSMContext):
    if message.from_user.id in active_chats:
        await state.clear(); return
    data = await state.get_data()
    target = data.get("rep_to")
    try:
        await bot.send_message(target, f"📩 *Ответ от поддержки:*\n\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Ответ отправлен.")
        await state.clear()
    except:
        await message.answer("❌ Не удалось отправить.")

# ================================================================
# СТАТИСТИКА
# ================================================================
@dp.callback_query(F.data == "a_stats")
async def a_stats_cb(call: types.CallbackQuery):
    now = datetime.now()
    all_ids = await db_exec("SELECT id FROM users", fetch="all")
    active_count = 0
    removed_ids = []
    for row in all_ids:
        uid = row[0]
        try:
            await bot.get_chat(uid)
            active_count += 1
        except:
            removed_ids.append(uid)
    for uid in removed_ids:
        await db_exec("DELETE FROM users WHERE id=?", (uid,))

    prem_c_row = await db_exec("SELECT COUNT(*) FROM users WHERE prem_until > ?", (now,), "one")
    ban_c_row  = await db_exec("SELECT COUNT(*) FROM users WHERE banned_until > ?", (now,), "one")
    mute_c_row = await db_exec("SELECT COUNT(*) FROM users WHERE muted_until > ?", (now,), "one")
    warn_c_row = await db_exec("SELECT COUNT(*) FROM users WHERE warns > 0", fetch="one")
    rep_c_row  = await db_exec("SELECT COUNT(*) FROM reports", fetch="one")

    prem_c = prem_c_row[0] if prem_c_row else 0
    ban_c  = ban_c_row[0] if ban_c_row else 0
    mute_c = mute_c_row[0] if mute_c_row else 0
    warn_c = warn_c_row[0] if warn_c_row else 0
    rep_c  = rep_c_row[0] if rep_c_row else 0
    online = len(active_chats) // 2

    await call.message.answer(
        f"📊 *Статистика бота*\n\n"
        f"👥 Всего юзеров: {active_count}\n"
        f"💎 Premium: {prem_c}\n"
        f"🚫 Забаненных: {ban_c}\n"
        f"🔇 Замученных: {mute_c}\n"
        f"⚠️ С варнами: {warn_c}\n"
        f"🚩 Жалоб в очереди: {rep_c}\n"
        f"💬 Активных чатов: {online}",
        parse_mode="Markdown"
    )
    await call.answer()

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
    cat = call.data.split("_")[1]
    if cat == "VIP" and not await is_prem(uid):
        await call.answer("💎 VIP-чат доступен только для Premium-пользователей!", show_alert=True)
        return
    await state.clear()
    try: await call.message.delete()
    except: pass
    await enter_queue(uid, cat)

@dp.callback_query(F.data == "stop_q")
async def stop_q_cb(call: types.CallbackQuery):
    uid = call.from_user.id
    for k in queues:
        if uid in queues[k]: queues[k].remove(uid)
    try: await call.message.edit_text("❌ Поиск отменён.")
    except: pass

# ================================================================
# ПОКУПКА PREMIUM
# ================================================================
@dp.callback_query(F.data.startswith("buy_"))
async def buy_cb(call: types.CallbackQuery, state: FSMContext):
    days   = call.data.split("_")[1]
    prices = {"1": "25 грн", "30": "100 грн", "999": "200 грн"}
    price  = prices.get(days, "?")
    await state.update_data(chosen_days=days)
    await call.message.edit_text(
        f"💳 Карта: `4874070057830877`\nСумма: *{price}*\n\nПосле оплаты отправьте скриншот чека сюда 👇",
        parse_mode="Markdown"
    )
    await state.set_state(States.wait_proof)

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
            cur_row = await db_exec("SELECT prem_until FROM users WHERE id=?", (target_id,), "one")
            cur = cur_row[0] if cur_row else None
            base = datetime.now()
            if cur and cur > base:
                base = cur
            until = base + timedelta(days=days)
            msg = f"💎 *Premium на {days} дней!*\nДо: {until.strftime('%d.%m.%Y')}"
        await db_exec("UPDATE users SET prem_until=? WHERE id=?", (until, target_id))
        try: await bot.send_message(target_id, msg, parse_mode="Markdown")
        except: pass
        try: await call.message.edit_caption(caption=f"✅ Оплата подтверждена для {target_id}.")
        except: await call.message.edit_text(f"✅ Оплата подтверждена для {target_id}.")
    else:
        try: await bot.send_message(target_id, "❌ Ваша оплата отклонена. Обратитесь в поддержку.")
        except: pass
        try: await call.message.edit_caption(caption=f"❌ Оплата отклонена для {target_id}.")
        except: await call.message.edit_text(f"❌ Оплата отклонена для {target_id}.")

# ================================================================
# ТЕХПОДДЕРЖКА (ЮЗЕРЫ)
# ================================================================
@dp.callback_query(F.data == "open_support")
async def open_support_cb(call: types.CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    banned, until = await is_banned(uid)
    if banned:
        await call.answer(f"Вы заблокированы до {until}", show_alert=True); return
    await state.set_state(States.user_tech_support)
    await call.message.answer(
        "📝 *Опишите вашу проблему:*\n\nНапишите сообщение, и мы передадим его администраторам.",
        parse_mode="Markdown"
    )
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
                f"👤 @{username} | ID: `{uid}` | {rank}\n\n"
                f"💬 Сообщение:\n{text}",
                reply_markup=kb.as_markup(),
                parse_mode="Markdown"
            )
        except: pass

    await message.answer("✅ *Ваше обращение отправлено!*\nОжидайте ответа от администратора.", parse_mode="Markdown")
    await state.clear()

# ================================================================
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК
# ================================================================
@dp.message()
async def global_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    cur_state = await state.get_state()

    if cur_state == States.wait_proof and message.photo:
        data = await state.get_data()
        days = data.get("chosen_days", "30")
        for a in ADMINS:
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Подтвердить", callback_data=f"pay_yes_{uid}_{days}")
            kb.button(text="❌ Отказать",    callback_data=f"pay_no_{uid}")
            await bot.send_photo(a, message.photo[-1].file_id,
                caption=f"💳 Чек на *{days} дн.* от `{uid}`",
                reply_markup=kb.as_markup(), parse_mode="Markdown")
        await message.answer("✅ Чек отправлен на проверку!")
        await state.clear()
        return

    banned, until = await is_banned(uid)
    if banned:
        await message.answer(f"🚫 Вы заблокированы до *{until}*.\nОбратитесь в поддержку.", parse_mode="Markdown")
        return

    if uid in active_chats:
        pid = active_chats[uid]
        muted, muted_until = await is_muted(uid)
        if muted:
            await message.answer(f"🔇 Вы замучены до *{muted_until}*. Вы не можете писать в чате.", parse_mode="Markdown")
            return
        if message.text:
            last_messages[uid] = f"[текст]: {message.text}"
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
        try: await bot.copy_message(pid, uid, message.message_id)
        except: pass
        return

    # ---- ГЛАВНОЕ МЕНЮ ----
    elif message.text == "👨‍💻 Поддержка":
        kb = InlineKeyboardBuilder()
        kb.button(text="📝 Написать в поддержку", callback_data="open_support")
        await message.answer(
            "👨‍💻 *Техническая поддержка*\n\n"
            "Нажмите кнопку ниже и опишите вашу проблему.\n"
            "Администраторы ответят вам в ближайшее время.",
            reply_markup=kb.as_markup(), parse_mode="Markdown"
        )

    elif message.text == "🔎 Поиск":
        if await is_prem(uid):
            kb = InlineKeyboardBuilder()
            kb.button(text="Все",         callback_data="q_all")
            kb.button(text="Девушки 👩",  callback_data="q_Ж")
            kb.button(text="Парни 👨",    callback_data="q_М")
            kb.button(text="До 18 лет",   callback_data="q_<18")
            kb.button(text="18+ лет",     callback_data="q_18+")
            kb.button(text="25+ лет",     callback_data="q_25+")
            kb.button(text="💎 VIP-чат",  callback_data="q_VIP")
            await message.answer(
                "💎 *Premium Поиск*\nВыбери критерий:\n\n"
                "✨ *VIP-чат* — только для Premium-пользователей!",
                reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown"
            )
        else:
            await enter_queue(uid, "all")

    elif message.text == "👤 Профиль":
        u = await db_exec("SELECT * FROM users WHERE id=?", (uid,), "one")
        if not u:
            await message.answer("Сначала пройди регистрацию через /start")
            return
        p_status = "✅ Активен" if await is_prem(uid) else "❌ Не активен"
        rank = await get_rank(uid)
        warns = await get_warns(uid)
        kb = InlineKeyboardBuilder()
        kb.button(text="✏️ Редактировать профиль", callback_data="edit_profile")
        await message.answer(
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"👤 *ВАШ ПРОФИЛЬ*\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"🆔 Твой ID: `{uid}`\n"
            f"🎖 Ранг: {rank}\n"
            f"💎 Premium: {p_status}\n"
            f"🤝 Рефералов: {u['refs']}\n"
            f"🚻 Пол: {u['gender'] or '—'} | 🎂 Возраст: {u['age'] or '—'}\n"
            f"⚠️ Варнов: {warns}/3\n"
            f"➖➖➖➖➖➖➖➖➖➖",
            reply_markup=kb.as_markup(), parse_mode="Markdown"
        )

    elif message.text == "🏆 ТОП":
        top = await db_exec("SELECT username,refs FROM users ORDER BY refs DESC LIMIT 5", fetch="all")
        txt = "🏆 *ЛИДЕРЫ РЕФЕРАЛОВ*\n\n"
        for i, r in enumerate(top, 1):
            txt += f"{i}. {r[0] or 'User'} — {r[1]} чел.\n"
        await message.answer(txt, parse_mode="Markdown")

    elif message.text == "💎 Реферал":
        me   = await bot.get_me()
        u    = await db_exec("SELECT refs FROM users WHERE id=?", (uid,), "one")
        refs = u[0] if u else 0
        await message.answer(
            f"🎁 *Реферальная программа*\n\n"
            f"👥 Ты пригласил: *{refs}* человек\n"
            f"🔥 За каждые *10 приглашённых* — *2 дня Premium*!\n\n"
            f"🔗 Твоя ссылка:\n`https://t.me/{me.username}?start={uid}`",
            parse_mode="Markdown"
        )

    elif message.text == "👑 Купить Premium":
        kb = InlineKeyboardBuilder()
        kb.button(text="1 день — 25 грн",    callback_data="buy_1")
        kb.button(text="30 дней — 100 грн",  callback_data="buy_30")
        kb.button(text="Навсегда — 200 грн", callback_data="buy_999")
        await message.answer(
            "💎 *Выбери тариф:*\n\n"
            "🎁 *Premium возможности:*\n"
            "• Поиск по полу и возрасту\n"
            "• Видно варны и ранг собеседника\n"
            "• 💎 VIP-чат — только среди Premium\n"
            "• Значок 💎 в профиле\n"
            "• Приоритет в поиске",
            reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown"
        )

# ================================================================
# ЗАПУСК
# ================================================================
async def main():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

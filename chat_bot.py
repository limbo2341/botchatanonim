import asyncio
import logging
import os
from datetime import datetime, timedelta

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- КОНФИГ ---
TOKEN = "8784182805:AAGk8Tw2Kan-Yj-Jxq_YujXqCMFcKYUWp-M"
ADMINS = [8528807150, 7245932902, 8784182805]
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:srMRgTqBOApXqLhjLXXOTUvhnBVEoIZY@yamabiko.proxy.rlwy.net:49845/railway"
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp  = Dispatcher()

# ================================================================
# БАЗА ДАННЫХ (asyncpg)
# ================================================================
db_pool: asyncpg.Pool = None

async def get_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, ssl="require")
    return db_pool

async def db_exec(sql, *params, fetch="none"):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if fetch == "one":
            return await conn.fetchrow(sql, *params)
        if fetch == "all":
            return await conn.fetch(sql, *params)
        await conn.execute(sql, *params)

async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           BIGINT PRIMARY KEY,
                username     TEXT,
                refs         INTEGER DEFAULT 0,
                prem_until   TIMESTAMP,
                gender       TEXT,
                age          TEXT,
                banned_until TIMESTAMP,
                muted_until  TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id           SERIAL PRIMARY KEY,
                reporter_id  BIGINT,
                target_id    BIGINT,
                last_message TEXT,
                created_at   TIMESTAMP DEFAULT NOW()
            )
        """)

# ================================================================
# ХЕЛПЕРЫ
# ================================================================
async def is_prem(uid):
    if uid in ADMINS: return True
    r = await db_exec("SELECT prem_until FROM users WHERE id=$1", uid, fetch="one")
    return bool(r and r['prem_until'] and r['prem_until'] > datetime.now())

async def is_banned(uid):
    if uid in ADMINS: return False, None
    r = await db_exec("SELECT banned_until FROM users WHERE id=$1", uid, fetch="one")
    if r and r['banned_until']:
        if r['banned_until'] > datetime.now():
            return True, r['banned_until'].strftime("%d.%m.%Y %H:%M")
        await db_exec("UPDATE users SET banned_until=NULL WHERE id=$1", uid)
    return False, None

async def is_muted(uid):
    if uid in ADMINS: return False, None
    r = await db_exec("SELECT muted_until FROM users WHERE id=$1", uid, fetch="one")
    if r and r['muted_until']:
        if r['muted_until'] > datetime.now():
            return True, r['muted_until'].strftime("%d.%m.%Y %H:%M")
        await db_exec("UPDATE users SET muted_until=NULL WHERE id=$1", uid)
    return False, None

async def get_user_info(uid):
    r = await db_exec("SELECT username, gender, age FROM users WHERE id=$1", uid, fetch="one")
    if not r:
        return f"🆔 ID: `{uid}`\nИнфо не найдено"
    username = r['username']
    gender   = r['gender']
    age      = r['age']
    prem     = "💎 Premium" if await is_prem(uid) else "Обычный"
    gmap     = {"М": "👨 Мужской", "Ж": "👩 Женский"}
    gender_s = gmap.get(gender, "—")
    return (
        f"🆔 ID: `{uid}`\n"
        f"👤 Ник: @{username or '—'}\n"
        f"🚻 Пол: {gender_s}\n"
        f"🎂 Возраст: {age or '—'}\n"
        f"⭐ Статус: {prem}"
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
    kb.row(types.KeyboardButton(text="👨‍💻 Поддержка"))
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
# СОСТОЯНИЯ
# ================================================================
class States(StatesGroup):
    broadcasting     = State()
    giving_prem_id   = State()
    wait_proof       = State()
    tech_support     = State()
    admin_reply      = State()
    admin_ban_input  = State()
    admin_mute_input = State()

# ================================================================
# ЛОГИКА ПОИСКА
# ================================================================
active_chats  = {}
last_messages = {}
queues = {"all":[], "М":[], "Ж":[], "Music":[], "Games":[], "Anime":[], "Code":[]}

async def enter_queue(uid, cat):
    if uid in active_chats: return
    for k in queues:
        if uid in queues[k]: queues[k].remove(uid)
    lst = queues.get(cat, [])
    if lst:
        pid = lst.pop(0)
        if pid == uid:
            queues[cat].append(uid)
            return
        active_chats[uid] = pid
        active_chats[pid] = uid
        last_messages[uid] = None
        last_messages[pid] = None
        await bot.send_message(
            uid,
            f"🎁 *Собеседник найден!*\n\n{await get_user_info(pid)}",
            reply_markup=chat_kb(), parse_mode="Markdown"
        )
        await bot.send_message(
            pid,
            f"🎁 *Собеседник найден!*\n\n{await get_user_info(uid)}",
            reply_markup=chat_kb(), parse_mode="Markdown"
        )
    else:
        queues[cat] = [uid]
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
    await bot.send_message(pid, "💔 Собеседник перешёл к следующему.", reply_markup=main_kb(pid))
    await message.answer("🔎 Ищем нового собеседника...", reply_markup=main_kb(uid))
    await enter_queue(uid, "all")

@dp.message(StateFilter("*"), F.text == "🚩 Пожаловаться")
async def report_msg(message: types.Message):
    uid = message.from_user.id
    if uid not in active_chats:
        await message.answer("Вы не в чате.")
        return
    pid      = active_chats[uid]
    last_msg = last_messages.get(pid, "—")
    await db_exec(
        "INSERT INTO reports(reporter_id, target_id, last_message) VALUES($1,$2,$3)",
        uid, pid, last_msg
    )
    for a in ADMINS:
        kb = InlineKeyboardBuilder()
        kb.button(text="🚫 Бан 1д",   callback_data=f"ban_{pid}_1")
        kb.button(text="🚫 Бан 7д",   callback_data=f"ban_{pid}_7")
        kb.button(text="🔇 Мут 1ч",   callback_data=f"mute_{pid}_1")
        kb.button(text="✅ Ок",        callback_data=f"rep_ok_{pid}")
        await bot.send_message(
            a,
            f"🚩 *Жалоба*\nОт: `{uid}`\nНа: `{pid}`\nПоследнее: {last_msg}",
            reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown"
        )
    await message.answer("✅ Жалоба отправлена.")

# ================================================================
# START
# ================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid      = message.from_user.id
    username = message.from_user.username or ""
    args     = message.text.split()
    ref_id   = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    existing = await db_exec("SELECT id FROM users WHERE id=$1", uid, fetch="one")
    if not existing:
        await db_exec(
            "INSERT INTO users(id, username) VALUES($1,$2) ON CONFLICT DO NOTHING",
            uid, username
        )
        if ref_id and ref_id != uid:
            await db_exec("UPDATE users SET refs=refs+1 WHERE id=$1", ref_id)
            ref_count = await db_exec("SELECT refs FROM users WHERE id=$1", ref_id, fetch="one")
            if ref_count and ref_count['refs'] % 10 == 0:
                until = datetime.now() + timedelta(days=2)
                await db_exec(
                    "UPDATE users SET prem_until=GREATEST(COALESCE(prem_until,NOW()), $1) WHERE id=$2",
                    until, ref_id
                )
                try:
                    await bot.send_message(ref_id, "🎁 +2 дня Premium за рефералов!")
                except:
                    pass

    kb = InlineKeyboardBuilder()
    kb.button(text="👨 Я парень", callback_data="gender_М")
    kb.button(text="👩 Я девушка", callback_data="gender_Ж")
    await message.answer(
        "👋 *Добро пожаловать в анонимный чат!*\n\nВыбери свой пол:",
        reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("gender_"))
async def set_gender(call: types.CallbackQuery):
    uid    = call.from_user.id
    gender = call.data.split("_")[1]
    await db_exec("UPDATE users SET gender=$1 WHERE id=$2", gender, uid)
    kb = InlineKeyboardBuilder()
    for age in ["14-17", "18-21", "22-25", "26-35", "35+"]:
        kb.button(text=age, callback_data=f"age_{age}")
    await call.message.edit_text("🎂 Теперь выбери возраст:", reply_markup=kb.adjust(3).as_markup())

@dp.callback_query(F.data.startswith("age_"))
async def set_age(call: types.CallbackQuery):
    uid = call.from_user.id
    age = call.data.split("_", 1)[1]
    await db_exec("UPDATE users SET age=$1 WHERE id=$2", age, uid)
    await call.message.edit_text("✅ Профиль заполнен!")
    await bot.send_message(uid, "🏠 *Главное меню*", reply_markup=main_kb(uid), parse_mode="Markdown")

# ================================================================
# ПОДДЕРЖКА
# ================================================================
@dp.message(F.text == "👨‍💻 Поддержка")
async def support_btn(message: types.Message, state: FSMContext):
    await state.set_state(States.tech_support)
    await message.answer("✍️ Напиши своё сообщение, и мы передадим его администраторам.")

@dp.message(States.tech_support)
async def support_msg(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    for a in ADMINS:
        kb = InlineKeyboardBuilder()
        kb.button(text="↩️ Ответить", callback_data=f"reply_{uid}")
        await bot.send_message(
            a,
            f"📩 *Поддержка от* `{uid}`:\n{message.text}",
            reply_markup=kb.as_markup(), parse_mode="Markdown"
        )
    await state.clear()
    await message.answer("✅ Сообщение отправлено!", reply_markup=main_kb(uid))

@dp.callback_query(F.data.startswith("reply_"))
async def admin_reply_cb(call: types.CallbackQuery, state: FSMContext):
    target = int(call.data.split("_")[1])
    await state.update_data(reply_target=target)
    await state.set_state(States.admin_reply)
    await call.message.answer(f"✍️ Напиши ответ для `{target}`:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_reply)
async def admin_reply_send(message: types.Message, state: FSMContext):
    data   = await state.get_data()
    target = data.get("reply_target")
    try:
        await bot.send_message(target, f"📨 *Ответ от поддержки:*\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Ответ отправлен.")
    except:
        await message.answer("❌ Не удалось отправить.")
    await state.clear()

# ================================================================
# ИНТЕРЕСЫ
# ================================================================
@dp.message(F.text == "🎭 По интересам")
async def interests_btn(message: types.Message):
    kb = InlineKeyboardBuilder()
    for cat in ["Music", "Games", "Anime", "Code"]:
        kb.button(text=cat, callback_data=f"q_{cat}")
    await message.answer("🎭 Выбери интерес:", reply_markup=kb.adjust(2).as_markup())

# ================================================================
# АДМИН ПАНЕЛЬ
# ================================================================
@dp.message(F.text == "⚙️ Админ Панель")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMINS: return
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика",   callback_data="a_stats")
    kb.button(text="📢 Рассылка",     callback_data="a_broadcast")
    kb.button(text="💎 Дать Premium", callback_data="a_give_prem")
    kb.button(text="🚫 Бан",          callback_data="a_ban")
    kb.button(text="🔇 Мут",          callback_data="a_mute")
    await message.answer("⚙️ *Админ Панель*", reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "a_broadcast")
async def a_broadcast_cb(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.broadcasting)
    await call.message.answer("📢 Напиши текст рассылки:")
    await call.answer()

@dp.message(States.broadcasting)
async def do_broadcast(message: types.Message, state: FSMContext):
    await state.clear()
    users = await db_exec("SELECT id FROM users", fetch="all")
    ok = 0
    for u in users:
        try:
            await bot.send_message(u['id'], message.text)
            ok += 1
        except:
            pass
    await message.answer(f"✅ Рассылка завершена: {ok}/{len(users)}")

@dp.callback_query(F.data == "a_give_prem")
async def a_give_prem_cb(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.giving_prem_id)
    await call.message.answer("💎 Введи ID пользователя и дни (формат: 123456 30):")
    await call.answer()

@dp.message(States.giving_prem_id)
async def do_give_prem(message: types.Message, state: FSMContext):
    await state.clear()
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("❌ Формат: ID дни")
        return
    uid  = int(parts[0])
    days = int(parts[1])
    until = datetime.now() + timedelta(days=days)
    await db_exec(
        "UPDATE users SET prem_until=GREATEST(COALESCE(prem_until,NOW()),$1) WHERE id=$2",
        until, uid
    )
    try:
        await bot.send_message(uid, f"💎 Вам выдан Premium на {days} дней!")
    except:
        pass
    await message.answer(f"✅ Premium выдан {uid} на {days} дней.")

@dp.callback_query(F.data == "a_ban")
async def a_ban_cb(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_ban_input)
    await call.message.answer("🚫 Введи ID и дни (формат: 123456 7):")
    await call.answer()

@dp.message(States.admin_ban_input)
async def do_ban(message: types.Message, state: FSMContext):
    await state.clear()
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("❌ Формат: ID дни")
        return
    uid  = int(parts[0])
    days = int(parts[1])
    until = datetime.now() + timedelta(days=days)
    await db_exec("UPDATE users SET banned_until=$1 WHERE id=$2", until, uid)
    try:
        await bot.send_message(uid, f"🚫 Вы заблокированы на {days} дней.")
    except:
        pass
    await message.answer(f"✅ Пользователь {uid} забанен на {days} дней.")

@dp.callback_query(F.data == "a_mute")
async def a_mute_cb(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    await state.set_state(States.admin_mute_input)
    await call.message.answer("🔇 Введи ID и часы (формат: 123456 2):")
    await call.answer()

@dp.message(States.admin_mute_input)
async def do_mute(message: types.Message, state: FSMContext):
    await state.clear()
    parts = message.text.split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("❌ Формат: ID часы")
        return
    uid   = int(parts[0])
    hours = int(parts[1])
    until = datetime.now() + timedelta(hours=hours)
    await db_exec("UPDATE users SET muted_until=$1 WHERE id=$2", until, uid)
    try:
        await bot.send_message(uid, f"🔇 Вы замучены на {hours} ч.")
    except:
        pass
    await message.answer(f"✅ Пользователь {uid} замучен на {hours} ч.")

# ================================================================
# БАН/МУТ ИЗ ЖАЛОБЫ
# ================================================================
@dp.callback_query(F.data.startswith("ban_"))
async def ban_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS: return
    p    = call.data.split("_")
    uid  = int(p[1])
    days = int(p[2])
    until = datetime.now() + timedelta(days=days)
    await db_exec("UPDATE users SET banned_until=$1 WHERE id=$2", until, uid)
    try: await bot.send_message(uid, f"🚫 Вы заблокированы на {days} дней.")
    except: pass
    await call.message.edit_text(f"✅ {uid} забанен на {days} дней.")

@dp.callback_query(F.data.startswith("mute_"))
async def mute_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS: return
    p     = call.data.split("_")
    uid   = int(p[1])
    hours = int(p[2])
    until = datetime.now() + timedelta(hours=hours)
    await db_exec("UPDATE users SET muted_until=$1 WHERE id=$2", until, uid)
    try: await bot.send_message(uid, f"🔇 Вы замучены на {hours} ч.")
    except: pass
    await call.message.edit_text(f"✅ {uid} замучен на {hours} ч.")

@dp.callback_query(F.data.startswith("rep_ok_"))
async def rep_ok_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS: return
    await call.message.edit_text("✅ Жалоба отклонена.")

# ================================================================
# ОЧЕРЕДЬ CALLBACK
# ================================================================
@dp.callback_query(F.data.startswith("q_"))
async def queue_cb(call: types.CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    if uid in active_chats:
        await call.answer("Вы уже в чате!", show_alert=True)
        return
    await state.clear()
    try: await call.message.delete()
    except: pass
    await enter_queue(uid, call.data.split("_")[1])

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
        f"💳 Карта: `4874070057830877`\nСумма: *{price}*\n\n"
        f"После оплаты отправьте скриншот чека сюда 👇",
        parse_mode="Markdown"
    )
    await state.set_state(States.wait_proof)

@dp.callback_query(F.data.startswith("pay_"))
async def pay_adm(call: types.CallbackQuery):
    p         = call.data.split("_")
    action    = p[1]
    target_id = int(p[2])
    days      = int(p[3]) if len(p) > 3 else 30
    if action == "yes":
        if days == 999:
            until = datetime.now() + timedelta(days=36500)
            msg   = "💎 *Premium активирован навсегда!*"
        else:
            row  = await db_exec("SELECT prem_until FROM users WHERE id=$1", target_id, fetch="one")
            base = datetime.now()
            if row and row['prem_until'] and row['prem_until'] > base: base = row['prem_until']
            until = base + timedelta(days=days)
            msg   = (f"💎 *Premium на {days} дней!*\n"
                     f"До: {until.strftime('%d.%m.%Y')}")
        await db_exec("UPDATE users SET prem_until=$1 WHERE id=$2", until, target_id)
        try: await bot.send_message(target_id, msg, parse_mode="Markdown")
        except: pass
        try: await call.message.edit_caption(caption=f"✅ Оплата подтверждена для {target_id}.")
        except: await call.message.edit_text(f"✅ Оплата подтверждена для {target_id}.")
    else:
        try: await bot.send_message(target_id, "❌ Ваша оплата отклонена.")
        except: pass
        try: await call.message.edit_caption(caption=f"❌ Оплата отклонена для {target_id}.")
        except: await call.message.edit_text(f"❌ Оплата отклонена для {target_id}.")

# ================================================================
# СТАТИСТИКА
# ================================================================
@dp.callback_query(F.data == "a_stats")
async def a_stats_cb(call: types.CallbackQuery):
    now    = datetime.now()
    total  = (await db_exec("SELECT COUNT(*) FROM users", fetch="one"))[0]
    prem_c = (await db_exec("SELECT COUNT(*) FROM users WHERE prem_until > $1", now, fetch="one"))[0]
    ban_c  = (await db_exec("SELECT COUNT(*) FROM users WHERE banned_until > $1", now, fetch="one"))[0]
    mute_c = (await db_exec("SELECT COUNT(*) FROM users WHERE muted_until > $1", now, fetch="one"))[0]
    rep_c  = (await db_exec("SELECT COUNT(*) FROM reports", fetch="one"))[0]
    online = len(active_chats) // 2
    await call.message.answer(
        f"📊 *Статистика бота*\n\n"
        f"👥 Всего юзеров: {total}\n"
        f"💎 Premium: {prem_c}\n"
        f"🚫 Забаненных: {ban_c}\n"
        f"🔇 Замученных: {mute_c}\n"
        f"🚩 Жалоб в очереди: {rep_c}\n"
        f"💬 Активных чатов: {online}",
        parse_mode="Markdown"
    )
    await call.answer()

# ================================================================
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК
# ================================================================
@dp.message()
async def global_handler(message: types.Message, state: FSMContext):
    uid       = message.from_user.id
    cur_state = await state.get_state()

    if cur_state == "States:wait_proof" and message.photo:
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
        return

    banned, until = await is_banned(uid)
    if banned:
        await message.answer(
            f"🚫 Вы заблокированы до *{until}*.\nОбратитесь в поддержку.",
            parse_mode="Markdown"
        )
        return

    if uid in active_chats:
        pid = active_chats[uid]
        muted, muted_until = await is_muted(uid)
        if muted:
            await message.answer(f"🔇 Вы замучены до *{muted_until}*.", parse_mode="Markdown")
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

    if message.text == "🔎 Поиск":
        if await is_prem(uid):
            kb = InlineKeyboardBuilder()
            kb.button(text="Все",        callback_data="q_all")
            kb.button(text="Девушки 👩", callback_data="q_Ж")
            kb.button(text="Парни 👨",   callback_data="q_М")
            await message.answer(
                "💎 *Premium Поиск*\nВыбери пол собеседника:",
                reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown"
            )
        else:
            await enter_queue(uid, "all")

    elif message.text == "👤 Профиль":
        u = await db_exec("SELECT id,username,refs,prem_until,gender,age FROM users WHERE id=$1", uid, fetch="one")
        if not u:
            await message.answer("Сначала пройди регистрацию через /start"); return
        p_status = "✅ Активен" if await is_prem(uid) else "❌ Не активен"
        rank     = "👑 Администратор" if uid in ADMINS else "Пользователь"
        await message.answer(
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"👤 *ВАШ ПРОФИЛЬ*\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"🆔 Твой ID: `{uid}`\n"
            f"🎭 Ранг: {rank}\n"
            f"💎 Premium: {p_status}\n"
            f"🤝 Рефералов: {u['refs']}\n"
            f"🚻 Пол: {u['gender'] or '—'} | 🎂 Возраст: {u['age'] or '—'}\n"
            f"➖➖➖➖➖➖➖➖➖➖",
            parse_mode="Markdown"
        )

    elif message.text == "🏆 ТОП":
        top = await db_exec("SELECT username,refs FROM users ORDER BY refs DESC LIMIT 5", fetch="all")
        txt = "🏆 *ЛИДЕРЫ РЕФЕРАЛОВ*\n\n"
        for i, r in enumerate(top, 1):
            txt += f"{i}. {r['username'] or 'User'} — {r['refs']} чел.\n"
        await message.answer(txt, parse_mode="Markdown")

    elif message.text == "💎 Реферал":
        me   = await bot.get_me()
        u    = await db_exec("SELECT refs FROM users WHERE id=$1", uid, fetch="one")
        refs = u['refs'] if u else 0
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
            "💎 *Выбери тариф:*",
            reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown"
        )

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

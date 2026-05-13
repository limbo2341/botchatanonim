import asyncio
import logging
import os
from datetime import datetime, timedelta

import psycopg2
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
# БАЗА ДАННЫХ
# ================================================================
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def db_exec(sql, params=(), fetch="none"):
    """Универсальный исполнитель SQL. Всегда делает commit."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if fetch == "one":
                result = cur.fetchone()
                conn.commit()
                return result
            if fetch == "all":
                result = cur.fetchall()
                conn.commit()
                return result
            conn.commit()
    finally:
        conn.close()

def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id           SERIAL PRIMARY KEY,
                    reporter_id  BIGINT,
                    target_id    BIGINT,
                    last_message TEXT,
                    created_at   TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()
    finally:
        conn.close()

# ================================================================
# ХЕЛПЕРЫ
# ================================================================
def is_prem(uid):
    if uid in ADMINS: return True
    r = db_exec("SELECT prem_until FROM users WHERE id=%s", (uid,), "one")
    return bool(r and r[0] and r[0] > datetime.now())

def is_banned(uid):
    if uid in ADMINS: return False, None
    r = db_exec("SELECT banned_until FROM users WHERE id=%s", (uid,), "one")
    if r and r[0]:
        if r[0] > datetime.now():
            return True, r[0].strftime("%d.%m.%Y %H:%M")
        db_exec("UPDATE users SET banned_until=NULL WHERE id=%s", (uid,))
    return False, None

def is_muted(uid):
    if uid in ADMINS: return False, None
    r = db_exec("SELECT muted_until FROM users WHERE id=%s", (uid,), "one")
    if r and r[0]:
        if r[0] > datetime.now():
            return True, r[0].strftime("%d.%m.%Y %H:%M")
        db_exec("UPDATE users SET muted_until=NULL WHERE id=%s", (uid,))
    return False, None

def get_user_info(uid):
    r = db_exec("SELECT username, gender, age FROM users WHERE id=%s", (uid,), "one")
    if not r:
        return f"🆔 ID: `{uid}`\nИнфо не найдено"
    username, gender, age = r
    prem     = "💎 Premium" if is_prem(uid) else "Обычный"
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
active_chats  = {}   # uid -> pid (собеседник)
last_messages = {}   # uid -> последнее сообщение написанное uid
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
            f"🎁 *Собеседник найден!*\n\n{get_user_info(pid)}",
            reply_markup=chat_kb(), parse_mode="Markdown"
        )
        await bot.send_message(
            pid,
            f"🎁 *Собеседник найден!*\n\n{get_user_info(uid)}",
            reply_markup=chat_kb(), parse_mode="Markdown"
        )
    else:
        queues[cat] = [uid]
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отмена", callback_data="stop_q")
        await bot.send_message(uid, f"⏳ Поиск в категории [{cat}]...", reply_markup=kb.as_markup())

# ================================================================
# КНОПКИ ЧАТА — StateFilter("*") = работают при ЛЮБОМ state FSM
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
    if uid not in active_chats: return
    await state.clear()
    pid      = active_chats[uid]
    last_msg = last_messages.get(pid) or "(нет сообщений)"
    # Сохраняем жалобу в БД
    db_exec(
        "INSERT INTO reports (reporter_id, target_id, last_message) VALUES (%s,%s,%s)",
        (uid, pid, last_msg)
    )
    # Сразу шлём уведомление каждому админу
    pid_info = get_user_info(pid)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔨 Бан 3 дня",      callback_data=f"rban_3_{pid}_0")
    kb.button(text="🔇 Мут 1 день",     callback_data=f"rmute_1_{pid}_0")
    kb.button(text="⚠️ Предупреждение", callback_data=f"rwarn_{pid}_0")
    kb.button(text="✅ Без наказания",  callback_data=f"rnoban_{pid}_0")
    text = (
        f"🚩 *Новая жалоба!*\n\n"
        f"*Нарушитель:*\n{pid_info}\n\n"
        f"*Последнее сообщение:*\n`{last_msg}`"
    )
    for adm in ADMINS:
        try:
            await bot.send_message(adm, text, reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
        except: pass
    await message.answer("✅ Жалоба отправлена администрации!\nПродолжайте чат или выйдите.")

# ================================================================
# /start
# ================================================================
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    uid    = message.from_user.id
    args   = message.text.split()
    ref_id = args[1] if len(args) > 1 else None

    is_new = not db_exec("SELECT id FROM users WHERE id=%s", (uid,), "one")
    if is_new:
        db_exec("INSERT INTO users (id, username, refs) VALUES (%s,%s,0)",
                (uid, message.from_user.username))
        if ref_id:
            try:
                rid = int(ref_id)
                if rid != uid and db_exec("SELECT id FROM users WHERE id=%s", (rid,), "one"):
                    db_exec("UPDATE users SET refs=refs+1 WHERE id=%s", (rid,))
                    u_refs = db_exec("SELECT refs FROM users WHERE id=%s", (rid,), "one")[0]
                    try:
                        await bot.send_message(
                            rid,
                            f"🎉 По вашей реф-ссылке зарегистрировался новый пользователь!\n"
                            f"👥 Ваших рефералов: *{u_refs}*",
                            parse_mode="Markdown"
                        )
                    except: pass
                    if u_refs % 10 == 0:
                        row  = db_exec("SELECT prem_until FROM users WHERE id=%s", (rid,), "one")
                        base = datetime.now()
                        if row and row[0] and row[0] > base: base = row[0]
                        until = base + timedelta(days=2)
                        db_exec("UPDATE users SET prem_until=%s WHERE id=%s", (until, rid))
                        try:
                            await bot.send_message(
                                rid,
                                f"🏆 Вы пригласили *{u_refs}* человек — получаете *+2 дня Premium*!",
                                parse_mode="Markdown"
                            )
                        except: pass
            except (ValueError, TypeError): pass

    kb = InlineKeyboardBuilder()
    for a in ["< 18", "18+", "25+", "65+"]:
        kb.button(text=a, callback_data=f"set_age_{a}")
    await message.answer("👋 Добро пожаловать! Укажи свой возраст:", reply_markup=kb.adjust(2).as_markup())

@dp.callback_query(F.data.startswith("set_age_"))
async def cb_age(call: types.CallbackQuery):
    db_exec("UPDATE users SET age=%s WHERE id=%s", (call.data[8:], call.from_user.id))
    kb = InlineKeyboardBuilder()
    kb.button(text="👨 Мужской", callback_data="set_sex_М")
    kb.button(text="👩 Женский", callback_data="set_sex_Ж")
    await call.message.edit_text("Теперь выбери свой пол:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("set_sex_"))
async def cb_sex(call: types.CallbackQuery):
    db_exec("UPDATE users SET gender=%s WHERE id=%s", (call.data[8:], call.from_user.id))
    await call.message.answer(
        "🎉 Регистрация завершена! Теперь ты можешь искать общение.",
        reply_markup=main_kb(call.from_user.id)
    )
    await call.message.delete()

# ================================================================
# ИНТЕРЕСЫ
# ================================================================
@dp.message(F.text == "🎭 По интересам")
async def interests_menu(message: types.Message):
    banned, until = is_banned(message.from_user.id)
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
# ТЕХ ПОДДЕРЖКА
# ================================================================
@dp.message(F.text == "👨‍💻 Поддержка")
async def tech_start(message: types.Message, state: FSMContext):
    if message.from_user.id in active_chats: return
    await state.clear()
    await message.answer("📝 Напишите ваше обращение. Админ ответит в ближайшее время.")
    await state.set_state(States.tech_support)

@dp.message(States.tech_support)
async def tech_send(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid in active_chats:
        await state.clear(); return
    for a in ADMINS:
        kb = InlineKeyboardBuilder()
        kb.button(text="✉️ Ответить", callback_data=f"reply_{uid}")
        await bot.send_message(
            a,
            f"📨 *Новое обращение!*\nОт ID: `{uid}`\nТекст: {message.text}",
            reply_markup=kb.as_markup(), parse_mode="Markdown"
        )
    await message.answer("✅ Сообщение отправлено администрации.")
    await state.clear()

# ================================================================
# АДМИН ПАНЕЛЬ
# ================================================================
@dp.message(F.text == "⚙️ Админ Панель")
async def adm_panel(message: types.Message):
    if message.from_user.id not in ADMINS: return
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Рассылка",    callback_data="adm_broad")
    kb.button(text="🚩 Жалобы",      callback_data="adm_reps")
    kb.button(text="🎁 Выдать Прем", callback_data="adm_give_manual")
    kb.button(text="📊 Статистика",  callback_data="a_stats")
    kb.button(text="🔨 Бан по ID",   callback_data="adm_ban")
    kb.button(text="🔇 Мут по ID",   callback_data="adm_mute")
    await message.answer(
        "🛠 *Панель управления администратора*",
        reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown"
    )

# --- Рассылка ---
@dp.callback_query(F.data == "adm_broad")
async def broad_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите текст рассылки:")
    await state.set_state(States.broadcasting)
    await call.answer()

@dp.message(States.broadcasting)
async def broad_process(message: types.Message, state: FSMContext):
    users = db_exec("SELECT id FROM users", fetch="all")
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
        row = db_exec("SELECT prem_until FROM users WHERE id=%s", (target,), "one")
        if row is not None:
            base = datetime.now()
            if row[0] and row[0] > base: base = row[0]
            until = base + timedelta(days=30)
            db_exec("UPDATE users SET prem_until=%s WHERE id=%s", (until, target))
            try: await bot.send_message(target, "💎 Вам выдан *Premium на 30 дней*!", parse_mode="Markdown")
            except: pass
            await message.answer(f"✅ Premium выдан пользователю `{target}`.", parse_mode="Markdown")
        else:
            await message.answer("❌ Пользователь не найден.")
    except ValueError:
        await message.answer("❌ Неверный ID.")
    await state.clear()

# --- Жалобы (очередь в панели) ---
@dp.callback_query(F.data == "adm_reps")
async def adm_reps_cb(call: types.CallbackQuery):
    r = db_exec(
        "SELECT id,reporter_id,target_id,last_message,created_at FROM reports ORDER BY id ASC LIMIT 1",
        fetch="one"
    )
    if not r:
        await call.answer("Жалоб нет!", show_alert=True)
        return
    rep_id, reporter_id, target_id, last_msg, created_at = r
    total    = db_exec("SELECT COUNT(*) FROM reports", fetch="one")[0]
    pid_info = get_user_info(target_id)
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

# --- Кнопки решения жалобы ---
@dp.callback_query(F.data.startswith("rban_"))
async def r_ban_cb(call: types.CallbackQuery):
    parts = call.data.split("_")
    days, target_id, rep_id = int(parts[1]), int(parts[2]), int(parts[3])
    until    = datetime.now() + timedelta(days=days)
    user_msg = (f"🔨 Вы заблокированы *на {days} дн.* за нарушение правил.\n"
                f"Разблокировка: {until.strftime('%d.%m.%Y %H:%M')}")
    db_exec("UPDATE users SET banned_until=%s WHERE id=%s", (until, target_id))
    if rep_id: db_exec("DELETE FROM reports WHERE id=%s", (rep_id,))
    if target_id in active_chats:
        pid = active_chats.pop(target_id)
        active_chats.pop(pid, None)
        try: await bot.send_message(pid, "💔 Собеседник покинул чат.", reply_markup=main_kb(pid))
        except: pass
    try: await bot.send_message(target_id, user_msg, parse_mode="Markdown")
    except: pass
    try: await call.message.edit_text(f"✅ Пользователь `{target_id}` заблокирован на {days} дн.", parse_mode="Markdown")
    except: pass

@dp.callback_query(F.data.startswith("rmute_"))
async def r_mute_cb(call: types.CallbackQuery):
    parts = call.data.split("_")
    days, target_id, rep_id = int(parts[1]), int(parts[2]), int(parts[3])
    until    = datetime.now() + timedelta(days=days)
    user_msg = (f"🔇 Вы замучены *на {days} дн.*\n"
                f"Окончание: {until.strftime('%d.%m.%Y %H:%M')}")
    db_exec("UPDATE users SET muted_until=%s WHERE id=%s", (until, target_id))
    if rep_id: db_exec("DELETE FROM reports WHERE id=%s", (rep_id,))
    try: await bot.send_message(target_id, user_msg, parse_mode="Markdown")
    except: pass
    try: await call.message.edit_text(f"✅ Пользователь `{target_id}` замучен на {days} дн.", parse_mode="Markdown")
    except: pass

@dp.callback_query(F.data.startswith("rwarn_"))
async def r_warn_cb(call: types.CallbackQuery):
    parts = call.data.split("_")
    target_id, rep_id = int(parts[1]), int(parts[2])
    if rep_id: db_exec("DELETE FROM reports WHERE id=%s", (rep_id,))
    try:
        await bot.send_message(
            target_id,
            "⚠️ *Предупреждение от администрации!*\n"
            "Вы нарушаете правила. При повторном — будете заблокированы.",
            parse_mode="Markdown"
        )
    except: pass
    try: await call.message.edit_text(f"✅ Предупреждение отправлено `{target_id}`.", parse_mode="Markdown")
    except: pass

@dp.callback_query(F.data.startswith("rnoban_"))
async def r_noban_cb(call: types.CallbackQuery):
    rep_id = int(call.data.split("_")[2])
    if rep_id: db_exec("DELETE FROM reports WHERE id=%s", (rep_id,))
    try: await call.message.edit_text("✅ Жалоба отклонена. Нарушений не выявлено.")
    except: pass

# ================================================================
# БАН ПО ID (из панели)
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
    await call.message.answer("🔨 *Бан пользователя*\nВыберите срок:",
                              reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
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
    data     = await state.get_data()
    days_str = data.get("ban_days")
    if not days_str:
        await message.answer("Сначала выберите срок."); return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = db_exec("SELECT id,username FROM users WHERE id=%s", (tid,), "one")
    except ValueError:
        row = db_exec("SELECT id,username FROM users WHERE username=%s", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return
    tid, tusername = row
    days = int(days_str)
    if days == 999:
        until = datetime.now() + timedelta(days=36500)
        label = "навсегда"
        msg   = "⛔ Вы заблокированы *навсегда* администрацией."
    else:
        until = datetime.now() + timedelta(days=days)
        label = f"на {days} дн."
        msg   = (f"🔨 Вы заблокированы *на {days} дн.*\n"
                 f"Разблокировка: {until.strftime('%d.%m.%Y %H:%M')}")
    db_exec("UPDATE users SET banned_until=%s WHERE id=%s", (until, tid))
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
# МУТ ПО ID (из панели)
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
    await call.message.answer("🔇 *Мут пользователя*\nВыберите срок:",
                              reply_markup=kb.adjust(2).as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("muteperiod_"))
async def adm_mute_period(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS: return
    days = call.data.split("_")[1]
    await state.update_data(mute_days=days)
    label = "навсегда" if days == "999" else f"{days} дн."
    await call.message.answer(f"Срок: *{label}*\nВведите ID або @username:", parse_mode="Markdown")
    await call.answer()

@dp.message(States.admin_mute_input)
async def adm_mute_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    data     = await state.get_data()
    days_str = data.get("mute_days")
    if not days_str:
        await message.answer("Сначала выберите срок."); return
    raw = message.text.strip().lstrip("@")
    row = None
    try:
        tid = int(raw)
        row = db_exec("SELECT id,username FROM users WHERE id=%s", (tid,), "one")
    except ValueError:
        row = db_exec("SELECT id,username FROM users WHERE username=%s", (raw,), "one")
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear(); return
    tid, tusername = row
    days = int(days_str)
    if days == 999:
        until = datetime.now() + timedelta(days=36500)
        label = "навсегда"
        msg   = "🔇 Вы замучены *навсегда*."
    else:
        until = datetime.now() + timedelta(days=days)
        label = f"на {days} дн."
        msg   = (f"🔇 Вы замучены *на {days} дн.*\n"
                 f"Окончание: {until.strftime('%d.%m.%Y %H:%M')}")
    db_exec("UPDATE users SET muted_until=%s WHERE id=%s", (until, tid))
    try: await bot.send_message(tid, msg, parse_mode="Markdown")
    except: pass
    name = f"@{tusername}" if tusername else str(tid)
    await message.answer(f"✅ {name} замучен {label}.")
    await state.clear()

# ================================================================
# ОТВЕТ АДМИНИСТРАТОРА (поддержка)
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
    data   = await state.get_data()
    target = data.get("rep_to")
    try:
        await bot.send_message(target, f"📩 *Ответ от поддержки:*\n\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Ответ отправлен.")
        await state.clear()
    except:
        await message.answer("❌ Не удалось отправить.")

# ================================================================
# ПОИСК CALLBACKS
# ================================================================
@dp.callback_query(F.data.startswith("q_"))
async def q_callback(call: types.CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    banned, until = is_banned(uid)
    if banned:
        await call.answer(f"Вы заблокированы до {until}", show_alert=True)
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
            row  = db_exec("SELECT prem_until FROM users WHERE id=%s", (target_id,), "one")
            base = datetime.now()
            if row and row[0] and row[0] > base: base = row[0]
            until = base + timedelta(days=days)
            msg   = (f"💎 *Premium на {days} дней!*\n"
                     f"До: {until.strftime('%d.%m.%Y')}")
        db_exec("UPDATE users SET prem_until=%s WHERE id=%s", (until, target_id))
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
    total  = db_exec("SELECT COUNT(*) FROM users", fetch="one")[0]
    prem_c = db_exec("SELECT COUNT(*) FROM users WHERE prem_until > %s",   (now,), "one")[0]
    ban_c  = db_exec("SELECT COUNT(*) FROM users WHERE banned_until > %s", (now,), "one")[0]
    mute_c = db_exec("SELECT COUNT(*) FROM users WHERE muted_until > %s",  (now,), "one")[0]
    rep_c  = db_exec("SELECT COUNT(*) FROM reports", fetch="one")[0]
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

    # Скриншот оплаты — проверяем строкой (aiogram 3 возвращает строку)
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

    # Бан
    banned, until = is_banned(uid)
    if banned:
        await message.answer(
            f"🚫 Вы заблокированы до *{until}*.\nОбратитесь в поддержку.",
            parse_mode="Markdown"
        )
        return

    # Пересылка в активном чате
    if uid in active_chats:
        pid = active_chats[uid]
        muted, muted_until = is_muted(uid)
        if muted:
            await message.answer(f"🔇 Вы замучены до *{muted_until}*.", parse_mode="Markdown")
            return
        # Сохраняем последнее сообщение uid (чтобы при жалобе на uid — видели что он писал)
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
    if message.text == "🔎 Поиск":
        if is_prem(uid):
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
        u = db_exec("SELECT id,username,refs,prem_until,gender,age FROM users WHERE id=%s", (uid,), "one")
        if not u:
            await message.answer("Сначала пройди регистрацию через /start"); return
        p_status = "✅ Активен" if is_prem(uid) else "❌ Не активен"
        rank     = "👑 Администратор" if uid in ADMINS else "Пользователь"
        await message.answer(
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"👤 *ВАШ ПРОФИЛЬ*\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"🆔 Твой ID: `{uid}`\n"
            f"🎭 Ранг: {rank}\n"
            f"💎 Premium: {p_status}\n"
            f"🤝 Рефералов: {u[2]}\n"
            f"🚻 Пол: {u[4] or '—'} | 🎂 Возраст: {u[5] or '—'}\n"
            f"➖➖➖➖➖➖➖➖➖➖",
            parse_mode="Markdown"
        )

    elif message.text == "🏆 ТОП":
        top = db_exec("SELECT username,refs FROM users ORDER BY refs DESC LIMIT 5", fetch="all")
        txt = "🏆 *ЛИДЕРЫ РЕФЕРАЛОВ*\n\n"
        for i, r in enumerate(top, 1):
            txt += f"{i}. {r[0] or 'User'} — {r[1]} чел.\n"
        await message.answer(txt, parse_mode="Markdown")

    elif message.text == "💎 Реферал":
        me   = await bot.get_me()
        u    = db_exec("SELECT refs FROM users WHERE id=%s", (uid,), "one")
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
            "💎 *Выбери тариф:*",
            reply_markup=kb.adjust(1).as_markup(), parse_mode="Markdown"
        )

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

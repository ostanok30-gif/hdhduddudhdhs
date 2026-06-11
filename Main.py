import asyncio
import logging
import sqlite3
import html
import aiohttp
import time
import platform
import sys
import threading
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    MessageHandler, filters
)

# ========================= КОНФИГУРАЦИЯ =========================
BOT_TOKEN = "5899329063:AAECeQOS3J_GrPaFw7MZ3JW1xUNBCCtHzoU"
OWNER_ID = 8640180536
CRYPTO_BOT_TOKEN = "588369:AAKj4nTSnSQQa4IJwchTa3mCGp0SUWVsxdk"
CRYPTO_API_URL = "https://pay.crypt.bot/api/"
FIRE_EFFECT_ID = "5104841245755180586"

START_TIME = time.time()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# ========================= БАЗА ДАННЫХ =========================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("shark_bot.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._init_tables()

    def execute(self, sql, params=()):
        with self.lock:
            cursor = self.conn.execute(sql, params)
            self.conn.commit()
            return cursor

    def fetchone(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def _init_tables(self):
        self.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, refs_count INTEGER DEFAULT 0,
            premium_until TEXT, total_attacks INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0, is_subbed INTEGER DEFAULT 0, invited_by INTEGER DEFAULT 0,
            ref_credited INTEGER DEFAULT 0)""")
        self.execute("""CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT, channel_name TEXT, channel_url TEXT,
            channel_id TEXT)""")
        self.execute("""CREATE TABLE IF NOT EXISTS scam_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, target TEXT,
            mark_text TEXT, created_at TEXT)""")
        self.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT,
            created_at TEXT)""")
        self.execute("""CREATE TABLE IF NOT EXISTS paid_invoices (
            invoice_id INTEGER PRIMARY KEY)""")
        self.execute("INSERT OR IGNORE INTO users (user_id, username, is_admin) VALUES (?, ?, 1)", (OWNER_ID, "owner"))

    def get_user(self, user_id): return self.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
    def create_user(self, user_id, username, invited_by=0):
        try:
            self.execute("INSERT INTO users (user_id, username, invited_by) VALUES (?, ?, ?)", (user_id, username, invited_by))
            return True
        except: return False
    def set_subbed(self, user_id): self.execute("UPDATE users SET is_subbed = 1 WHERE user_id = ?", (user_id,))
    def is_subbed(self, user_id):
        row = self.fetchone("SELECT is_subbed FROM users WHERE user_id = ?", (user_id,))
        return row and row["is_subbed"] == 1
    def is_ref_credited(self, user_id):
        row = self.fetchone("SELECT ref_credited FROM users WHERE user_id = ?", (user_id,))
        return row and row["ref_credited"] == 1
    def set_ref_credited(self, user_id): self.execute("UPDATE users SET ref_credited = 1 WHERE user_id = ?", (user_id,))
    def add_ref(self, user_id): self.execute("UPDATE users SET refs_count = refs_count + 1 WHERE user_id = ?", (user_id,))
    def get_refs(self, user_id):
        row = self.fetchone("SELECT refs_count FROM users WHERE user_id = ?", (user_id,))
        return row["refs_count"] if row else 0
    def get_invited_by(self, user_id):
        row = self.fetchone("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
        return row["invited_by"] if row else 0
    def get_refs_list(self, user_id):
        return self.fetchall("SELECT user_id, username FROM users WHERE invited_by = ?", (user_id,))
    def get_premium_status(self, user_id):
        row = self.fetchone("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
        if row and row["premium_until"]:
            try:
                end_time = datetime.fromisoformat(row["premium_until"])
                if end_time > datetime.now(): return end_time
            except: pass
        return None
    def has_premium(self, user_id): return self.get_premium_status(user_id) is not None
    def activate_premium(self, user_id, days):
        current = datetime.now()
        existing = self.get_premium_status(user_id)
        if existing and existing > current: current = existing
        if days == 0:
            self.execute("UPDATE users SET premium_until = NULL WHERE user_id = ?", (user_id,))
            return None
        else:
            new_end = current + timedelta(days=days)
            self.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (new_end.isoformat(), user_id))
            return new_end
    def add_attack(self, user_id): self.execute("UPDATE users SET total_attacks = total_attacks + 1 WHERE user_id = ?", (user_id,))
    def is_admin(self, user_id):
        row = self.fetchone("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
        return row and row["is_admin"] == 1
    def set_admin(self, user_id, is_admin): self.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (1 if is_admin else 0, user_id))
    def get_admins(self): return self.fetchall("SELECT user_id FROM users WHERE is_admin = 1")
    def set_blocked(self, user_id, status: bool): self.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (1 if status else 0, user_id))
    def is_blocked(self, user_id):
        row = self.fetchone("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
        return row and row["is_blocked"] == 1
    def add_scam_mark(self, user_id, target, mark_text): self.execute("INSERT INTO scam_marks (user_id, target, mark_text, created_at) VALUES (?, ?, ?, ?)", (user_id, target, mark_text, datetime.now().isoformat()))
    def get_scam_marks_count(self, user_id):
        row = self.fetchone("SELECT COUNT(*) as c FROM scam_marks WHERE user_id = ?", (user_id,))
        return row["c"] if row else 0
    def add_channel(self, name, url, channel_id): self.execute("INSERT INTO required_channels (channel_name, channel_url, channel_id) VALUES (?, ?, ?)", (name, url, str(channel_id)))
    def get_channels(self): return self.fetchall("SELECT * FROM required_channels")
    def remove_channel(self, local_id): self.execute("DELETE FROM required_channels WHERE id = ?", (local_id,))
    def add_ticket(self, user_id, message):
        with self.lock:
            cursor = self.conn.execute("INSERT INTO support_tickets (user_id, message, created_at) VALUES (?, ?, ?)", (user_id, message, datetime.now().isoformat()))
            self.conn.commit()
            return cursor.lastrowid
    def get_stats(self):
        users = self.fetchone("SELECT COUNT(*) as c FROM users")["c"]
        prem = self.fetchone("SELECT COUNT(*) as c FROM users WHERE premium_until > datetime('now')")["c"]
        atk = self.fetchone("SELECT SUM(total_attacks) as s FROM users")["s"] or 0
        return {"users": users, "premium": prem, "attacks": atk}
    def is_invoice_paid(self, invoice_id): return self.fetchone("SELECT 1 FROM paid_invoices WHERE invoice_id = ?", (invoice_id,)) is not None
    def mark_invoice_paid(self, invoice_id): self.execute("INSERT OR IGNORE INTO paid_invoices (invoice_id) VALUES (?)", (invoice_id,))

db = Database()

# ========================= CRYPTOBOT API =========================
async def create_crypto_invoice(amount: float, payload: str, asset: str = "USDT") -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CRYPTO_API_URL + "createInvoice", headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}, json={"asset": asset, "amount": str(amount), "payload": payload}) as resp:
                res = await resp.json()
                if res.get("ok"): return res["result"]
    except: pass
    return None

async def get_crypto_invoice(invoice_id: int) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CRYPTO_API_URL + f"getInvoices?invoice_ids={invoice_id}", headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}) as resp:
                res = await resp.json()
                if res.get("ok") and res["result"]["items"]: return res["result"]["items"][0]
    except: pass
    return None

# ========================= ФОРМАТИРОВАНИЕ =========================
def escape(text: str) -> str: return html.escape(str(text))
def bold(text: str) -> str: return f"<b>{escape(text)}</b>"
def mono(text: str) -> str: return f"<code>{escape(text)}</code>"
def quote(text: str) -> str: return f"<blockquote>{escape(text)}</blockquote>"

def format_timedelta(td: timedelta) -> str:
    days, seconds = td.days, td.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if days > 0: return f"{days} дн. {hours} ч."
    if hours > 0: return f"{hours} ч. {minutes} мин."
    return f"{minutes} мин."

# ========================= ЗАЧИСЛЕНИЕ РЕФЕРАЛА =========================
async def credit_ref(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Засчитывает реферала если ещё не засчитан"""
    if db.is_ref_credited(user_id):
        return
    
    invited_by = db.get_invited_by(user_id)
    if not invited_by or invited_by == 0 or invited_by == user_id:
        return
    
    db.set_ref_credited(user_id)
    db.add_ref(invited_by)
    
    user = db.get_user(user_id)
    uname = user["username"] if user else str(user_id)
    
    # Уведомление рефереру
    try:
        await context.bot.send_message(
            invited_by,
            f"{bold('+1 реферал')}\nАгент @{uname} присоединился.",
            parse_mode=ParseMode.HTML
        )
    except: pass
    
    # Лог админам
    for admin in db.get_admins():
        try:
            await context.bot.send_message(
                admin["user_id"],
                f"Реферал засчитан:\nАгент: {mono(str(user_id))} (@{uname})\nРеферер: {mono(str(invited_by))}\nУ реферера: {db.get_refs(invited_by)} реф.",
                parse_mode=ParseMode.HTML
            )
        except: pass

# ========================= ПРОВЕРКА ПОДПИСКИ =========================
async def check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query = update.callback_query
    if query:
        try: await query.answer()
        except: pass

    user_id = update.effective_user.id
    if db.is_admin(user_id): return True

    channels = db.get_channels()
    
    # Если каналов нет — засчитываем реферала и пропускаем
    if not channels:
        await credit_ref(user_id, context)
        return True

    not_subbed = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=ch["channel_id"], user_id=user_id)
            if member.status in ['left', 'kicked']: 
                not_subbed.append(ch)
        except: 
            not_subbed.append(ch)

    if not not_subbed:
        # Подписан на все каналы — засчитываем реферала
        await credit_ref(user_id, context)
        return True

    # Не подписан — показываем предупреждение
    keyboard = [[InlineKeyboardButton(ch["channel_name"], url=ch["channel_url"])] for ch in not_subbed]
    keyboard.append([InlineKeyboardButton("Проверить подписку", callback_data="menu")])
    text = f"{bold('Доступ ограничен')}\n\nДля продолжения нужно подписаться на каналы.\nПосле подписки нажмите кнопку проверки."
    try:
        if query: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception as e:
        if "Message is not modified" not in str(e): logging.error(e)
    return False

# ========================= ГЛАВНОЕ МЕНЮ =========================
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_new_message=False):
    context.user_data.pop("awaiting", None)
    
    user_id = update.effective_user.id
    username = update.effective_user.username or "unknown"
    
    if not db.get_user(user_id): db.create_user(user_id, username)
    if not await check_sub(update, context): return
    
    has_premium = db.has_premium(user_id)
    refs = db.get_refs(user_id)
    is_admin = db.is_admin(user_id)
    
    kb = []
    if has_premium: kb.append([InlineKeyboardButton("Протокол атаки", callback_data="attack")])
    elif refs >= 5: kb.append([InlineKeyboardButton("Оформить Premium", callback_data="buy")])
    else: kb.append([InlineKeyboardButton("Атака (нужно 5 рефералов)", callback_data="no_access")])
    
    kb.append([InlineKeyboardButton("Скам-метка", callback_data="scam")])
    kb.append([InlineKeyboardButton("Рефералы", callback_data="refs"), InlineKeyboardButton("Профиль", callback_data="profile")])
    kb.append([InlineKeyboardButton("Связь", callback_data="support")])
    if is_admin: kb.append([InlineKeyboardButton("Админ-панель", callback_data="admin")])
    
    text = f"{bold('Shark bot')}\n\nЮзернейм: {mono('@' + username)}\nСтатус: {bold('online')}\n\n{quote('Здесь ты можешь веселиться. Выбери раздел ниже:')}"
    
    try:
        if is_new_message: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML, message_effect_id=FIRE_EFFECT_ID)
        else: await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    except Exception as e:
        if "Message is not modified" not in str(e): logging.error(e)

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("awaiting", None)
    await main_menu(update, context, is_new_message=False)

# ========================= ОБРАБОТЧИК СООБЩЕНИЙ =========================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("awaiting")
    
    if state == "attack": await handle_attack(update, context)
    elif state == "scam": await handle_scam(update, context)
    elif state == "support": await handle_support(update, context)
    elif state == "admin_reply": await handle_admin_reply(update, context)
    elif state == "admin_broadcast": await handle_broadcast(update, context)
    elif state == "admin_user_search": await handle_admin_user_search(update, context)
    elif state == "admin_give_prem": await handle_admin_give_prem(update, context)
    elif state == "add_channel_id": await handle_add_channel_id(update, context)
    elif state == "add_channel_link": await handle_add_channel_link(update, context)
    elif state == "add_channel_name": await handle_add_channel_name(update, context)
    elif state == "remove_channel": await handle_remove_channel(update, context)
    elif state == "add_admin": await handle_add_admin(update, context)
    elif state == "remove_admin": await handle_remove_admin(update, context)

# ========================= ПРОФИЛЬ =========================
async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_sub(update, context): return
    user_id = update.callback_query.from_user.id
    user = db.get_user(user_id)
    prem_end = db.get_premium_status(user_id)
    premium_text = f"Активен (осталось: {format_timedelta(prem_end - datetime.now())})" if prem_end else "Не активен"
    text = f"{bold('Профиль агента')}\n\nID: {mono(str(user_id))}\nUsername: {mono('@' + (user['username'] or 'unknown'))}\n\nДоступ: {bold(premium_text)}\nРефералов: {bold(str(user['refs_count']))}\nМеток выдано: {bold(str(db.get_scam_marks_count(user_id)))}\nВыполнено атак: {bold(str(user['total_attacks']))}"
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="menu")]]), parse_mode=ParseMode.HTML)

# ========================= РЕФЕРАЛЫ =========================
async def refs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_sub(update, context): return
    uid = update.callback_query.from_user.id
    refs = db.get_refs(uid)
    link = f"https://t.me/{context.bot.username}?start=ref_{uid}"
    text = f"{bold('Реферальная сеть')}\n\nПриглашено: {bold(str(refs))}\n"
    if refs < 5: text += f"Осталось до Premium: {bold(str(5 - refs))}\n\n"
    else: text += "Доступ к атакам открыт.\n\n"
    text += f"{quote('Ваша ссылка для приглашения:')}\n{mono(link)}"
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="menu")]]), parse_mode=ParseMode.HTML)

# ========================= АТАКА =========================
async def attack_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_sub(update, context): return
    query = update.callback_query
    if not db.has_premium(query.from_user.id):
        await query.edit_message_text(f"{bold('Доступ закрыт')}\n\nНеобходим Premium статус.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="menu")]]), parse_mode=ParseMode.HTML)
        return
    context.user_data["awaiting"] = "attack"
    await query.edit_message_text(f"{bold('Протокол атаки')}\n\n{quote('Введите цель (username или ссылку):')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="menu")]]), parse_mode=ParseMode.HTML)

async def handle_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    user_id = update.effective_user.id
    target = escape(update.message.text.strip())
    if not db.has_premium(user_id):
        await update.message.reply_text(f"{bold('Ошибка')}\nНет доступа.", parse_mode=ParseMode.HTML)
        return
    db.add_attack(user_id)
    msg = await update.message.reply_text(f"Инициализация атаки на {mono(target)}...", parse_mode=ParseMode.HTML)
    stages = ["Загрузка модулей... [20%]", f"Подключение к {mono(target)}... [50%]", "Инъекция пакетов... [80%]", "Завершение... [100%]"]
    for stage in stages:
        await asyncio.sleep(1.2)
        try: await msg.edit_text(stage, parse_mode=ParseMode.HTML)
        except: pass
    await asyncio.sleep(1)
    await msg.edit_text(f"{bold('Атака завершена')}\n\nЦель {mono(target)} нейтрализована.", parse_mode=ParseMode.HTML)

# ========================= СКАМ-МЕТКА =========================
async def scam_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_sub(update, context): return
    context.user_data["awaiting"] = "scam"
    await update.callback_query.edit_message_text(f"{bold('Скам-метка')}\n\nСтоимость: {bold('1 USDT')}\n\n{quote('Введите @username цели:')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="menu")]]), parse_mode=ParseMode.HTML)

async def handle_scam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    target = update.message.text.strip().replace("@", "")
    msg = await update.message.reply_text("Создание счета...", parse_mode=ParseMode.HTML)
    invoice = await create_crypto_invoice(1.0, f"scam|{update.effective_user.id}|{target}")
    if not invoice:
        await msg.edit_text("Ошибка платежной системы.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="menu")]]))
        return
    kb = [[InlineKeyboardButton("Оплатить 1 USDT", url=invoice['pay_url'])], [InlineKeyboardButton("Проверить оплату", callback_data=f"checkpay_{invoice['invoice_id']}")], [InlineKeyboardButton("Отмена", callback_data="menu")]]
    await msg.edit_text(f"{bold('Верификация метки')}\n\nЦель: {mono('@' + target)}\n\nОжидание оплаты...", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

# ========================= ПРЕМИУМ =========================
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_sub(update, context): return
    query = update.callback_query
    if db.get_refs(query.from_user.id) < 5:
        await query.edit_message_text(f"{bold('Доступ закрыт')}\nНужно 5 рефералов.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="menu")]]), parse_mode=ParseMode.HTML)
        return
    kb = [[InlineKeyboardButton(f"{d} дн. - {p} USDT", callback_data=f"buytariff_{d}")] for d, p in [(1, 0.5), (3, 1.0), (7, 2.0), (30, 4.0)]]
    kb.append([InlineKeyboardButton("Отмена", callback_data="menu")])
    await query.edit_message_text(f"{bold('Premium лицензия')}\n\nВыберите тариф:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def buy_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    days = int(query.data.split("_")[1])
    amount = {1: 0.5, 3: 1.0, 7: 2.0, 30: 4.0}.get(days, 1.0)
    await query.edit_message_text("Создание счета...", parse_mode=ParseMode.HTML)
    invoice = await create_crypto_invoice(amount, f"prem|{query.from_user.id}|{days}")
    if not invoice:
        await query.edit_message_text("Ошибка создания счета.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="menu")]]))
        return
    kb = [[InlineKeyboardButton("Оплатить", url=invoice['pay_url'])], [InlineKeyboardButton("Проверить оплату", callback_data=f"checkpay_{invoice['invoice_id']}")], [InlineKeyboardButton("Отмена", callback_data="menu")]]
    await query.edit_message_text(f"{bold('Оплата лицензии')}\n\nСрок: {days} дн.\nСумма: {amount} USDT", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    invoice_id = int(query.data.split("_")[1])
    if db.is_invoice_paid(invoice_id):
        await query.answer("Уже обработан.", show_alert=True)
        return
    inv = await get_crypto_invoice(invoice_id)
    if not inv:
        await query.answer("Ошибка проверки.", show_alert=True)
        return
    status = inv.get("status")
    if status == "active": await query.answer("Оплата не найдена.", show_alert=True)
    elif status == "paid":
        db.mark_invoice_paid(invoice_id)
        parts = inv.get("payload", "").split("|")
        if parts[0] == "scam":
            db.add_scam_mark(int(parts[1]), parts[2], f"Статус: недоверие\nОбъект: @{parts[2]}\nПодтверждено системой")
            await query.edit_message_text(f"{bold('Оплата подтверждена')}\n\nМетка добавлена в базу.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В меню", callback_data="menu")]]), parse_mode=ParseMode.HTML)
        elif parts[0] == "prem":
            db.activate_premium(int(parts[1]), int(parts[2]))
            await query.message.delete()
            await context.bot.send_message(chat_id=int(parts[1]), text=f"{bold('Premium активирован')}\n\nДоступ открыт на {parts[2]} дн.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В терминал", callback_data="menu")]]), parse_mode=ParseMode.HTML, message_effect_id=FIRE_EFFECT_ID)
    else:
        await query.answer("Счет истек.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В меню", callback_data="menu")]]))

# ========================= ПОДДЕРЖКА =========================
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_sub(update, context): return
    context.user_data["awaiting"] = "support"
    await update.callback_query.edit_message_text(f"{bold('Связь с админом')}\n\n{quote('Напишите ваше сообщение:')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="menu")]]), parse_mode=ParseMode.HTML)

async def handle_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    uid = update.effective_user.id
    msg = update.message.text.strip()
    ticket_id = db.add_ticket(uid, msg)
    for admin in db.get_admins():
        try: await context.bot.send_message(admin["user_id"], f"Тикет #{ticket_id}\nОт: {mono(str(uid))}\n\n{quote(msg)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Ответить", callback_data=f"reply_{ticket_id}_{uid}")]]), parse_mode=ParseMode.HTML)
        except: pass
    await update.message.reply_text("Сообщение отправлено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В меню", callback_data="menu")]]), parse_mode=ParseMode.HTML)

async def reply_ticket_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not db.is_admin(query.from_user.id): return
    parts = query.data.split("_")
    context.user_data["reply_user"] = parts[2]
    context.user_data["awaiting"] = "admin_reply"
    await query.edit_message_text(f"{bold('Терминал админа')}\n\nВведите ответ:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="menu")]]), parse_mode=ParseMode.HTML)

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    try:
        await context.bot.send_message(int(context.user_data.pop("reply_user")), f"{bold('Ответ администратора')}\n\n{quote(update.message.text.strip())}", parse_mode=ParseMode.HTML)
        await update.message.reply_text(f"{bold('Отправлено.')}", parse_mode=ParseMode.HTML)
    except: await update.message.reply_text(f"{bold('Сбой доставки.')}", parse_mode=ParseMode.HTML)

# ========================= АДМИН-ПАНЕЛЬ =========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not db.is_admin(query.from_user.id): return
    stats = db.get_stats()
    text = f"{bold('Админ-панель')}\n\nЮзеров: {stats['users']}\nPremium: {stats['premium']}\nАтак: {stats['attacks']}"
    kb = [[InlineKeyboardButton("Управление агентами", callback_data="admin_users")], [InlineKeyboardButton("Каналы", callback_data="admin_channels")], [InlineKeyboardButton("Админы", callback_data="admin_admins")], [InlineKeyboardButton("Рассылка", callback_data="admin_broadcast")], [InlineKeyboardButton("В главное меню", callback_data="menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def admin_user_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "admin_user_search"
    await update.callback_query.edit_message_text("Введите ID пользователя:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin")]]))

async def handle_admin_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    try: target_id = int(update.message.text.strip())
    except: await update.message.reply_text("Неверный ID.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin")]])); return
    user = db.get_user(target_id)
    if not user: await update.message.reply_text("Пользователь не найден.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin")]])); return
    
    invited_by = db.get_invited_by(target_id)
    refs_list = db.get_refs_list(target_id)
    refs_info = ""
    if invited_by:
        inviter = db.get_user(invited_by)
        if inviter: refs_info += f"Приглашен: @{inviter['username']} (ID: {invited_by})\n"
    if refs_list:
        refs_info += f"Пригласил: {len(refs_list)} чел.\n"
        for r in refs_list:
            refs_info += f"  - @{r['username']} (ID: {r['user_id']})\n"
    if not refs_info:
        refs_info = "Нет данных\n"
    
    text = f"ID: {target_id}\n@{user['username']}\nPrem: {'да' if db.has_premium(target_id) else 'нет'}\nБан: {'ДА' if user['is_blocked'] else 'НЕТ'}\nРефералов: {user['refs_count']}\nref_credited: {user['ref_credited']}\n\nРеферальная информация:\n{refs_info}"
    kb = [[InlineKeyboardButton("Выдать Premium", callback_data=f"admingiveprem_{target_id}")], [InlineKeyboardButton("Разбан" if user["is_blocked"] else "Бан", callback_data=f"adminblock_{target_id}")], [InlineKeyboardButton("В панель", callback_data="admin")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def admin_block_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tid = int(q.data.split("_")[1])
    user = db.get_user(tid)
    if user: db.set_blocked(tid, not user["is_blocked"])
    await q.edit_message_text("Статус обновлен.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin")]]))

async def admin_give_prem_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data["target_prem_id"] = int(q.data.split("_")[1])
    context.user_data["awaiting"] = "admin_give_prem"
    await q.edit_message_text("Дней (0 = снять):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="admin")]]))

async def handle_admin_give_prem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    try:
        d = int(update.message.text.strip())
        tid = context.user_data.pop("target_prem_id")
        db.activate_premium(tid, d)
        await update.message.reply_text("Готово.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В панель", callback_data="admin")]]))
    except: await update.message.reply_text("Ошибка.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В панель", callback_data="admin")]]))

# ========================= КАНАЛЫ =========================
async def admin_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chs = db.get_channels()
    clist = "\n".join([f"[{c['id']}] {c['channel_name']} | {c['channel_id']}" for c in chs]) if chs else "Пусто"
    kb = [[InlineKeyboardButton("Добавить", callback_data="add_channel"), InlineKeyboardButton("Удалить", callback_data="remove_channel")], [InlineKeyboardButton("Назад", callback_data="admin")]]
    await q.edit_message_text(f"{bold('Каналы')}\n\n{clist}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "add_channel_id"
    await update.callback_query.edit_message_text("Шаг 1. ID канала:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="admin_channels")]]))

async def handle_add_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_ch_id"] = update.message.text.strip()
    context.user_data["awaiting"] = "add_channel_link"
    await update.message.reply_text("Шаг 2. Ссылка на канал:")

async def handle_add_channel_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if url.startswith("@"): url = f"https://t.me/{url[1:]}"
    elif url.startswith("t.me/"): url = f"https://{url}"
    elif not url.startswith("http"): url = f"https://t.me/{url}"
    context.user_data["new_ch_url"] = url
    context.user_data["awaiting"] = "add_channel_name"
    await update.message.reply_text("Шаг 3. Название:")

async def handle_add_channel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    db.add_channel(update.message.text.strip(), context.user_data.pop("new_ch_url"), context.user_data.pop("new_ch_id"))
    await update.message.reply_text("Добавлено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin_channels")]]))

async def remove_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "remove_channel"
    await update.callback_query.edit_message_text("ID канала в БД:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="admin_channels")]]))

async def handle_remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    db.remove_channel(int(update.message.text.strip()))
    await update.message.reply_text("Удален.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin_channels")]]))

# ========================= АДМИНЫ И РАССЫЛКА =========================
async def admin_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    al = "\n".join([str(a['user_id']) for a in db.get_admins()])
    kb = [[InlineKeyboardButton("Добавить", callback_data="add_admin"), InlineKeyboardButton("Удалить", callback_data="remove_admin")], [InlineKeyboardButton("Назад", callback_data="admin")]]
    await q.edit_message_text(f"{bold('Админы')}\n\n{al}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "add_admin"
    await update.callback_query.edit_message_text("ID админа:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="admin_admins")]]))

async def handle_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    db.set_admin(int(update.message.text.strip()), True)
    await update.message.reply_text("Добавлен.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin_admins")]]))

async def remove_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "remove_admin"
    await update.callback_query.edit_message_text("ID для удаления:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="admin_admins")]]))

async def handle_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    rem_id = int(update.message.text.strip())
    if rem_id != OWNER_ID: db.set_admin(rem_id, False)
    await update.message.reply_text("Удален.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin_admins")]]))

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "admin_broadcast"
    await update.callback_query.edit_message_text("Текст рассылки:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="admin")]]))

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting", None)
    text = update.message.text
    users = db.fetchall("SELECT user_id FROM users WHERE is_blocked = 0")
    sent = 0
    for user in users:
        try: await context.bot.send_message(user["user_id"], f"{bold('Глобальное уведомление')}\n\n{text}", parse_mode=ParseMode.HTML); sent += 1
        except: pass
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"Разослано: {sent}/{len(users)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin")]]))

# ========================= СТАРТ =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or "unknown"
    
    invited_by = 0
    if context.args and context.args[0].startswith("ref_"):
        try:
            invited_by = int(context.args[0].split("_")[1])
            if invited_by == uid: invited_by = 0
        except: invited_by = 0
    
    if not db.get_user(uid):
        db.create_user(uid, uname, invited_by)
    
    await main_menu(update, context, is_new_message=True)

async def no_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer("Нужно 5 рефералов для доступа.", show_alert=True)

# ========================= ЗАПУСК =========================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(profile_callback, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(refs_callback, pattern="^refs$"))
    app.add_handler(CallbackQueryHandler(no_access, pattern="^no_access$"))
    app.add_handler(CallbackQueryHandler(attack_start, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(scam_start, pattern="^scam$"))
    app.add_handler(CallbackQueryHandler(buy_menu, pattern="^buy$"))
    app.add_handler(CallbackQueryHandler(buy_tariff, pattern="^buytariff_"))
    app.add_handler(CallbackQueryHandler(support_start, pattern="^support$"))
    app.add_handler(CallbackQueryHandler(reply_ticket_start, pattern="^reply_"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_user_search_start, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_block_action, pattern="^adminblock_"))
    app.add_handler(CallbackQueryHandler(admin_give_prem_start, pattern="^admingiveprem_"))
    app.add_handler(CallbackQueryHandler(admin_channels, pattern="^admin_channels$"))
    app.add_handler(CallbackQueryHandler(add_channel_start, pattern="^add_channel$"))
    app.add_handler(CallbackQueryHandler(remove_channel_start, pattern="^remove_channel$"))
    app.add_handler(CallbackQueryHandler(admin_admins, pattern="^admin_admins$"))
    app.add_handler(CallbackQueryHandler(add_admin_start, pattern="^add_admin$"))
    app.add_handler(CallbackQueryHandler(remove_admin_start, pattern="^remove_admin$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(check_payment, pattern="^checkpay_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    logging.info("Shark Terminal запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
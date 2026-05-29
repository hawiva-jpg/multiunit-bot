"""
Telegram-бот для Railway — данные хранятся в базе сервера.
"""

import os, re, logging, json
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    ContextTypes, filters
)
import httpx

TOKEN      = os.getenv("TG_BOT_TOKEN", "ВСТАВЬ_ТОКЕН")
API_URL    = os.getenv("API_URL", "https://multi-production-0cab.up.railway.app")
BOT_SECRET = os.getenv("BOT_SECRET", "multiunit-bot-2026")
BOT_HEADERS = {"x-bot-secret": BOT_SECRET}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# ── API хелперы ───────────────────────────────────────────────────────────────
async def api(method, path, data=None):
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            if method == "GET":
                r = await c.get(f"{API_URL}{path}", headers=BOT_HEADERS)
            elif method == "POST":
                r = await c.post(f"{API_URL}{path}", json=data, headers=BOT_HEADERS)
            elif method == "PUT":
                r = await c.put(f"{API_URL}{path}", json=data, headers=BOT_HEADERS)
            elif method == "DELETE":
                r = await c.delete(f"{API_URL}{path}", headers=BOT_HEADERS)
            if r.status_code == 200:
                return r.json()
            logging.error(f"API {method} {path}: {r.status_code} {r.text[:100]}")
            return None
    except Exception as e:
        logging.error(f"API error {method} {path}: {e}")
        return None

async def get_doctors():
    return await api("GET", "/api/bot/tg-doctors") or {}

async def save_doctor(surname, chat_id):
    await api("POST", "/api/bot/tg-doctors", {"surname": surname, "chat_id": chat_id})

async def get_pending():
    data = await api("GET", "/api/bot/tg-pending") or {}
    return {int(k): v for k, v in data.items()}

async def save_pending(msg_id, order_id, group_chat_id=None):
    await api("POST", "/api/bot/tg-pending", {"msg_id": msg_id, "order_id": order_id, "group_chat_id": group_chat_id})

async def del_pending(msg_id):
    await api("DELETE", f"/api/bot/tg-pending/{msg_id}")

async def api_create_order(data):
    return await api("POST", "/api/orders", data)

async def api_get_order(order_id):
    result = await api("GET", f"/api/bot/order/{order_id}")
    return result

async def api_update_order(order_id, data):
    return await api("PUT", f"/api/bot/order/{order_id}", data)

# ── Парсинг ───────────────────────────────────────────────────────────────────
def parse_order(text):
    text = text.strip()
    result = {}

    # ── Короткий формат: ЛТЛ-Новиков-23.07.2026 или ЛТЛ-Новиков-23.07.2026-Комментарий ──
    short = re.match(r'^([А-ЯЁа-яёA-Za-z.\s]+?)-([А-ЯЁа-яёA-Za-z.\s]+?)-(\d{2}\.\d{2}\.\d{4})(?:-(.+))?$', text.strip())
    if short:
        try:
            d = datetime.strptime(short.group(3).strip(), "%d.%m.%Y")
            result['doctor']   = short.group(1).strip()
            result['patient']  = short.group(2).strip()
            result['due_date'] = d.strftime("%Y-%m-%d")
            result['comment']  = short.group(4).strip() if short.group(4) else ""
            return result
        except: pass

    # ── Полный формат: Пациент: ... | Доктор: ... | Дата: ... ──
    m = re.search(r'пациент[:\s]+([^|,\n]+)', text, re.IGNORECASE)
    if m: result['patient'] = m.group(1).strip()
    m = re.search(r'доктор[:\s]+([^|,\n]+)', text, re.IGNORECASE)
    if m: result['doctor'] = m.group(1).strip()
    m = re.search(r'дата[:\s]+([\d.]+)', text, re.IGNORECASE)
    if m:
        try:
            d = datetime.strptime(m.group(1).strip(), "%d.%m.%Y")
            result['due_date'] = d.strftime("%Y-%m-%d")
        except: pass
    m = re.search(r'(коммент|примечание)[:\s]+([^|,\n]+)', text, re.IGNORECASE)
    if m: result['comment'] = m.group(2).strip()
    if result.get('patient') and result.get('doctor') and result.get('due_date'):
        return result
    return None

UNIT_KEYWORDS = {
    "прямой": "Мультиюнит прямой 0°", "0°": "Мультиюнит прямой 0°",
    "17°": "Мультиюнит угловой 17°", "угловой 17": "Мультиюнит угловой 17°",
    "30°": "Мультиюнит угловой 30°", "угловой 30": "Мультиюнит угловой 30°",
    "45°": "Мультиюнит угловой 45°", "угловой 45": "Мультиюнит угловой 45°",
    "абатмент": "Абатмент мультиюнит", "колпачок": "Колпачок мультиюнит",
    "винт": "Винт фиксирующий", "заглушка": "Заглушка мультиюнит",
}

def parse_units(text):
    units = []
    for line in [l.strip() for l in text.split('\n') if l.strip()]:
        if line.startswith('/'): continue
        low = line.lower()
        unit = {"type": "Другое", "length": "", "tooth": "", "system": "", "qty": 1}
        for keyword, utype in UNIT_KEYWORDS.items():
            if keyword.lower() in low:
                unit['type'] = utype
                break
        m = re.search(r'(\d+)\s*мм', low)
        if m: unit['length'] = f"{m.group(1)} мм"
        m = re.search(r'(?:зуб[:\s#]*)(\d+)', low)
        if m: unit['tooth'] = m.group(1)
        else:
            nums = re.findall(r'\b([1-4][1-8])\b', low)
            if nums: unit['tooth'] = nums[0]
        for sys in ['nobel','straumann','osstem','megagen','mis','ankylos','neobiotech']:
            if sys in low:
                unit['system'] = sys.title()
                break
        m = re.search(r'[хx]\s*(\d+)|(\d+)\s*шт', low)
        if m: unit['qty'] = int(m.group(1) or m.group(2))
        if unit['type'] != 'Другое' or unit['tooth']:
            units.append(unit)
    return units

# ── Вспомогательные ───────────────────────────────────────────────────────────
async def send_result(msg, order, units, order_id):
    units_text = "\n".join(
        f"• {u['type']}"
        + (f" · {u['length']}" if u['length'] else "")
        + (f" · зуб #{u['tooth']}" if u['tooth'] else "")
        + (f" · {u['system']}" if u['system'] else "")
        + f" ×{u['qty']}"
        for u in units
    )
    await msg.reply_text(
        f"✅ <b>Заказ #{order_id} обновлён!</b>\n\n"
        f"👤 {order['patient']}  |  Д-р {order['doctor']}\n"
        f"📅 {order['due_date']}\n"
        f"🔧 Статус: В работе\n\n"
        f"<b>Мультиюниты ({len(units)}):</b>\n{units_text}",
        parse_mode="HTML"
    )

UNITS_HINT = (
    "<b>Ankylos:</b>\n• МЮ прямой 0° 1мм\n• МЮ прямой 0° 2мм\n• МЮ прямой 0° 3мм\n• МЮ угловой 17° 3мм\n• МЮ угловой 30° 3мм\n\n"
    "<b>Neobiotech:</b>\n• МЮ прямой 0° 1мм\n• МЮ прямой 0° 2мм\n• МЮ прямой 0° 3мм\n• МЮ угловой 17°\n• МЮ угловой 30°\n\n"
    "<b>Nobel:</b>\n• МЮ прямой 0° 1мм\n• МЮ прямой 0° 2мм\n• МЮ прямой 0° 3мм\n• МЮ угловой 17° 3мм\n• МЮ угловой 30° 3мм\n\n"
    "<b>Straumann:</b>\n• МЮ прямой 0° 1мм\n• МЮ прямой 0° 2мм\n• МЮ прямой 0° 3мм\n• МЮ угловой 17° 3мм\n• МЮ угловой 30° 3мм"
)

# ── Команды ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if update.effective_chat.type == "private":
        await msg.reply_text(
            f"👋 Привет, {update.effective_user.full_name}!\n\n"
            f"Напиши свою фамилию (как в программе):"
        )
        ctx.user_data['awaiting_surname'] = True
        return
    await msg.reply_text(
        "🔩 <b>Бот учёта мультиюнитов активен!</b>\n\n"
        "Формат заказа:\n"
        "<code>Пациент: Иванов А.В. | Доктор: Смирнова | Дата: 10.07.2026</code>",
        parse_mode="HTML"
    )

async def cmd_mydoctors(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doctors = await get_doctors()
    if not doctors:
        await update.message.reply_text(
            "Нет зарегистрированных докторов.\n\n"
            "Чтобы добавить — доктор пишет /start боту в личку."
        )
        return
    lines = "\n".join(f"• {n}" for n in doctors)
    await update.message.reply_text(
        f"👨‍⚕️ <b>Зарегистрированные доктора:</b>\n\n{lines}\n\n"
        f"Чтобы удалить: /removedoctor Фамилия\n"
        f"Чтобы добавить: /adddoctor Фамилия",
        parse_mode="HTML"
    )

async def cmd_removedoctor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Укажите фамилию: /removedoctor Иванов")
        return
    surname = " ".join(ctx.args).strip()
    doctors = await get_doctors()
    # Ищем совпадение без учёта регистра
    found = next((k for k in doctors if k.lower() == surname.lower()), None)
    if not found:
        await update.message.reply_text(f"❌ Доктор «{surname}» не найден.")
        return
    await api("DELETE", f"/api/bot/tg-doctors/{found}", None)
    await update.message.reply_text(f"✅ Доктор «{found}» удалён из системы.")

async def cmd_adddoctor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Укажите фамилию и chat_id: /adddoctor Иванов 123456789\n\nЧтобы узнать chat_id доктора — попросите его написать @userinfobot")
        return
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "Укажите фамилию и chat_id:\n/adddoctor Иванов 123456789\n\n"
            "Проще попросить доктора написать /start боту в личку — он зарегистрируется сам!"
        )
        return
    surname = ctx.args[0]
    try:
        chat_id = int(ctx.args[1])
    except:
        await update.message.reply_text("❌ chat_id должен быть числом.")
        return
    await save_doctor(surname, chat_id)
    await update.message.reply_text(f"✅ Доктор «{surname}» добавлен!")

# ── Обработка сообщений ───────────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text: return
    text = msg.text.strip()
    chat = update.effective_chat

    # ── ЛИЧКА ─────────────────────────────────────────────────────────────────
    if chat.type == "private":
        if ctx.user_data.get('awaiting_surname'):
            surname = text.strip()
            await save_doctor(surname, msg.chat_id)
            ctx.user_data['awaiting_surname'] = False
            await msg.reply_text(
                f"✅ Зарегистрирован как доктор <b>{surname}</b>.\n\n"
                f"Когда придёт заказ — ответьте на моё сообщение списком мультиюнитов.",
                parse_mode="HTML"
            )
            logging.info(f"Registered: {surname} -> {msg.chat_id}")
            return

        # Reply на уведомление
        if msg.reply_to_message:
            replied_text = msg.reply_to_message.text or ""
            replied_msg_id = msg.reply_to_message.message_id
            order_id = None
            group_chat_id = None
            pending = await get_pending()
            if replied_msg_id in pending:
                pdata = pending[replied_msg_id]
                order_id = pdata.get("order_id")
                group_chat_id = pdata.get("group_chat_id")
            else:
                m = re.search(r'[Зз]аказ\s*#?(\d+)', replied_text)
                if m: order_id = int(m.group(1))
            if order_id:
                units = parse_units(text)
                if not units:
                    await msg.reply_text("❌ Не распознал.\n\nПример:\n<code>Угловой 17°, зуб 16, Nobel, 4мм</code>", parse_mode="HTML")
                    return
                order = await api_get_order(order_id)
                if not order:
                    await msg.reply_text(f"❌ Заказ #{order_id} не найден.")
                    return
                all_units = (order.get('units') or []) + units
                updated = await api_update_order(order_id, {**order, 'status': 'progress', 'units': all_units})
                if updated:
                    await send_result(msg, order, units, order_id)
                    if group_chat_id:
                        try:
                            units_text = "\n".join(f"• {u['type']}{' · '+u['length'] if u['length'] else ''}{' · зуб #'+u['tooth'] if u['tooth'] else ''} ×{u['qty']}" for u in units)
                            await ctx.bot.send_message(
                                chat_id=group_chat_id,
                                text=f"✅ <b>Заказ #{order_id} обновлён доктором!</b>\n\n👤 {order['patient']}  |  Д-р {order['doctor']}\n📅 {order['due_date']}\n🔧 Статус: В работе\n\n<b>Мультиюниты ({len(units)}):</b>\n{units_text}",
                                parse_mode="HTML",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            logging.error(f"Group notify error: {e}")
                    await del_pending(replied_msg_id)
                return

        # Формат "Заказ N: ..."
        m = re.match(r'(?:заказ|#)\s*(\d+)[:\s]+(.+)', text, re.IGNORECASE | re.DOTALL)
        if m:
            order_id = int(m.group(1))
            units = parse_units(m.group(2))
            if units:
                order = await api_get_order(order_id)
                if order:
                    all_units = (order.get('units') or []) + units
                    await api_update_order(order_id, {**order, 'status': 'progress', 'units': all_units})
                    await send_result(msg, order, units, order_id)
                else:
                    await msg.reply_text(f"❌ Заказ #{order_id} не найден.")
        return

    # ── ГРУППА: создание заказа ───────────────────────────────────────────────
    if re.search(r'пациент', text, re.IGNORECASE) and re.search(r'доктор', text, re.IGNORECASE):
        order_data = parse_order(text)
        if not order_data:
            await msg.reply_text("❌ Формат:\n<code>Пациент: Иванов | Доктор: Смирнова | Дата: 10.07.2026</code>", parse_mode="HTML")
            return
        order_data.update({'status': 'new', 'units': []})
        order = await api_create_order(order_data)
        if not order or 'id' not in order:
            await msg.reply_text("❌ Ошибка при создании заказа.")
            return
        order_id = order['id']
        reply = await msg.reply_text(
            f"✅ <b>Заказ #{order_id} создан!</b>\n\n"
            f"👤 Пациент: <b>{order_data['patient']}</b>\n"
            f"🩺 Доктор: <b>{order_data['doctor']}</b>\n"
            f"📅 Дата: <b>{order_data['due_date']}</b>\n\n"
            f"<i>Доктор {order_data['doctor']}, ответьте на это сообщение списком мультиюнитов.</i>",
            parse_mode="HTML"
        )
        await save_pending(reply.message_id, order_id, msg.chat_id)
        doctors = await get_doctors()
        for name, cid in doctors.items():
            if name.lower() in order_data['doctor'].lower() or order_data['doctor'].lower() in name.lower():
                try:
                    dm = await ctx.bot.send_message(
                        chat_id=cid,
                        text=(
                            f"🔔 <b>Новый заказ!</b>\n\n"
                            f"👤 Пациент: <b>{order_data['patient']}</b>\n"
                            f"📅 Дата: <b>{order_data['due_date']}</b>\n"
                            f"🆔 Заказ #{order_id}\n\n"
                            f"✍️ <b>Ответьте на это сообщение</b> списком мультиюнитов.\n"
                            f"Укажите: тип, зуб, систему, длину.\n\n"
                            f"{UNITS_HINT}"
                        ),
                        parse_mode="HTML"
                    )
                    await save_pending(dm.message_id, order_id, msg.chat_id)
                    logging.info(f"Notified {name} (chat_id={cid})")
                except Exception as e:
                    logging.error(f"Notify error: {e}")
                break
        return

    # ── ГРУППА: ответ доктора ────────────────────────────────────────────────
    if msg.reply_to_message:
        replied_text = msg.reply_to_message.text or ""
        logging.info(f"Reply to: '{replied_text[:60]}'")
        m = re.search(r'[Зз]аказ\s*#?(\d+)', replied_text)
        if not m: return
        order_id = int(m.group(1))
        units = parse_units(text)
        logging.info(f"order_id={order_id}, units={len(units)}")
        if not units:
            await msg.reply_text("❌ Не распознал.\n\nПример:\n<code>Угловой 17°, зуб 16, Nobel, 4мм</code>", parse_mode="HTML")
            return
        order = await api_get_order(order_id)
        if not order:
            await msg.reply_text(f"❌ Заказ #{order_id} не найден.")
            return
        all_units = (order.get('units') or []) + units
        updated = await api_update_order(order_id, {**order, 'status': 'progress', 'units': all_units})
        if not updated:
            await msg.reply_text("❌ Ошибка обновления.")
            return
        await send_result(msg, order, units, order_id)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("mydoctors", cmd_mydoctors))
    app.add_handler(CommandHandler("removedoctor", cmd_removedoctor))
    app.add_handler(CommandHandler("adddoctor", cmd_adddoctor))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()

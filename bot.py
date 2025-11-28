# bot.py
import json
import os
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Please set the BOT_TOKEN environment variable")

DATA_FILE = "orders.json"
GROUP_ID = -1001234567890  # Replace with your Telegram group ID
ADMINS = [123456789, 987654321]  # Replace with admin Telegram IDs

# ----------------------------
# STATUS MAPPING
# ----------------------------
STATUS_MAP = {
    "out": "Out for delivery",
    "on the way": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)

# ----------------------------
# DATA HANDLING
# ----------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ----------------------------
# GROUP MESSAGE HANDLER
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return  # Only allow updates from the designated group

    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)
    if not match:
        return

    orders_raw = match.group("orders")
    status_raw = match.group("status").lower().strip()
    status = STATUS_MAP.get(status_raw, status_raw)

    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    data = load_data()
    agent_name = update.message.from_user.full_name

    for order_id in order_list:
        data.setdefault(order_id, []).append({
            "status": status,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agent": agent_name
        })

    save_data(data)
    await update.message.reply_text(
        f"Updated {len(order_list)} order(s): {', '.join(order_list)}"
    )

# ----------------------------
# PRIVATE COMMANDS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me an order number to get its current status."
    )

async def private_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Send only the order number (digits only).")
        return

    data = load_data()
    if text in data:
        last_update = data[text][-1]
        await update.message.reply_text(
            f"Order: {text}\nStatus: {last_update['status']}\n"
            f"Updated: {last_update['timestamp']}\nAgent: {last_update['agent']}"
        )
    else:
        await update.message.reply_text("No record found for this order.")

# ----------------------------
# HISTORY (admin only)
# ----------------------------
PAGE_SIZE = 10

def build_history_buttons(total_pages, current_page):
    buttons = []
    for i in range(1, total_pages + 1):
        buttons.append(InlineKeyboardButton(str(i), callback_data=f"history:{i}"))
    return build_menu(buttons, 5)

def build_menu(buttons, n_cols):
    return [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    data = load_data()
    order_ids = list(data.keys())
    total_pages = (len(order_ids) - 1) // PAGE_SIZE + 1

    page = 1
    await send_history_page(update, context, page, order_ids, total_pages)

async def send_history_page(update, context, page, order_ids, total_pages):
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    display_orders = order_ids[start_idx:end_idx]

    message_text = ""
    data = load_data()
    for order_id in display_orders:
        updates = data[order_id]
        last = updates[-1]
        message_text += f"Order: {order_id}\nStatus: {last['status']}\n"
        message_text += f"Agent: {last['agent']}\nTime: {last['timestamp']}\n\n"

    buttons = build_history_buttons(total_pages, page)
    markup = InlineKeyboardMarkup(buttons) if buttons else None

    await update.message.reply_text(message_text.strip(), reply_markup=markup)

async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[1])

    data = load_data()
    order_ids = list(data.keys())
    total_pages = (len(order_ids) - 1) // PAGE_SIZE + 1

    await query.edit_message_text(
        text=f"Page {page}/{total_pages}",
        reply_markup=None
    )
    # Send the page content as a new message
    display_orders = order_ids[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    message_text = ""
    for order_id in display_orders:
        updates = data[order_id]
        last = updates[-1]
        message_text += f"Order: {order_id}\nStatus: {last['status']}\n"
        message_text += f"Agent: {last['agent']}\nTime: {last['timestamp']}\n\n"
    await query.message.reply_text(message_text.strip())

# ----------------------------
# Delivery agent own orders
# ----------------------------
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent_name = update.message.from_user.full_name
    data = load_data()
    my_updates = []

    for order_id, updates in data.items():
        for u in updates:
            if u["agent"] == agent_name:
                my_updates.append((order_id, u))

    if not my_updates:
        await update.message.reply_text("You have not updated any orders yet.")
        return

    message_text = ""
    for order_id, u in my_updates:
        message_text += f"Order: {order_id}\nStatus: {u['status']}\nTime: {u['timestamp']}\n\n"

    await update.message.reply_text(message_text.strip())

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Group listener
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))

    # Private commands
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_lookup))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("myorders", my_orders))
    app.add_handler(CallbackQueryHandler(history_callback, pattern=r"history:\d+"))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

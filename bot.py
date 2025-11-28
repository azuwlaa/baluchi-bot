# bot.py
import json
import os
import re
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------------------
# CONFIGURATION
# ----------------------------
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"  # <-- Replace with your bot token
GROUP_ID = -1001234567890                    # <-- Replace with your group ID
ADMINS = [123456789, 987654321]             # <-- Replace with Telegram user IDs of admins
DATA_FILE = "orders.json"

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
# GROUP LISTENER (DELIVERY AGENTS)
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != GROUP_ID:
        return  # Only process messages from the specific group

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
    agent_id = update.message.from_user.id
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for order_id in order_list:
        # Save history per order
        if order_id not in data:
            data[order_id] = {"history": []}
        data[order_id]["history"].append({
            "status": status,
            "timestamp": timestamp,
            "agent_name": agent_name,
            "agent_id": agent_id
        })
        # Update latest status for convenience
        data[order_id]["latest"] = {
            "status": status,
            "timestamp": timestamp,
            "agent_name": agent_name
        }

    save_data(data)

    await update.message.reply_text(
        f"✅ Updated {len(order_list)} order(s): {', '.join(order_list)}"
    )

# ----------------------------
# PRIVATE LOOKUP
# ----------------------------
async def private_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text("Send only the order number.")
        return

    data = load_data()
    order_id = text
    user_id = update.message.from_user.id

    if order_id not in data:
        await update.message.reply_text("No record found for this order.")
        return

    order_info = data[order_id]
    # Check if admin
    if user_id in ADMINS:
        latest = order_info.get("latest", {})
        await update.message.reply_text(
            f"Order: {order_id}\n"
            f"Status: {latest.get('status')}\n"
            f"Updated: {latest.get('timestamp')}\n"
            f"By: {latest.get('agent_name')}"
        )
    else:
        # Check if this user has updated this order
        user_updates = [h for h in order_info["history"] if h["agent_id"] == user_id]
        if not user_updates:
            await update.message.reply_text("You have not updated this order.")
            return
        latest = user_updates[-1]
        await update.message.reply_text(
            f"Order: {order_id}\n"
            f"Your Status: {latest.get('status')}\n"
            f"Updated: {latest.get('timestamp')}"
        )

# ----------------------------
# COMMANDS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me an order number to get its status."
    )

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No orders yet.")
        return

    msg_lines = []
    count = 0
    for order_id, order_data in data.items():
        latest = order_data.get("latest", {})
        line = f"{order_id}: {latest.get('status')} by {latest.get('agent_name')} at {latest.get('timestamp')}"
        msg_lines.append(line)
        count += 1
        if count >= 10:  # paginate every 10
            break

    await update.message.reply_text("\n".join(msg_lines))

async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    data = load_data()
    user_lines = []

    for order_id, order_data in data.items():
        user_updates = [h for h in order_data["history"] if h["agent_id"] == user_id]
        if user_updates:
            latest = user_updates[-1]
            user_lines.append(
                f"{order_id}: {latest['status']} at {latest['timestamp']}"
            )

    if not user_lines:
        await update.message.reply_text("You have not updated any orders yet.")
    else:
        await update.message.reply_text("\n".join(user_lines))

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_lookup))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("myorders", myorders))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()

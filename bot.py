import json
import os
import re
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import asyncio

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = ""  # Add your bot token
GROUP_ID = -1003463796946
ADMINS = [624102836, 7477828866]
AGENT_LOG_CHANNEL = -1003484693080
DATA_FILE = "orders.json"

STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "air": "On the way to airport",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z]+)$", re.IGNORECASE)

# ----------------------------
# JSON STORAGE
# ----------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        save_data({})
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def now_gmt5():
    return datetime.now(timezone.utc) + timedelta(hours=5)

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
async def send_agent_log(context: ContextTypes.DEFAULT_TYPE, orders, agent_name, status_full, action="Update", user_id=None):
    orders_text = ", ".join(orders)
    agent_html = f'<a href="tg://user?id={user_id}">{agent_name}</a>' if user_id else agent_name
    message = (
        f"<b>#{action}</b>\n"
        f"• Orders#: {orders_text}\n"
        f"• Agent: {agent_html}\n"
        f"• Time: {now_gmt5().strftime('%H:%M')} ⏰\n"
        f"• Status: {status_full}"
    )
    await context.bot.send_message(
        chat_id=AGENT_LOG_CHANNEL,
        text=message,
        parse_mode="HTML"
    )

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, orders, agent_name):
    msg = f"⚠️ Order(s) {', '.join(orders)} marked as NO ANSWER by {agent_name}"
    for admin in ADMINS:
        try:
            await context.bot.send_message(chat_id=admin, text=msg)
        except:
            pass

# ----------------------------
# URGENT HANDLERS
# ----------------------------
async def urgent_private_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id
    text = update.message.text.lower()

    if "urgent" not in text:
        return

    if user_id not in ADMINS:
        return await update.message.reply_text("❌ Only admins can send urgent alerts.")

    numbers = re.findall(r"\b\d+\b", text)
    if not numbers:
        return await update.message.reply_text("❌ No order numbers found.")

    urgent_text = f"🚨 URGENT ORDERS: {', '.join(numbers)}"

    msg = await context.bot.send_message(
        chat_id=GROUP_ID,
        text=urgent_text
    )

    try:
        await context.bot.pin_chat_message(chat_id=GROUP_ID, message_id=msg.message_id)
    except:
        pass

    await update.message.reply_text("✅ Urgent message sent and pinned in group.")

async def urgent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Only admins can send urgent alerts.")

    args = update.message.text.split()
    if len(args) < 2:
        return await update.message.reply_text("Usage: /urgent 12345")

    orders = [o for o in args[1:] if o.isdigit()]
    if not orders:
        return await update.message.reply_text("❌ No valid order numbers provided.")

    urgent_text = f"🚨 URGENT ORDERS: {', '.join(orders)}"

    msg = await context.bot.send_message(
        chat_id=GROUP_ID,
        text=urgent_text
    )

    try:
        await context.bot.pin_chat_message(chat_id=GROUP_ID, message_id=msg.message_id)
    except:
        pass

    await update.message.reply_text("✅ Urgent message sent and pinned in group.")

# ----------------------------
# MESSAGE HANDLERS
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        return
    data = load_data()
    oid = update.message.text.strip()
    if oid in data:
        info = data[oid]
        await update.message.reply_text(
            f"Order#: {oid}\n"
            f"Status: {info['status']}\n"
            f"Updated: {info['timestamp']} ⏰\n"
            f"By: {info['agent']}"
        )
    else:
        await update.message.reply_text("❌ This order hasn't been updated yet.")

async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != GROUP_ID or not update.message.text:
        return

    text = update.message.text.strip()
    agent_name = update.message.from_user.full_name
    user_id = update.message.from_user.id

    # Manual done per order
    match_done = re.match(r"^([0-9 ,]+)\s+done$", text, re.IGNORECASE)
    if match_done:
        orders = [o.strip() for o in match_done.group(1).split(",") if o.strip().isdigit()]
        if not orders: return
        data = load_data()
        updated = []

        for oid in orders:
            current_order = data.get(oid, {})
            if current_order.get("status") == STATUS_MAP["done"]:
                await update.message.reply_text(
                    f"❌ Order {oid} has already been delivered by {current_order.get('agent','Unknown')}."
                )
                continue

            current_order["status"] = STATUS_MAP["done"]
            current_order["timestamp"] = now_gmt5().strftime("%H:%M")
            current_order["agent"] = agent_name
            current_order.setdefault("history", []).append({
                "status": STATUS_MAP["done"],
                "agent": agent_name,
                "timestamp": current_order["timestamp"]
            })
            data[oid] = current_order
            updated.append(oid)

        save_data(data)

        if updated:
            await update.message.reply_text(
                f"✅ Orders {', '.join(updated)} marked as done manually by {agent_name}"
            )
            await send_agent_log(context, updated, agent_name, STATUS_MAP["done"], action="Done", user_id=user_id)
        return

    # Standard updates
    match = ORDER_PATTERN.match(text)
    if not match: return
    orders_raw = match.group("orders")
    status_key = match.group("status").lower()
    if status_key not in STATUS_MAP: return
    status_full = STATUS_MAP[status_key]
    orders = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not orders: return

    data = load_data()
    updated = []

    for oid in orders:
        current_order = data.get(oid, {})

        # Already done
        if current_order.get("status") == STATUS_MAP["done"]:
            await update.message.reply_text(
                f"❌ Order {oid} has already been delivered by {current_order.get('agent','Unknown')}."
            )
            continue

        current_order["status"] = status_full
        current_order["timestamp"] = now_gmt5().strftime("%H:%M")
        current_order["agent"] = agent_name
        history_list = current_order.get("history", [])
        history_list.append({
            "status": status_full,
            "agent": agent_name,
            "timestamp": current_order["timestamp"]
        })
        current_order["history"] = history_list
        data[oid] = current_order
        updated.append(oid)

    save_data(data)

    if status_key == "no":
        await notify_admins(context, updated, agent_name)

    if updated:
        msg = await update.message.reply_text(f"✅ Updated {len(updated)} order(s) by {agent_name}")
        await asyncio.sleep(5)
        try:
            await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
        except:
            pass

        await send_agent_log(context, updated, agent_name, status_full, action="Update", user_id=user_id)

# ----------------------------
# COMMAND HANDLERS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send an order number to get its status.")

# ----------------------------
# MYORDERS with history (📝)
# ----------------------------
async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.full_name
    data = load_data()
    orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user]

    if not orders:
        return await update.message.reply_text("You haven't updated any orders yet.")

    msg_lines = [f"📝 *Orders updated by {user}:*"]

    for oid, info in orders:
        history = info.get("history", [])
        if not history:
            history_text = "_No history available._"
        else:
            history_sorted = sorted(history, key=lambda x: x["timestamp"], reverse=True)
            history_lines = [f"  - *{h['status']}* at `{h['timestamp']}`" for h in history_sorted]
            history_text = "\n".join(history_lines)

        msg_lines.append(f"\n*Order `{oid}`* (Current: *{info['status']}* at `{info['timestamp']}`)\n{history_text}")

    await update.message.reply_text("\n".join(msg_lines), parse_mode="Markdown")

# ----------------------------
# MYSTATS
# ----------------------------
async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.full_name
    data = load_data()

    total = done = no_answer = in_progress = 0

    for oid, info in data.items():
        if info.get("agent") != user:
            continue
        total += 1
        status = info.get("status", "").lower()
        if status == STATUS_MAP["done"].lower():
            done += 1
        elif status == STATUS_MAP["no"].lower():
            no_answer += 1
        else:
            in_progress += 1

    msg = (
        f"📊 Stats for {user}\n"
        f"Total updated: {total}\n"
        f"✅ Completed: {done}\n"
        f"🚚 In progress: {in_progress}\n"
        f"❌ No answer: {no_answer}"
    )
    await update.message.reply_text(msg)

# ----------------------------
# CHECK ORDER HISTORY
# ----------------------------
async def check_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await update.message.reply_text("Usage: /check 12345")
    order_id = args[1]
    data = load_data()
    if order_id not in data:
        return await update.message.reply_text("❌ Order not found.")
    info = data[order_id]
    msg_lines = [f"📝 *Order `{order_id}` Details:*", f"Current Status: *{info['status']}*"]
    history = info.get("history", [])
    if not history:
        msg_lines.append("_No history available._")
    else:
        for h in history:
            msg_lines.append(f"- *{h['status']}* by {h['agent']} at `{h['timestamp']}`")
    await update.message.reply_text("\n".join(msg_lines), parse_mode="Markdown")

# ----------------------------
# RESET ALL DATA
# ----------------------------
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")
    save_data({})
    await update.message.reply_text("✅ All order history cleared.")

# ----------------------------
# UNDONE ORDER
# ----------------------------
async def undone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")
    args = update.message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await update.message.reply_text("Usage: /undone 12345")
    order_id = args[1]
    data = load_data()
    if order_id not in data:
        return await update.message.reply_text("Order not found.")
    history = data[order_id].get("history", [])
    last_non_done = None
    for entry in reversed(history):
        if entry["status"] != STATUS_MAP["done"]:
            last_non_done = entry
            break
    if last_non_done:
        data[order_id]["status"] = last_non_done["status"]
        data[order_id]["timestamp"] = last_non_done["timestamp"]
        data[order_id]["agent"] = last_non_done["agent"]
    else:
        data[order_id]["status"] = "Pending"
        data[order_id]["timestamp"] = now_gmt5().strftime("%H:%M")
        data[order_id]["agent"] = "Unknown"
    save_data(data)
    await update.message.reply_text(f"🔄 Order {order_id} status reverted.")
    await send_agent_log(context, [order_id], update.message.from_user.full_name, data[order_id]["status"], action="Undone", user_id=update.message.from_user.id)

# ----------------------------
# DONE COMMAND
# ----------------------------
async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = update.message.from_user.full_name
    user_id = update.message.from_user.id
    data = load_data()
    updated = []

    for oid, info in data.items():
        if info.get("status") == STATUS_MAP["done"] or info.get("status") == STATUS_MAP["no"]:
            continue
        if info.get("agent") != agent:
            continue
        info["status"] = STATUS_MAP["done"]
        info["timestamp"] = now_gmt5().strftime("%H:%M")
        info.setdefault("history", []).append({
            "status": STATUS_MAP["done"],
            "agent": agent,
            "timestamp": info["timestamp"]
        })
        updated.append(oid)

    save_data(data)

    if not updated:
        return await update.message.reply_text(
            "No eligible orders to mark as done. Only your own orders in progress can be done."
        )

    msg = await update.message.reply_text(
        f"✅ Marked {len(updated)} order(s) as done by {agent}"
    )
    await asyncio.sleep(5)
    try:
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
    except:
        pass

    await send_agent_log(context, updated, agent, STATUS_MAP["done"], action="Done", user_id=user_id)

# ----------------------------
# COMPLETED ORDERS
# ----------------------------
async def completed_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    completed = [(oid, info) for oid, info in data.items() if info.get("status") == STATUS_MAP["done"]]
    if not completed:
        return await update.message.reply_text("No completed orders yet.")
    msg_lines = ["✅ *Completed Orders:*"]
    for oid, info in completed:
        last_entry = info.get("history", [])[-1] if info.get("history") else info
        msg_lines.append(f"- Order `{oid}` by {last_entry.get('agent','Unknown')} at `{last_entry.get('timestamp','Unknown')}`")
    await update.message.reply_text("\n".join(msg_lines), parse_mode="Markdown")

# ----------------------------
# ONGOING ORDERS
# ----------------------------
async def ongoing_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    ongoing = [(oid, info) for oid, info in data.items() if info.get("status") != STATUS_MAP["done"]]
    if not ongoing:
        return await update.message.reply_text("No ongoing orders.")
    msg_lines = ["🚚 *Ongoing Orders:*"]
    for oid, info in ongoing:
        last_entry = info.get("history", [])[-1] if info.get("history") else info
        msg_lines.append(f"- Order `{oid}`: {last_entry.get('status','Unknown')} by {last_entry.get('agent','Unknown')} at `{last_entry.get('timestamp','Unknown')}`")
    await update.message.reply_text("\n".join(msg_lines), parse_mode="Markdown")

# ----------------------------
# STATS
# ----------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Only admins can view stats.")
    data = load_data()
    if not data:
        return await update.message.reply_text("No orders recorded yet.")

    total = done_count = in_progress = no_answer = 0
    agent_stats = {}
    for oid, info in data.items():
        status = info.get("status", "").lower()
        agent = info.get("agent", "Unknown")
        agent_stats.setdefault(agent, {"total": 0, "done": 0})
        agent_stats[agent]["total"] += 1
        total += 1
        if status == STATUS_MAP["done"].lower():
            done_count += 1
            agent_stats[agent]["done"] += 1
        elif status == STATUS_MAP["no"].lower():
            no_answer += 1
        else:
            in_progress += 1

    msg_lines = [
        "📊 *Today's Order Stats*",
        f"Total orders updated: {total}",
        f"✅ Completed: {done_count}",
        f"🚚 In progress: {in_progress}",
        f"❌ No answer: {no_answer}\n",
        "🧑‍🤝‍🧑 *Per-Agent Stats*"
    ]
    for agent, stats_info in agent_stats.items():
        msg_lines.append(f"- {agent}: {stats_info['total']} updated, ✅ {stats_info['done']} done")

    await update.message.reply_text("\n".join(msg_lines), parse_mode="Markdown")

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("undone", undone))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("comp", completed_orders))
    app.add_handler(CommandHandler("status", ongoing_orders))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("check", check_order))
    app.add_handler(CommandHandler("urgent", urgent_command))
    
    # Messages
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, urgent_private_handler))

    print("Bot running with PTB v21+ (Python 3.13 compatible, Markdown logs)")
    app.run_polling()

if __name__ == "__main__":
    main()

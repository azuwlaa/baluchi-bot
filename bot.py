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
AGENTS_FILE = "agents.json"

# ----------------------------
# STATUS MAP (w/ aliases)
# ----------------------------
STATUS_MAP = {
    "out": "Out for delivery",

    # OTW aliases
    "otw": "On the way to Hulhumale'",
    "on": "On the way to Hulhumale'",
    "ontheway": "On the way to Hulhumale'",
    "ontheway": "On the way to Hulhumale'",
    "on-the-way": "On the way to Hulhumale'",
    "ontheway": "On the way to Hulhumale'",

    # GOT aliases
    "got": "Received by Hulhumale' agents",
    "rwav": "Received by Hulhumale' agents",
    "resv": "Received by Hulhumale' agents",
    "reav": "Received by Hulhumale' agents",
    "rcvd": "Received by Hulhumale' agents",
    "rwsv": "Received by Hulhumale' agents",
    "rwv": "Received by Hulhumale' agents",

    # NO-ANSWER aliases
    "no": "No answer from the number",
    "noanswer": "No answer from the number",
    "noanswers": "No answer from the number",
    "noanswering": "No answer from the number",
    "noans": "No answer from the number",

    "air": "On the way to airport",
    "done": "Order delivery completed",
}

# Accept multi-word status + slash/comma
ORDER_PATTERN = re.compile(
    r"^(?P<orders>[0-9 ,/]+)\s+(?P<status>[a-zA-Z _-]+)$",
    re.IGNORECASE
)

# ----------------------------
# HELPERS
# ----------------------------
def normalize_status_key(text: str):
    return text.lower().replace(" ", "").replace("-", "").replace("_", "")

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data({})
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_agents():
    if not os.path.exists(AGENTS_FILE):
        save_agents({})
    with open(AGENTS_FILE, "r") as f:
        return json.load(f)

def save_agents(data):
    with open(AGENTS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def remember_agent(user_id, name):
    agents = load_agents()
    agents[str(user_id)] = name
    save_agents(agents)

def now_gmt5():
    return datetime.now(timezone.utc) + timedelta(hours=5)


# ----------------------------
# LOGGING HELPERS
# ----------------------------
async def send_agent_log(context, orders, agent_name, status_full, action="Update", user_id=None):
    orders_text = ", ".join(orders)
    agent_html = f'<a href="tg://user?id={user_id}">{agent_name}</a>'
    msg = (
        f"<b>#{action}</b>\n"
        f"• Orders#: {orders_text}\n"
        f"• Agent: {agent_html}\n"
        f"• Time: {now_gmt5().strftime('%H:%M')} ⏰\n"
        f"• Status: {status_full}"
    )
    await context.bot.send_message(AGENT_LOG_CHANNEL, msg, parse_mode="HTML")


async def notify_admins(context, orders, agent_name):
    msg = f"⚠️ Orders {', '.join(orders)} marked as NO ANSWER by {agent_name}"
    for admin in ADMINS:
        try:
            await context.bot.send_message(admin, msg)
        except:
            pass


# ----------------------------
# URGENT (PRIVATE)
# ----------------------------
async def urgent_private_handler(update: Update, context):
    if not update.message or not update.message.text:
        return

    if update.message.chat.type != "private":
        return

    text = update.message.text.lower()

    if "urgent" not in text:
        return

    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")

    numbers = [n for n in re.findall(r"\b\d+\b", text) if len(n) <= 6]

    if not numbers:
        return await update.message.reply_text("❌ No valid numbers found.")

    urgent_text = f"🚨 URGENT ORDERS: {', '.join(numbers)}"
    msg = await context.bot.send_message(GROUP_ID, urgent_text)
    try:
        await context.bot.pin_chat_message(GROUP_ID, msg.message_id)
    except:
        pass

    await update.message.reply_text("✅ Urgent pinned.")


# ----------------------------
# /urgent command
# ----------------------------
async def urgent_command(update: Update, context):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")

    args = update.message.text.split()[1:]
    orders = [o for o in args if o.isdigit() and len(o) <= 6]

    if not orders:
        return await update.message.reply_text("❌ No valid order numbers.")

    urgent_text = f"🚨 URGENT ORDERS: {', '.join(orders)}"
    msg = await context.bot.send_message(GROUP_ID, urgent_text)

    try:
        await context.bot.pin_chat_message(GROUP_ID, msg.message_id)
    except:
        pass

    await update.message.reply_text("✅ Urgent pinned.")


# ----------------------------
# LOOKUP ORDER (PRIVATE)
# ----------------------------
async def lookup_order(update: Update, context):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not text.isdigit():
        return

    if len(text) == 7:  # ignore 7-digit numbers
        return

    data = load_data()

    if text in data:
        info = data[text]
        await update.message.reply_text(
            f"Order#: {text}\n"
            f"Status: {info['status']}\n"
            f"Updated: {info['timestamp']}\n"
            f"By: {info['agent']}"
        )
    else:
        await update.message.reply_text("❌ No updates for this order yet.")


# ----------------------------
# GROUP LISTENER
# ----------------------------
async def group_listener(update: Update, context):
    if not update.message or not update.message.text:
        return

    if update.message.chat.id != GROUP_ID:
        return

    text = update.message.text.strip()
    agent_name = update.message.from_user.full_name
    user_id = update.message.from_user.id

    remember_agent(user_id, agent_name)

    # -------------------------------------------------------
    # (0) REPLY-BASED STATUS UPDATES
    # -------------------------------------------------------
    if update.message.reply_to_message and update.message.reply_to_message.text:
        original_text = update.message.reply_to_message.text.strip()
        raw_list = re.split(r"[,/ ]+", original_text)
        replied_orders = [o for o in raw_list if o.isdigit() and 1 <= len(o) <= 6]

        if replied_orders:
            status_key = normalize_status_key(text)
            if status_key in STATUS_MAP:
                status_full = STATUS_MAP[status_key]
                data = load_data()
                updated = []

                for oid in replied_orders:
                    current = data.get(oid, {})

                    if current.get("status") == STATUS_MAP["done"]:
                        continue

                    current["status"] = status_full
                    current["timestamp"] = now_gmt5().strftime("%H:%M")
                    current["agent"] = agent_name
                    current.setdefault("history", []).append({
                        "status": status_full,
                        "agent": agent_name,
                        "timestamp": current["timestamp"]
                    })
                    data[oid] = current
                    updated.append(oid)

                save_data(data)

                if updated:
                    await update.message.reply_text(
                        f"🔁 Updated orders {', '.join(updated)} via reply."
                    )
                    await send_agent_log(context, updated, agent_name, status_full, action="Reply-Update", user_id=user_id)

                return

    # -------------------------------------------------------
    # (1) “done” alone = /done
    # -------------------------------------------------------
    if text.lower() == "done":
        return await done_command(update, context)

    # -------------------------------------------------------
    # (2) AUTO-OUT: only numbers
    # -------------------------------------------------------
    raw_list = re.split(r"[,/ ]+", text)
    only_numbers = [o for o in raw_list if o.isdigit() and 1 <= len(o) <= 6]

    if only_numbers and len(only_numbers) == len(raw_list):
        status_full = STATUS_MAP["out"]
        data = load_data()
        updated = []

        for oid in only_numbers:
            current = data.get(oid, {})
            if current.get("status") == STATUS_MAP["done"]:
                continue

            current["status"] = status_full
            current["timestamp"] = now_gmt5().strftime("%H:%M")
            current["agent"] = agent_name
            current.setdefault("history", []).append({
                "status": status_full,
                "agent": agent_name,
                "timestamp": current["timestamp"]
            })
            data[oid] = current
            updated.append(oid)

        save_data(data)

        if updated:
            await update.message.reply_text(f"🚚 Marked {', '.join(updated)} as Out.")
            await send_agent_log(context, updated, agent_name, status_full, action="Update", user_id=user_id)

        return

    # -------------------------------------------------------
    # (3) MANUAL DONE: “123/33 done”
    # -------------------------------------------------------
    match_done = re.match(r"^([0-9 ,/]+)\s+done$", text, re.IGNORECASE)
    if match_done:
        raw_list = re.split(r"[,/ ]+", match_done.group(1))
        orders = [o for o in raw_list if o.isdigit() and 1 <= len(o) <= 6]

        data = load_data()
        updated = []

        for oid in orders:
            current = data.get(oid, {})
            if current.get("status") == STATUS_MAP["done"]:
                continue

            current["status"] = STATUS_MAP["done"]
            current["timestamp"] = now_gmt5().strftime("%H:%M")
            current["agent"] = agent_name
            current.setdefault("history", []).append({
                "status": STATUS_MAP["done"],
                "agent": agent_name,
                "timestamp": current["timestamp"]
            })
            data[oid] = current
            updated.append(oid)

        save_data(data)

        if updated:
            await update.message.reply_text(f"✅ Marked {', '.join(updated)} done.")
            await send_agent_log(context, updated, agent_name, STATUS_MAP["done"], action="Done", user_id=user_id)

        return

    # -------------------------------------------------------
    # (4) STANDARD UPDATES: “123 otw”, “1080 no answer”, etc.
    # -------------------------------------------------------
    match = ORDER_PATTERN.match(text)
    if not match:
        return

    orders_raw = match.group("orders")
    raw_list = re.split(r"[,/ ]+", orders_raw)
    orders = [o for o in raw_list if o.isdigit() and 1 <= len(o) <= 6]

    if not orders:
        return

    status_key = normalize_status_key(match.group("status"))

    if status_key not in STATUS_MAP:
        return

    status_full = STATUS_MAP[status_key]
    data = load_data()
    updated = []

    for oid in orders:
        current = data.get(oid, {})
        if current.get("status") == STATUS_MAP["done"]:
            continue

        current["status"] = status_full
        current["timestamp"] = now_gmt5().strftime("%H:%M")
        current["agent"] = agent_name
        current.setdefault("history", []).append({
            "status": status_full,
            "agent": agent_name,
            "timestamp": current["timestamp"]
        })
        data[oid] = current
        updated.append(oid)

    save_data(data)

    if status_key in ["no", "noanswer", "noanswers", "noanswering", "noans"]:
        await notify_admins(context, updated, agent_name)

    if updated:
        await update.message.reply_text(f"✅ Updated {len(updated)} order(s).")
        await send_agent_log(context, updated, agent_name, status_full, action="Update", user_id=user_id)


# ----------------------------
# /agents — Show all agents
# ----------------------------
async def agents_list(update: Update, context):
    agents = load_agents()

    if not agents:
        return await update.message.reply_text("No agents recorded yet.")

    lines = ["🧑‍🤝‍🧑 *Registered Agents:*"]

    for uid, name in agents.items():
        hyperlink = f"[{name}](tg://user?id={uid})"
        lines.append(f"- **{hyperlink}** — `ID:{uid}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ----------------------------
# /myorders
# ----------------------------
async def myorders(update, context):
    user = update.message.from_user.full_name
    data = load_data()

    orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user]

    if not orders:
        return await update.message.reply_text("You haven't updated any orders.")

    msg = [f"📝 *Orders updated by {user}:*"]

    for oid, info in orders:
        history = info.get("history", [])
        if not history:
            hist = "_No history._"
        else:
            hist = "\n".join(
                [f"  - *{h['status']}* at `{h['timestamp']}`" for h in reversed(history)]
            )

        msg.append(f"\n*Order `{oid}`* → {info['status']} at `{info['timestamp']}`\n{hist}")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# /mystats
# ----------------------------
async def mystats(update, context):
    user = update.message.from_user.full_name
    data = load_data()

    total = done = no_ans = in_prog = 0

    for oid, info in data.items():
        if info.get("agent") != user:
            continue

        total += 1
        status = info["status"].lower()

        if status == STATUS_MAP["done"].lower():
            done += 1
        elif status == STATUS_MAP["no"].lower():
            no_ans += 1
        else:
            in_prog += 1

    await update.message.reply_text(
        f"📊 Stats for {user}\n"
        f"Total updated: {total}\n"
        f"✅ Done: {done}\n"
        f"🚚 In progress: {in_prog}\n"
        f"❌ No answer: {no_ans}"
    )


# ----------------------------
# /check
# ----------------------------
async def check_order(update, context):
    args = update.message.text.split()

    if len(args) != 2 or not args[1].isdigit() or len(args[1]) == 7:
        return await update.message.reply_text("Usage: /check 12345")

    order_id = args[1]
    data = load_data()

    if order_id not in data:
        return await update.message.reply_text("❌ Order not found.")

    info = data[order_id]
    msg = [
        f"📝 *Order `{order_id}`*",
        f"Status: *{info['status']}*"
    ]

    for h in info.get("history", []):
        msg.append(f"- *{h['status']}* by {h['agent']} at `{h['timestamp']}`")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# /reset
# ----------------------------
async def reset(update, context):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")

    save_data({})
    save_agents({})

    await update.message.reply_text("🗑 All data cleared.")


# ----------------------------
# /undone
# ----------------------------
async def undone(update, context):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")

    args = update.message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await update.message.reply_text("Usage: /undone 12345")

    oid = args[1]
    data = load_data()

    if oid not in data:
        return await update.message.reply_text("Order not found.")

    history = data[oid].get("history", [])
    last = None

    for h in reversed(history):
        if h["status"] != STATUS_MAP["done"]:
            last = h
            break

    if last:
        data[oid]["status"] = last["status"]
        data[oid]["timestamp"] = last["timestamp"]
        data[oid]["agent"] = last["agent"]
    else:
        data[oid]["status"] = "Pending"
        data[oid]["timestamp"] = now_gmt5().strftime("%H:%M")
        data[oid]["agent"] = "Unknown"

    save_data(data)
    await update.message.reply_text(f"🔄 Order {oid} reverted.")


# ----------------------------
# /done
# ----------------------------
async def done_command(update, context):
    agent = update.message.from_user.full_name
    user_id = update.message.from_user.id
    remember_agent(user_id, agent)

    data = load_data()
    updated = []

    for oid, info in data.items():
        if info.get("agent") != agent:
            continue
        if info["status"] == STATUS_MAP["done"]:
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
        return await update.message.reply_text("No orders eligible for done.")

    await update.message.reply_text(f"✅ Marked {len(updated)} orders done.")
    await send_agent_log(context, updated, agent, STATUS_MAP["done"], action="Done", user_id=user_id)


# ----------------------------
# /comp
# ----------------------------
async def completed_orders(update, context):
    data = load_data()
    completed = [(oid, info) for oid, info in data.items() if info["status"] == STATUS_MAP["done"]]

    if not completed:
        return await update.message.reply_text("No completed orders.")

    msg = ["✅ *Completed Orders:*"]
    for oid, info in completed:
        last = info.get("history", [])[-1]
        msg.append(f"- `{oid}` by {last['agent']} at `{last['timestamp']}`")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# /status
# ----------------------------
async def ongoing_orders(update, context):
    data = load_data()
    ongoing = [(oid, info) for oid, info in data.items() if info["status"] != STATUS_MAP["done"]]

    if not ongoing:
        return await update.message.reply_text("No ongoing orders.")

    msg = ["🚚 *Ongoing Orders:*"]
    for oid, info in ongoing:
        last = info.get("history", [])[-1]
        msg.append(f"- `{oid}` → {last['status']} by {last['agent']} at `{last['timestamp']}`")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# /stats
# ----------------------------
async def stats(update, context):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")

    data = load_data()

    if not data:
        return await update.message.reply_text("No orders yet.")

    total = done = no_ans = in_prog = 0
    agent_stats = {}

    for oid, info in data.items():
        status = info["status"].lower()
        agent = info.get("agent", "Unknown")

        agent_stats.setdefault(agent, {"total": 0, "done": 0})
        agent_stats[agent]["total"] += 1
        total += 1

        if status == STATUS_MAP["done"].lower():
            agent_stats[agent]["done"] += 1
            done += 1
        elif status == STATUS_MAP["no"].lower():
            no_ans += 1
        else:
            in_prog += 1

    msg = [
        "📊 *Today's Stats*",
        f"Total updated: {total}",
        f"✅ Done: {done}",
        f"🚚 In progress: {in_prog}",
        f"❌ No answer: {no_ans}",
        "\n🧍 *Agent Breakdown:*"
    ]

    for agent, s in agent_stats.items():
        msg.append(f"- {agent}: {s['total']} updated, {s['done']} done")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


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
    app.add_handler(CommandHandler("agents", agents_list))

    # Message listeners
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lookup_order))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, urgent_private_handler))

    print("Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

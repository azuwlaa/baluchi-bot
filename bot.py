# baluchi_bot.py
import json
import os
import re
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

# ----------------------------
# CONFIG - <<< EDIT THESE >>>
# ----------------------------

GROUP_ID = -1003463796946      # <-- your main group id (integer)
LOG_CHANNEL_ID = -1003484693080  # <-- channel id or chat id for logs (admins only)
ADMINS = [624102836, 252008924]   # <-- list of admin telegram user ids
DATA_DIR = "data"
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")
AGENTS_FILE = os.path.join(DATA_DIR, "agents.json")
URGENCIES_FILE = os.path.join(DATA_DIR, "urgents.json")

# ----------------------------
# STATUS MAP (short_key -> full description)
# ----------------------------
STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}
STATUS_KEYS = set(STATUS_MAP.keys())

# ----------------------------
# Utilities & persistence
# ----------------------------
os.makedirs(DATA_DIR, exist_ok=True)

def _read_json(path: str, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default
    with open(path, "r") as f:
        try:
            return json.load(f)
        except Exception:
            return default

def _write_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_orders() -> Dict[str, Any]:
    return _read_json(ORDERS_FILE, {})

def save_orders(data: Dict[str, Any]):
    _write_json(ORDERS_FILE, data)

def load_agents() -> List[int]:
    return _read_json(AGENTS_FILE, [])

def save_agents(lst: List[int]):
    _write_json(AGENTS_FILE, lst)

def load_urgents() -> Dict[str, bool]:
    return _read_json(URGENCIES_FILE, {})

def save_urgents(d: Dict[str, bool]):
    _write_json(URGENCIES_FILE, d)

# timezone-aware current time in GMT+5
TZ = timezone(timedelta(hours=5))
def now_iso():
    return datetime.now(tz=TZ).isoformat(timespec="seconds")

def time_hhmm(ts_iso: str):
    try:
        dt = datetime.fromisoformat(ts_iso)
        return dt.astimezone(TZ).strftime("%H:%M")
    except Exception:
        return ts_iso

# Logging helper to send to LOG_CHANNEL_ID
async def send_log(application, order_id: str, agent_name: str, status_full: str, ts_iso: str):
    if not LOG_CHANNEL_ID:
        return
    text = (
        f"#Update:\n"
        f"• Order#: {order_id}\n"
        f"• Agent: {agent_name}\n"
        f"• Time: {time_hhmm(ts_iso)}\n"
        f"• Status: {status_full}"
    )
    try:
        await application.bot.send_message(chat_id=LOG_CHANNEL_ID, text=text)
    except Exception:
        # don't crash on log failure
        pass

# Notify admins (private)
async def notify_admins(application, message: str):
    for admin_id in ADMINS:
        try:
            await application.bot.send_message(chat_id=admin_id, text=message)
        except Exception:
            pass

# ----------------------------
# Message parsing rules
# ----------------------------
# Patterns:
#   "<orders> <status_key>"  e.g. "12345 out" or "123,124 otw"
ORDERS_STATUS_RE = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[A-Za-z]+)$")
# "done" alone marks all agent's assigned orders done (skip 'no')
DONE_ORDERS_RE = re.compile(r"^(?P<orders>[0-9 ,]+)\s+done$", re.IGNORECASE)
URGENT_RE = re.compile(r"^(?P<order>[0-9]+)\s+urgent$", re.IGNORECASE)
STATUS_CMD_RE = re.compile(r"^/status\s+(?P<id>[0-9]+)$", re.IGNORECASE)

# ----------------------------
# Core behaviors
# ----------------------------
async def handle_update_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    This receives text messages from the group and private (via handlers).
    We process only when message exists and is text.
    """
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_name = user.full_name if user else "Unknown"

    # If admin marking urgent in group: "12345 urgent"
    if chat_id == GROUP_ID and user and user.id in ADMINS:
        m = URGENT_RE.match(text)
        if m:
            order = m.group("order")
            orders = load_orders()
            urgents = load_urgents()
            urgents[order] = True
            save_urgents(urgents)
            assigned = orders.get(order, {}).get("assigned_agent_id")
            if assigned:
                # PM assigned agent
                try:
                    await context.bot.send_message(chat_id=assigned, text=f"⚠️ URGENT: Order {order} marked urgent by admin.")
                except Exception:
                    pass
                await update.message.reply_text(f"🔔 Urgent sent to assigned agent.")
            else:
                await update.message.reply_text("🔔 Marked as urgent — no agent assigned yet. Agent will be notified when they take it.")
            return

    # If it's a simple "/status <order>" command in message text (allow in group or private)
    sc = STATUS_CMD_RE.match(text)
    if sc:
        oid = sc.group("id")
        orders = load_orders()
        if oid in orders:
            info = orders[oid]
            last = info.get("history", [])[-1] if info.get("history") else {}
            msg = (
                f"📦 Order {oid}\n"
                f"Status: {last.get('status','-')}\n"
                f"Agent: {info.get('assigned_agent_name','-')}\n"
                f"Time: {last.get('time_hhmm','-')}"
            )
            await update.message.reply_text(msg)
        else:
            await update.message.reply_text("No record found for that order.")
        return

    # Only accept updates coming from the GROUP for status changes (per requirement).
    # But allow private messages for /status handled above; ignore other private texts.
    if chat_id != GROUP_ID:
        # allow agent commands like "/add", "/remove", "/myorders" handled by command handlers; ignore other private texts
        return

    # Now parse group text (agent updates or lookups)
    # If message contains only digits -> lookup
    if text.isdigit():
        orders = load_orders()
        oid = text
        if oid in orders:
            info = orders[oid]
            last = info.get("history", [])[-1] if info.get("history") else {}
            await update.message.reply_text(
                f"📦 Order {oid}: {last.get('status','-')} by {info.get('assigned_agent_name','-')} at {last.get('time_hhmm','-')}"
            )
        else:
            await update.message.reply_text("No record found for this order.")
        return

    # match "<orders> <status>"
    m = ORDERS_STATUS_RE.match(text)
    if not m:
        return

    orders_raw = m.group("orders")
    status_key = m.group("status").lower()
    status_key = status_key.strip()
    if status_key not in STATUS_KEYS:
        # ignore anything not in map
        return
    status_full = STATUS_MAP[status_key]

    # split orders
    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    # load persisted structures
    orders = load_orders()
    urgents = load_urgents()
    agents_list = load_agents()

    # If status_key == 'done' and message was exactly "done" (no numbers) — we handle in separate logic.
    # Here we handle either "12345 done" or "12345 otw" or "12345 out", etc.
    ts_iso = now_iso()

    # For 'out' registration and assignment: when an agent writes "12345 out", they take the order.
    # For any status we add history entry, update assigned agent if status != 'no' ?
    # We'll set assigned_agent to the agent who updated the order when they say 'out' or any status except 'no' maybe.
    for oid in order_list:
        entry = {
            "status": status_full,
            "time_iso": ts_iso,
            "time_hhmm": time_hhmm(ts_iso),
            "agent_id": user.id,
            "agent_name": user_name,
        }
        order_obj = orders.get(oid, {"history": [], "assigned_agent_id": None, "assigned_agent_name": None, "status": None})
        # append history
        order_obj.setdefault("history", []).append(entry)
        order_obj["status"] = status_full

        # if agent sends 'out' or any status other than 'no', assign to them (taking order)
        if status_key != "no":
            order_obj["assigned_agent_id"] = user.id
            order_obj["assigned_agent_name"] = user_name

        orders[oid] = order_obj

        # If this order was marked urgent earlier, notify group that urgent assignment happened.
        if urgents.get(oid):
            # announce in group and PM the agent
            try:
                await context.bot.send_message(chat_id=GROUP_ID,
                                               text=f"‼️ Order {oid} was URGENT and now taken by {user_name}.")
                await context.bot.send_message(chat_id=user.id, text=f"‼️ You took URGENT order {oid}.")
            except Exception:
                pass
            urgents.pop(oid)
    # persist
    save_orders(orders)
    save_urgents(urgents)

    # Log updates to LOG_CHANNEL and notify admins on 'no'
    for oid in order_list:
        od = orders[oid]
        last = od["history"][-1]
        # Send log entry
        await send_log(context.application, oid, last["agent_name"], last["status"], last["time_iso"])
        # If status is 'no' then notify admins
        if status_key == "no":
            await notify_admins(context.application, f"⚠️ Order {oid} marked NO ANSWER by {user_name} at {last['time_hhmm']}")

    # Confirmation message (auto-delete after 5 seconds using job queue)
    confirm = await update.message.reply_text(f"✅ Updated {len(order_list)} order(s): {', '.join(order_list)} by {user_name}")
    # schedule delete
    context.application.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id=confirm.chat_id, message_id=confirm.message_id), 5)

# ----------------------------
# Bulk 'done' handling when agent sends 'done' alone:
# - Marks all orders assigned to that agent as done except those with current status "No answer..."
# ----------------------------
async def handle_done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """This handler is for messages 'done' or '123,124 done' in group."""
    if not update.message or not update.message.text:
        return
    if update.effective_chat.id != GROUP_ID:
        return

    text = update.message.text.strip().lower()
    user = update.effective_user
    user_name = user.full_name if user else "Unknown"

    # if explicit numbers provided: e.g. "12345,12346 done"
    m = DONE_ORDERS_RE.match(text)
    if m:
        orders_str = m.group("orders")
        order_list = [o.strip() for o in orders_str.split(",") if o.strip().isdigit()]
        if not order_list:
            return
        orders = load_orders()
        ts_iso = now_iso()
        for oid in order_list:
            od = orders.get(oid)
            if not od:
                # create new and mark done
                od = {"history": [], "assigned_agent_id": user.id, "assigned_agent_name": user_name}
            # add done entry even if previously 'no'
            entry = {
                "status": STATUS_MAP["done"],
                "time_iso": ts_iso,
                "time_hhmm": time_hhmm(ts_iso),
                "agent_id": user.id,
                "agent_name": user_name,
            }
            od.setdefault("history", []).append(entry)
            od["status"] = STATUS_MAP["done"]
            od["assigned_agent_id"] = user.id
            od["assigned_agent_name"] = user_name
            orders[oid] = od
            await send_log(context.application, oid, user_name, entry["status"], entry["time_iso"])
        save_orders(orders)
        confirm = await update.message.reply_text(f"✅ Marked {len(order_list)} specified order(s) as done.")
        context.application.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id=confirm.chat_id, message_id=confirm.message_id), 5)
        return

    # if message exactly 'done' -> bulk complete agent's orders (skip 'no')
    if text == "done":
        orders = load_orders()
        ts_iso = now_iso()
        modified = 0
        for oid, od in orders.items():
            # check last status and assigned agent
            last = od.get("history", [])[-1] if od.get("history") else None
            if not last:
                continue
            # only if assigned to this agent and not 'No answer'
            if od.get("assigned_agent_id") == user.id:
                last_status = last.get("status","").lower()
                if "no answer" in last_status:
                    # skip: agent must explicitly done that order
                    continue
                # add done entry
                entry = {
                    "status": STATUS_MAP["done"],
                    "time_iso": ts_iso,
                    "time_hhmm": time_hhmm(ts_iso),
                    "agent_id": user.id,
                    "agent_name": user_name,
                }
                od.setdefault("history", []).append(entry)
                od["status"] = STATUS_MAP["done"]
                orders[oid] = od
                await send_log(context.application, oid, user_name, entry["status"], entry["time_iso"])
                modified += 1
        save_orders(orders)
        confirm = await update.message.reply_text(f"✅ Marked {modified} order(s) as done for {user_name}.")
        context.application.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id=confirm.chat_id, message_id=confirm.message_id), 5)
        return

# ----------------------------
# Commands
# ----------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "Hello — delivery bot. Agents post updates in the group using:\n"
        "`12345 out` / `12345 otw` / `12345 done` / `12345 no`\n"
        "Admins can use /history, /stats, /report, /reset\n"
        "Customers can check `/status <order>`"
    )

# /myorders - show orders updated by the calling user (works in group & private)
async def cmd_myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    user_name = user.full_name
    orders = load_orders()
    lines = []
    for oid, od in orders.items():
        # show last history entries done by this agent
        for h in od.get("history", []):
            if h.get("agent_id") == user.id:
                lines.append(f"📦 {oid}: {h.get('status')} ⏱ {h.get('time_hhmm')}")
    if not lines:
        await update.message.reply_text("You haven't updated any orders yet.")
        return
    header = f"📝 Your Updated Orders, {user_name}:\n"
    await update.message.reply_text(header + "\n".join(lines))

# /history - admin view last N orders
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can use /history.")
        return
    data = load_orders()
    items = list(data.items())
    # last 10 by insertion order (orders.json preserve insertion order)
    last10 = items[-10:]
    lines = []
    for oid, od in last10:
        last = od.get("history", [])[-1] if od.get("history") else {}
        lines.append(f"📦 {oid}: {last.get('status')} by {last.get('agent_name')} at {last.get('time_hhmm')}")
    if not lines:
        await update.message.reply_text("No orders yet.")
        return
    await update.message.reply_text("📜 Last 10 Orders:\n" + "\n".join(lines))

# /stats - admin individual and overall stats for today
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can use /stats.")
        return
    data = load_orders()
    today = datetime.now(tz=TZ).date()
    total = done_count = in_progress = no_answer = 0
    agent_totals = {}
    agent_done = {}
    for oid, od in data.items():
        # check last history entry date
        last = od.get("history", [])[-1] if od.get("history") else None
        if not last:
            continue
        try:
            dt = datetime.fromisoformat(last["time_iso"]).astimezone(TZ)
        except Exception:
            dt = None
        if dt and dt.date() != today:
            continue
        total += 1
        status = last.get("status","").lower()
        agent = last.get("agent_name","Unknown")
        agent_totals[agent] = agent_totals.get(agent, 0) + 1
        if "completed" in status:
            done_count += 1
            agent_done[agent] = agent_done.get(agent, 0) + 1
        elif "no answer" in status:
            no_answer += 1
        else:
            in_progress += 1

    # build message per requested format
    header = (
        f"📊 **Today's Order Stats**\n"
        f"Total orders updated: {total}\n"
        f"✅ Completed: {done_count}\n"
        f"🚚 In progress: {in_progress}\n"
        f"❌ No answer: {no_answer}\n\n"
        f"🧑‍🤝‍🧑 **Per-Agent Stats**\n"
    )
    lines = []
    for agent, total_cnt in agent_totals.items():
        done_cnt = agent_done.get(agent, 0)
        lines.append(f"👤 {agent}: {total_cnt} updated, ✅ {done_cnt} done")
    if not lines:
        lines_text = "No agent updates today."
    else:
        lines_text = "\n".join(lines)
    await update.message.reply_text(header + lines_text, parse_mode=ParseMode.MARKDOWN)

# /report - full summary of delivered orders that day (admin)
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can use /report.")
        return
    data = load_orders()
    today = datetime.now(tz=TZ).date()
    delivered = []
    for oid, od in data.items():
        for h in od.get("history", []):
            try:
                dt = datetime.fromisoformat(h["time_iso"]).astimezone(TZ)
            except Exception:
                dt = None
            if dt and dt.date() == today and "completed" in h["status"].lower():
                delivered.append((oid, h))
    if not delivered:
        await update.message.reply_text("No deliveries recorded today.")
        return
    lines = []
    for oid, h in delivered:
        lines.append(f"📦 {oid} — {h['agent_name']} — {h['time_hhmm']}")
    await update.message.reply_text("📋 Today's Delivered Orders:\n" + "\n".join(lines))

# /status <order> - customer visible check
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    text = update.message.text.strip()
    m = STATUS_CMD_RE.match(text)
    if not m:
        await update.message.reply_text("Usage: /status <order_number>")
        return
    oid = m.group("id")
    orders = load_orders()
    if oid in orders:
        last = orders[oid].get("history", [])[-1]
        await update.message.reply_text(
            f"📦 Order {oid}\nStatus: {last.get('status')}\nAgent: {orders[oid].get('assigned_agent_name','-')}\nTime: {last.get('time_hhmm')}"
        )
    else:
        await update.message.reply_text("No record found for that order.")

# /add (reply to someone's message) -> register agent (admin only)
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Only admins can add agents.")
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await update.message.reply_text("Reply to a user's message with /add to register them as agent.")
        return
    target = update.message.reply_to_message.from_user
    agents = load_agents()
    if target.id in agents:
        await update.message.reply_text(f"{target.full_name} is already registered.")
        return
    agents.append(target.id)
    save_agents(agents)
    await update.message.reply_text(f"Registered agent: {target.full_name} ({target.id})")

# /remove (reply) -> unregister agent
async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Only admins can remove agents.")
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await update.message.reply_text("Reply to a user's message with /remove to unregister them.")
        return
    target = update.message.reply_to_message.from_user
    agents = load_agents()
    if target.id not in agents:
        await update.message.reply_text(f"{target.full_name} is not registered.")
        return
    agents.remove(target.id)
    save_agents(agents)
    await update.message.reply_text(f"Removed agent: {target.full_name}")

# ----------------------------
# Register handlers and run
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # basic message handlers:
    # Group message handler for updates, urgents and lookups
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT & ~filters.UpdateType.EDITED, handle_update_message))
    # Done handler (must be after general handler? We'll add pattern-based handler)
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.Regex(r"(?i)^done$|(?i)^[0-9 ,]+ done$"), handle_done_command))

    # Lookup in anywhere - order number message is handled inside handle_update_message for group, but allow private /status cmd
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myorders", cmd_myorders))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("reset", lambda u,c: reset_handler(u,c)))  # wrap to check admin inside
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))

    # Ensure job_queue exists (it will be created by Application)
    _ = app.job_queue

    print("Bot running...")
    app.run_polling()

# simple wrapper for reset so that it is async and checked
async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can reset.")
        return
    save_orders({})
    await update.message.reply_text("✅ All order data cleared.")

if __name__ == "__main__":
    main()

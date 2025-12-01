import re
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters
)
from PIL import Image
import io
import pandas as pd

# ===== CONFIGURATION =====
BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID = -1001956620304   # Group where reports happen
LOG_CHANNEL_ID = -1003449720539   # Channel where logs go

# ===== DATABASE SETUP =====
def init_db():
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    # Staff table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT
        )
    """)
    # Attendance table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            clock_in TEXT,
            clock_out TEXT,
            status TEXT,
            late_minutes INTEGER
        )
    """)
    # Broken glass table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS broken_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reported_by_id INTEGER,
            reported_by_name TEXT,
            broken_by TEXT,
            photo_file_id TEXT,
            date TEXT,
            time TEXT,
            message_link TEXT
        )
    """)
    conn.commit()
    conn.close()

# ===== HELPER FUNCTIONS =====
def escape_markdown(text: str) -> str:
    return re.sub(r'([_\*\[\]\(\)\~\>\#\+\-\=\|\{\}\.\!])', r'\\\1', text)

def gmt5_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=5)))

def get_shift(clock_time: datetime) -> str:
    """Determine shift based on time"""
    h, m = clock_time.hour, clock_time.minute
    if h < 17:
        return "Morning"
    return "Evening"

def compute_late(clock_time: datetime, shift: str) -> int:
    """Return late minutes"""
    if shift == "Morning":
        ref = clock_time.replace(hour=8, minute=30)
    else:
        ref = clock_time.replace(hour=17, minute=0)
    delta = clock_time - ref
    return max(0, int(delta.total_seconds() // 60))

# ===== STAFF MANAGEMENT =====
async def add_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message.reply_to_message or len(context.args) < 1:
        await message.reply_text("Reply to a user and provide their correct name. Usage: /add <Name>")
        return
    user = message.reply_to_message.from_user
    name = " ".join(context.args)
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO staff (user_id, full_name) VALUES (?, ?)", (user.id, name))
    conn.commit()
    conn.close()
    await message.reply_text(f"✅ Staff added: {name}")

async def rm_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message.reply_to_message:
        await message.reply_text("Reply to a staff to remove them using /rm")
        return
    user = message.reply_to_message.from_user
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE user_id=?", (user.id,))
    conn.commit()
    conn.close()
    await message.reply_text(f"✅ Staff removed: {user.full_name}")

async def list_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, full_name FROM staff")
    rows = cur.fetchall()
    conn.close()
    text = f"*Staff list ({len(rows)} total):*\n"
    for uid, name in rows:
        text += f"• **[{escape_markdown(name)}](tg://user?id={uid})**\n"
    await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ===== CLOCK-IN/CLOCK-OUT =====
async def clock_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    now = gmt5_now()
    shift = get_shift(now)
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    date = now.strftime("%Y-%m-%d")
    cur.execute("SELECT * FROM attendance WHERE user_id=? AND date=?", (user.id, date))
    if cur.fetchone():
        await message.reply_text("❌ You have already clocked in today.")
        return
    late_minutes = compute_late(now, shift)
    # Determine clock out time automatically
    if shift == "Morning":
        clock_out = now.replace(hour=17, minute=0)
    else:
        clock_out = now.replace(hour=0, minute=30) + timedelta(days=1)
    cur.execute("""
        INSERT INTO attendance (user_id, date, clock_in, clock_out, status, late_minutes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user.id, date, now.strftime("%H:%M"), clock_out.strftime("%H:%M"), "Clocked In", late_minutes))
    conn.commit()
    conn.close()
    # Send log to channel
    caption = f"#clock\n• Staff Name: {escape_markdown(user.full_name)}\n• Date: {date}\n• Time: {now.strftime('%H:%M')}\n• Message link: [Go to message](https://t.me/c/{str(GROUP_ID)[4:]}/{message.message_id})"
    await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=caption, parse_mode=ParseMode.MARKDOWN)
    await message.reply_text("✅ Clock-in recorded.", parse_mode=ParseMode.MARKDOWN)

# ===== SICK/OFF COMMANDS =====
async def mark_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    cmd = message.text.split()[0][1:]  # sick/off
    now = gmt5_now()
    date = now.strftime("%Y-%m-%d")
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO attendance (user_id, date, status, clock_in, clock_out, late_minutes) VALUES (?, ?, ?, ?, ?, ?)",
                (user.id, date, cmd.capitalize(), None, None, 0))
    conn.commit()
    conn.close()
    await message.reply_text(f"✅ Marked as {cmd.capitalize()} for {date}")

# ===== SHOW ATTENDANCE =====
async def show_staff_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message.reply_to_message:
        staff_id = message.reply_to_message.from_user.id
    elif len(context.args) > 0:
        staff_id = int(context.args[0])
    else:
        await message.reply_text("Reply to staff or provide ID/username to show details")
        return
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM staff WHERE user_id=?", (staff_id,))
    row = cur.fetchone()
    if not row:
        await message.reply_text("Staff not found")
        return
    name = row[0]
    # Fetch attendance
    cur.execute("SELECT status, COUNT(*) FROM attendance WHERE user_id=? GROUP BY status", (staff_id,))
    counts = {r[0]: r[1] for r in cur.fetchall()}
    total_clocked = counts.get("Clocked In", 0)
    total_absent = counts.get("Absent", 0)
    total_late = counts.get("Clocked In", 0)  # sum late minutes
    cur.execute("SELECT SUM(late_minutes) FROM attendance WHERE user_id=?", (staff_id,))
    late_sum = cur.fetchone()[0] or 0
    total_sick = counts.get("Sick", 0)
    total_off = counts.get("Off", 0)
    conn.close()
    text = f"*Attendance Summary for [{escape_markdown(name)}](tg://user?id={staff_id})*\n"
    text += f"• Total Days Clocked: {total_clocked}\n"
    text += f"• Absent Days: {total_absent}\n"
    text += f"• Late Days: {total_late} (Total Late Minutes: {late_sum})\n"
    text += f"• Sick Days: {total_sick}\n"
    text += f"• Off Days: {total_off}\n"
    await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ===== BROKEN GLASS LOG =====
def extract_broken_by(text: str):
    match = re.search(r"broken\s*by\s*[:\-–=•]*\s*([^\n]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None

async def report_glass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message.photo:
        return
    text = message.caption or ""
    broken_by = extract_broken_by(text)
    if not broken_by:
        return
    reporter = message.from_user
    photo = message.photo[-1].file_id
    now = gmt5_now()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M")
    msg_link = f"https://t.me/c/{str(GROUP_ID)[4:]}/{message.message_id}"
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO broken_logs (reported_by_id, reported_by_name, broken_by, photo_file_id, date, time, message_link) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (reporter.id, reporter.full_name, broken_by, photo, date, time, msg_link))
    conn.commit()
    conn.close()
    caption = f"#update\n• Reported by: {escape_markdown(reporter.full_name)}\n• Broken by: {escape_markdown(broken_by)}\n• Date: {date}\n• Time: {time}\n• Message link: [Go to message]({msg_link})"
    await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=photo, caption=caption, parse_mode=ParseMode.MARKDOWN)
    await message.reply_text(f"✅ Report logged for {broken_by}")

# ===== ATTENDANCE REPORT =====
async def attendance_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT a.date, s.full_name, a.status, a.clock_in, a.clock_out, a.late_minutes, s.user_id FROM attendance a LEFT JOIN staff s ON a.user_id=s.user_id")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await message.reply_text("No attendance data found.")
        return
    df = pd.DataFrame(rows, columns=["Date", "Staff Name", "Status", "Clock In", "Clock Out", "Late Minutes", "User ID"])
    # Create Excel
    file_path = f"Attendance_Report_{gmt5_now().strftime('%Y-%m')}.xlsx"
    df.to_excel(file_path, index=False)
    await message.reply_document(document=open(file_path, "rb"))

# ===== RESET HISTORY =====
async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance")
    cur.execute("DELETE FROM broken_logs")
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ All history cleared.")

# ===== MAIN =====
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Staff management
    app.add_handler(CommandHandler("add", add_staff))
    app.add_handler(CommandHandler("rm", rm_staff))
    app.add_handler(CommandHandler("staff", list_staff))

    # Clock-in/clock-out
    app.add_handler(MessageHandler(filters.Regex(r"^at fr$") | filters.Regex(r"^/clock$"), clock_in))

    # Sick/off
    app.add_handler(CommandHandler("sick", mark_status))
    app.add_handler(CommandHandler("off", mark_status))

    # Show staff details
    app.add_handler(CommandHandler("show", show_staff_detail))

    # Broken glass
    app.add_handler(MessageHandler(filters.PHOTO & filters.Chat(GROUP_ID), report_glass))

    # Attendance report
    app.add_handler(CommandHandler("report", attendance_report))

    # Reset
    app.add_handler(CommandHandler("reset", reset_history))

    print("✅ FRC Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()

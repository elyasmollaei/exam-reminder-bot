# bot.py
# ربات چندگروهی یادآور — مالک/مدیر خودکار، عضویت کانال اجباری، تگ اعضا، ارسال پیوی
# نیازمندی: python-telegram-bot==20.3 , pytz , schedule

import os
import json
import asyncio
import datetime
import uuid
import pytz
from typing import Dict, Any, List
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ---------- تنظیمات ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")  # حتما در Render/Env مقداردهی شود
REQUIRED_CHANNEL = "@aporoir"       # کانال اجباری
DATA_FILE = "data.json"
IRAN_TZ = pytz.timezone("Asia/Tehran")
CHECK_INTERVAL_MINUTES = 60         # هر چند دقیقه چک شود
MAX_MENTIONS = 50                   # حداکثر تعداد تگ در پیام گروه

# ---------- کمک‌کننده‌ها ----------
def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        data = {"groups": {}}
        save_data(data)
        return data
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data: Dict[str, Any]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def normalize_digits(s: str) -> str:
    P = {'۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9',
         '٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9'}
    for k,v in P.items():
        s = s.replace(k,v)
    return s

def parse_date(date_str: str):
    """
    پارس تاریخ با فرمت YYYY.MM.DD
    (توجه: اگر تاریخ را بر پایه تقویم شمسی وارد می‌کنید—در این نسخه ما همان اعداد را مستقیم می‌خوانیم،
    در صورت نیاز بعدا می‌توانیم تبدیل تقویم شمسی -> میلادی اضافه کنیم)
    """
    try:
        ds = normalize_digits(date_str.strip())
        parts = ds.split(".")
        if len(parts) != 3:
            return None
        y, m, d = map(int, parts)
        return datetime.date(y, m, d)
    except Exception:
        return None

def ensure_group(data: Dict[str,Any], chat_id: int) -> Dict[str,Any]:
    key = str(chat_id)
    if key not in data["groups"]:
        data["groups"][key] = {"owners": [], "admins": [], "members": [], "reminders": []}
    return data["groups"][key]

def find_member_index(members: List[Dict[str,Any]], user_id: int) -> int:
    for i, m in enumerate(members):
        if m.get("id") == user_id:
            return i
    return -1

def mention_text_for_members(members: List[Dict[str,Any]]) -> str:
    mentions = []
    c = 0
    for m in members:
        if c >= MAX_MENTIONS:
            break
        if m.get("username"):
            mentions.append(f"@{m['username']}")
        else:
            name = m.get("name") or "کاربر"
            mentions.append(f"[{name}](tg://user?id={m['id']})")
        c += 1
    return " ".join(mentions)

# ---------- بررسی عضویت در کانال REQUIRED_CHANNEL ----------
async def is_member_of_required_channel(bot, user_id: int) -> bool:
    try:
        r = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return r.status in ("member", "creator", "administrator")
    except Exception:
        return False

# ---------- بروزرسانی لیست ادمین‌ها و صاحب گروه (owner) با getChatAdministrators ----------
async def refresh_group_admins_and_owner(bot, chat_id: int):
    data = load_data()
    g = ensure_group(data, chat_id)
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = []
        owner_id = None
        for a in admins:
            user = a.user
            status = a.status  # "creator" or "administrator"
            admin_ids.append(user.id)
            if status == "creator":
                owner_id = user.id
        g["admins"] = list(set(admin_ids))
        if owner_id:
            if owner_id not in g["owners"]:
                g["owners"].append(owner_id)
        save_data(data)
    except Exception:
        # اگر دسترسی نبود (مثلاً ربات ادمین نیست)، نادیده بگیر
        pass

# ---------- هندلرها ----------

# /start در پیوی یا گروه
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    data = load_data()
    if chat.type == "private":
        await update.message.reply_text(
            "👋 سلام! من ربات یادآور هستم.\n"
            "برای ثبت یادآوری در گروه‌ها از فرمت:\n`یادآوری/YYYY.MM.DD عنوان`\n"
            "استفاده کن.\n\n"
            f"توجه: برای ساخت یادآوری باید عضو کانال {REQUIRED_CHANNEL} باشی."
        )
    else:
        await update.message.reply_text("ربات فعال است. پیام‌هایی که با `یادآوری/` شروع شوند پردازش می‌شوند.")

    # ثبت عضو در لیست members گروه (برای تگ و ارسال پیوی)
    if chat.type in ("group", "supergroup"):
        g = ensure_group(data, chat.id)
        idx = find_member_index(g["members"], user.id)
        name = (user.first_name or "") + (" " + (user.last_name or "") if user.last_name else "")
        if idx == -1:
            g["members"].append({"id": user.id, "username": user.username, "name": name, "started": True})
        else:
            g["members"][idx].update({"username": user.username, "name": name, "started": True})
        save_data(data)
        # refresh admins/owner asynchronously
        await refresh_group_admins_and_owner(context.bot, chat.id)

# /join در گروه برای ثبت کاربر جهت دریافت پیوی
async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور را در گروه اجرا کن.")
        return
    data = load_data()
    g = ensure_group(data, chat.id)
    idx = find_member_index(g["members"], user.id)
    name = (user.first_name or "") + (" " + (user.last_name or "") if user.last_name else "")
    if idx == -1:
        g["members"].append({"id": user.id, "username": user.username, "name": name, "started": True})
    else:
        g["members"][idx].update({"username": user.username, "name": name, "started": True})
    save_data(data)
    await update.message.reply_text("✅ شما برای دریافت یادآوری‌ها ثبت شدی.")

# /setadmin (تنظیم ادمین) — فقط owner یا تلگرام admin می‌تواند
async def setadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور در گروه اجرا می‌شود.")
        return
    data = load_data()
    g = ensure_group(data, chat.id)
    # بررسی اینکه کاربر خودِ گروه creator یا ادمین تلگرامی است
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("❌ فقط ادمین‌های تلگرام یا سازندهٔ گروه می‌توانند ادمین تنظیم کنند.")
            return
    except Exception:
        await update.message.reply_text("❌ خطا در بررسی دسترسی.")
        return

    # هدف: باید ریپلای یا @username بعد از دستور
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    else:
        parts = update.message.text.split()
        if len(parts) >= 2:
            uname = parts[1].lstrip("@")
            for m in g["members"]:
                if m.get("username") and m["username"].lower() == uname.lower():
                    class U: pass
                    t = U()
                    t.id = m["id"]; t.username = m.get("username"); t.first_name = m.get("name")
                    target = t
                    break
    if not target:
        await update.message.reply_text("برای تنظیم ادمین: `/setadmin @username` یا ریپلای به پیام کاربر.")
        return
    if target.id not in g["admins"]:
        g["admins"].append(target.id)
    save_data(data)
    await update.message.reply_text(f"✅ {target.first_name or target.username} به عنوان ادمین تنظیم شد.")

# /removeadmin در گروه
async def removeadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    data = load_data()
    g = ensure_group(data, chat.id)
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("❌ فقط ادمین‌های تلگرام یا سازندهٔ گروه می‌توانند اینکار را انجام دهند.")
            return
    except Exception:
        await update.message.reply_text("❌ خطا در بررسی دسترسی.")
        return

    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    else:
        parts = update.message.text.split()
        if len(parts) >= 2:
            uname = parts[1].lstrip("@")
            for m in g["members"]:
                if m.get("username") and m["username"].lower() == uname.lower():
                    class U: pass
                    t = U()
                    t.id = m["id"]; t.username = m.get("username"); t.first_name = m.get("name")
                    target = t
                    break
    if not target:
        await update.message.reply_text("برای حذف ادمین: `/removeadmin @username` یا ریپلای به پیام کاربر.")
        return
    if target.id in g["admins"]:
        g["admins"].remove(target.id)
    save_data(data)
    await update.message.reply_text(f"✅ {target.first_name or target.username} از ادمین‌ها حذف شد.")

# پیام‌های گروه: فقط پیام‌هایی که با "یادآوری/" شروع شوند پردازش می‌شوند
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    user = update.effective_user
    text = (msg.text or "").strip()
    data = load_data()
    g = ensure_group(data, chat.id)

    # ثبت/به‌روزرسانی عضو
    idx = find_member_index(g["members"], user.id)
    name = (user.first_name or "") + (" " + (user.last_name or "") if user.last_name else "")
    if idx == -1:
        g["members"].append({"id": user.id, "username": user.username, "name": name, "started": True})
    else:
        g["members"][idx].update({"username": user.username, "name": name, "started": True})
    save_data(data)

    # فقط پیام‌هایی با prefix
    if not (text.startswith("یادآوری/") or text.startswith("یادآوری /")):
        return

    # بررسی عضویت سازنده در REQUIRED_CHANNEL
    ok_channel = await is_member_of_required_channel(context.bot, user.id)
    if not ok_channel:
        await msg.reply_text(f"⚠️ برای استفاده از ربات باید عضو کانال {REQUIRED_CHANNEL} باشید.")
        return

    # استخراج تاریخ و عنوان
    after = text.split("/",1)[1].strip()
    if not after:
        await msg.reply_text("❌ فرمت نادرست. مثال: `یادآوری/1404.08.07 امتحان علوم`", parse_mode="Markdown")
        return
    parts = after.split(" ",1)
    if len(parts) < 2:
        await msg.reply_text("❌ بعد از تاریخ یک فاصله و سپس عنوان را بنویس.", parse_mode="Markdown")
        return
    date_part = parts[0].strip()
    title = parts[1].strip()
    exam_date = parse_date(date_part)
    if not exam_date:
        await msg.reply_text("❌ تاریخ باید به صورت `YYYY.MM.DD` باشد.", parse_mode="Markdown")
        return

    # بررسی دسترسی: مالک یا ادمین تلگرامی یا ادمین ثبت‌شده
    allowed = False
    try:
        mem = await context.bot.get_chat_member(chat.id, user.id)
        if mem.status in ("creator", "administrator"):
            allowed = True
    except Exception:
        pass
    # یا اگر user.id در g["owners"] یا g["admins"] ذخیره شده
    if user.id in g.get("owners", []):
        allowed = True
    if user.id in g.get("admins", []):
        allowed = True
    if not allowed:
        await msg.reply_text("❌ فقط مالک یا ادمین گروه می‌تواند یادآوری ثبت کند.")
        return

    # ذخیره یادآوری
    rid = str(uuid.uuid4())
    reminder = {"id": rid, "date": date_part, "title": title, "creator_id": user.id, "chat_id": chat.id}
    g.setdefault("reminders", []).append(reminder)
    save_data(data)
    # به‌روزرسانی لیست admins/owner از سرور تلگرام (ضمنی)
    await refresh_group_admins_and_owner(context.bot, chat.id)

    await msg.reply_text(f"✅ یادآوری «{title}» برای {date_part} ثبت شد. یادآوری‌ها 2 روز، 1 روز و روزِ امتحان ارسال می‌شوند.")

# ارسال یادآوری برای یک reminder: در گروه تگ و در پی‌وی به اعضای ثبت‌شده پیام می‌فرستد
async def send_reminder_for(rem: Dict[str,Any], app):
    data = load_data()
    chat_id = rem["chat_id"]
    g = data["groups"].get(str(chat_id), {})
    members = g.get("members", [])
    mention_text = mention_text_for_members(members)
    if mention_text:
        group_msg = f"🔔 یادآوری: {rem['title']}\n({rem['date']})\n\n{mention_text}"
    else:
        group_msg = f"🔔 یادآوری: {rem['title']}\n({rem['date']})"

    try:
        await app.bot.send_message(chat_id=chat_id, text=group_msg, parse_mode="Markdown")
    except Exception:
        pass

    # ارسال پیوی
    for m in members:
        if not m.get("started"):
            continue
        uid = m["id"]
        private_text = f"🔔 یادآوری از گروه {chat_id}:\n{rem['title']}\n({rem['date']})"
        try:
            await app.bot.send_message(chat_id=uid, text=private_text)
        except Exception:
            # اگر پیوی بسته باشه یا بلاک شده باشه، نادیده می‌گیره
            pass

# بررسی همه یادآوری‌ها و ارسال در روزهای 2/1/0
async def check_and_send_all(app):
    data = load_data()
    today = datetime.datetime.now(IRAN_TZ).date()
    for gid, g in data["groups"].items():
        for rem in g.get("reminders", []):
            ex_date = parse_date(rem["date"])
            if not ex_date:
                continue
            diff = (ex_date - today).days
            if diff in (2,1,0):
                # ارسال
                await send_reminder_for(rem, app)

# Scheduler دوره‌ای
async def scheduler_loop(app):
    while True:
        try:
            await check_and_send_all(app)
        except Exception as e:
            print("Scheduler error:", e)
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)

# پنل ساده خصوصی برای owner: لیست گروه‌ها و export json
async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type != "private":
        await update.message.reply_text("این دستور فقط در پیوی قابل استفاده است.")
        return
    data = load_data()
    uid = user.id
    # چک اگر owner تلگرامی (تو این نسخه owner = کسی که در owners لیست گروه بود)
    # برای سادگی: اگر uid در owners هر گروه باشد پنل آن گروه نشان داده می‌شود
    owned_groups = []
    for gid, g in data["groups"].items():
        if uid in g.get("owners", []):
            owned_groups.append(gid)
    if not owned_groups:
        await update.message.reply_text("❌ شما مالک هیچ گروهی ثبت‌شده‌ای نیستید.")
        return
    keyboard = []
    for gid in owned_groups:
        keyboard.append([InlineKeyboardButton(f"گروه: {gid}", callback_data=f"owner::group::{gid}")])
    keyboard.append([InlineKeyboardButton("📤 خروجی JSON", callback_data="owner::export")])
    await update.message.reply_text("👑 گروه‌های شما:", reply_markup=InlineKeyboardMarkup(keyboard))

# callback handler (برای پنل owner)
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    uid = query.from_user.id
    parts = query.data.split("::")
    if parts[0] == "owner":
        if parts[1] == "group":
            gid = parts[2]
            g = data["groups"].get(gid, {})
            text = f"📋 اطلاعات گروه {gid}:\nOwners: {g.get('owners',[])}\nAdmins: {g.get('admins',[])}\nMembers: {len(g.get('members',[]))}\nReminders: {len(g.get('reminders',[]))}"
            await query.edit_message_text(text)
        elif parts[1] == "export":
            try:
                with open(DATA_FILE, "rb") as f:
                    await context.bot.send_document(chat_id=uid, document=f, filename="data.json")
                await query.edit_message_text("✅ فایل JSON برای شما ارسال شد.")
            except Exception:
                await query.edit_message_text("❌ خطا در ارسال فایل JSON.")

# ---------- اجرای اصلی ----------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN در متغیرهای محیطی تنظیم نشده.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("setadmin", setadmin_cmd))
    app.add_handler(CommandHandler("removeadmin", removeadmin_cmd))
    app.add_handler(CommandHandler("panel", panel_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, start_cmd))

    # start scheduler after init
    app.post_init(lambda _: asyncio.create_task(scheduler_loop(app)))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

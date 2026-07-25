import os
from threading import Thread
from flask import Flask

app = Flask('')


@app.route('/')
def home():
  return 'Bot is running!'


def run():
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)


Thread(target=run).start()

import subprocess, sys

# ─── تثبيت المكتبات تلقائياً ───
required = ["python-telegram-bot==21.6", "python-dotenv==1.0.1"]
subprocess.check_call([sys.executable, "-m", "pip", "install", *required, "-q"])

# ─────────────────────────────────────────────────────────────
import os, sqlite3, asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import (
    Update, ReplyKeyboardMarkup,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes,
)
from telegram.constants import ParseMode

load_dotenv()

BOT_TOKEN     = os.getenv("BOT_TOKEN", "")
ADMIN_IDS     = [int(x.strip()) for x in os.getenv("ADMIN_ID", "0").split(",") if x.strip()]
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "")

DB_PATH = "bot.db"

# ─── حالات المحادثة ───
WHEEL_FULL_NAME, WHEEL_USERNAME, WHEEL_BOT_NAME, WHEEL_CONFIRM = range(4)
ADMIN_BROADCAST_MSG, ADMIN_ADD_CH_NAME, ADMIN_ADD_CH_URL, ADMIN_EDIT_UID, ADMIN_EDIT_AMOUNT = range(10, 15)

# ─────────────────────────────────────────────
# قاعدة البيانات
# ─────────────────────────────────────────────

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id              INTEGER PRIMARY KEY,
            username             TEXT,
            display_name         TEXT,
            total_referrals      INTEGER DEFAULT 0,
            available_referrals  INTEGER DEFAULT 0,
            wheel_participations INTEGER DEFAULT 0,
            joined_at            TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wheel_registrations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER NOT NULL,
            full_name        TEXT NOT NULL,
            telegram_username TEXT NOT NULL,
            bot_name         TEXT NOT NULL,
            registered_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS channels (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url  TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

def ensure_user(user_id, username=None, display_name=None):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (user_id,username,display_name,joined_at) VALUES (?,?,?,?)",
            (user_id, username or "", display_name or "", datetime.now().isoformat()),
        )
        conn.commit()
    conn.close()

def get_user(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def add_referral(referrer_id):
    conn = db()
    conn.execute(
        "UPDATE users SET total_referrals=total_referrals+1, available_referrals=available_referrals+1 WHERE user_id=?",
        (referrer_id,),
    )
    conn.commit()
    conn.close()

def consume_referrals(user_id):
    conn = db()
    conn.execute(
        "UPDATE users SET available_referrals=available_referrals-3, wheel_participations=wheel_participations+1 WHERE user_id=?",
        (user_id,),
    )
    conn.commit()
    conn.close()

def save_wheel_registration(user_id, full_name, tg_username, bot_name):
    conn = db()
    conn.execute(
        "INSERT INTO wheel_registrations (user_id,full_name,telegram_username,bot_name,registered_at) VALUES (?,?,?,?,?)",
        (user_id, full_name, tg_username, bot_name, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

def get_all_user_ids():
    conn = db()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]

def get_all_wheel_registrations():
    conn = db()
    rows = conn.execute("""
        SELECT wr.*, u.available_referrals, u.wheel_participations
        FROM wheel_registrations wr
        JOIN users u ON wr.user_id=u.user_id
        ORDER BY wr.registered_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_channels():
    conn = db()
    rows = conn.execute("SELECT * FROM channels ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_channel(name, url):
    conn = db()
    conn.execute("INSERT INTO channels (name,url) VALUES (?,?)", (name, url))
    conn.commit()
    conn.close()

def delete_channel(channel_id):
    conn = db()
    conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))
    conn.commit()
    conn.close()

def update_user_balance(user_id, delta):
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET available_referrals=MAX(0,available_referrals+?) WHERE user_id=?",
        (delta, user_id),
    )
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

# ─────────────────────────────────────────────
# أدوات مساعدة
# ─────────────────────────────────────────────

def is_admin(user_id): return user_id in ADMIN_IDS

MAIN_KB = ReplyKeyboardMarkup(
    [["🎡 التسجيل في العجلة"],
     ["🔗 نظام الإحالات", "📢 قنواتنا"],
     ["ℹ️ حول البوت والشروط"]],
    resize_keyboard=True,
)
CANCEL_KB = ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)

def admin_panel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📣 إذاعة رسالة",          callback_data="admin_broadcast")],
        [InlineKeyboardButton("📢 إدارة القنوات",         callback_data="admin_channels")],
        [InlineKeyboardButton("👤 تعديل رصيد مستخدم",    callback_data="admin_edit_balance")],
        [InlineKeyboardButton("📋 قائمة المسجلين في العجلة", callback_data="admin_wheel_list")],
    ])

def channels_manage_kb(channels):
    rows = [[InlineKeyboardButton(f"🗑 {ch['name']}", callback_data=f"del_ch_{ch['id']}")] for ch in channels]
    rows.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="admin_add_channel")])
    rows.append([InlineKeyboardButton("🔙 رجوع",       callback_data="admin_back")])
    return InlineKeyboardMarkup(rows)

async def send_log(context, user_data, reg):
    if not LOG_CHANNEL_ID:
        return
    text = (
        f"🎯 <b>طلب تسجيل جديد في العجلة!</b>\n\n"
        f"👤 <b>الاسم الكامل:</b> {reg['full_name']}\n"
        f"🔗 <b>اليوزر:</b> @{reg['tg_username']}\n"
        f"🆔 <b>الاسم في البوت:</b> {reg['bot_name']}\n"
        f"🔢 <b>آيدي المستخدم:</b> <code>{reg['user_id']}</code>\n"
        f"📊 <b>إجمالي مشاركاته في العجلة:</b> {user_data.get('wheel_participations', 0)}"
    )
    try:
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.full_name)

    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user.id and get_user(referrer_id):
                add_referral(referrer_id)
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text="🎉 انضم صديق جديد عبر رابط إحالتك!\n✅ تم إضافة إحالة نشطة جديدة إلى رصيدك.",
                    )
                except Exception:
                    pass
        except (ValueError, TypeError):
            pass

    await update.message.reply_text(
        f"👋 مرحباً {user.first_name}!\n\n"
        "🎡 أهلاً بك في بوت عجلة الحظ والمسابقات.\n"
        "اختر من القائمة أدناه للبدء:",
        reply_markup=MAIN_KB,
    )

# ─────────────────────────────────────────────
# /admin
# ─────────────────────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ليس لديك صلاحية الوصول.")
        return
    await update.message.reply_text(
        "👑 <b>لوحة تحكم المشرف</b>\n\nاختر الإجراء المطلوب:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_panel_kb(),
    )

# ─────────────────────────────────────────────
# القائمة الرئيسية
# ─────────────────────────────────────────────

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    ensure_user(update.effective_user.id, update.effective_user.username, update.effective_user.full_name)

    if text == "📢 قنواتنا":
        channels = get_channels()
        if not channels:
            await update.message.reply_text("📢 لا توجد قنوات مضافة حالياً.", reply_markup=MAIN_KB)
            return
        buttons = [[InlineKeyboardButton(ch["name"], url=ch["url"])] for ch in channels]
        await update.message.reply_text("📢 <b>قنواتنا:</b>", parse_mode=ParseMode.HTML,
                                        reply_markup=InlineKeyboardMarkup(buttons))
    elif text == "ℹ️ حول البوت والشروط":
        await update.message.reply_text(
            "ℹ️ <b>حول البوت والشروط</b>\n\n"
            "🎡 هذا البوت مخصص لتسجيل المستخدمين في عجلة الحظ والمسابقات.\n\n"
            "<b>الشروط والأحكام:</b>\n"
            "• يجب امتلاك 3 إحالات نشطة للتسجيل في العجلة.\n"
            "• يُخصم 3 إحالات من رصيدك عند كل تسجيل ناجح.\n"
            "• يمكن الحصول على إحالات عبر دعوة الأصدقاء برابط الإحالة الخاص بك.\n"
            "• يحق للإدارة تعديل الشروط في أي وقت.",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_KB,
        )

# ─────────────────────────────────────────────
# نظام الإحالات
# ─────────────────────────────────────────────

async def handle_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.full_name)
    data = get_user(user.id)
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.id}"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📤 مشاركة رابط الإحالة",
            url=f"https://t.me/share/url?url={ref_link}&text=🎡 انضم معي في عجلة الحظ!",
        )
    ]])
    await update.message.reply_text(
        f"🔗 <b>نظام الإحالات</b>\n\n"
        f"رابط الإحالة الخاص بك:\n<code>{ref_link}</code>\n\n"
        f"👥 <b>إجمالي الإحالات الكلي:</b> {data['total_referrals']}\n"
        f"✅ <b>الإحالات المتاحة للتسجيل:</b> {data['available_referrals']}/3\n"
        f"🎡 <b>مرات المشاركة في العجلة:</b> {data['wheel_participations']}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

# ─────────────────────────────────────────────
# محادثة التسجيل في العجلة
# ─────────────────────────────────────────────

async def wheel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.full_name)
    data = get_user(user.id)
    available = data["available_referrals"]

    if available < 3:
        await update.message.reply_text(
            f"⚠️ عذراً، تحتاج إلى 3 إحالات نشطة للتسجيل في العجلة.\n"
            f"رصيدك الحالي المتاح: ({available}/3)\n\n"
            "ادعُ أصدقاءك عبر رابط الإحالة للحصول على المزيد!",
            reply_markup=MAIN_KB,
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "📝 <b>التسجيل في العجلة</b>\n\nالخطوة 1 من 3\nأدخل <b>اسمك الكامل</b>:",
        parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB,
    )
    return WHEEL_FULL_NAME

async def wheel_get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await wheel_cancel(update, context)
    context.user_data["wheel_full_name"] = update.message.text.strip()
    await update.message.reply_text(
        "الخطوة 2 من 3\nأدخل <b>يوزر التيليجرام</b> الخاص بك (بدون @):",
        parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB,
    )
    return WHEEL_USERNAME

async def wheel_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await wheel_cancel(update, context)
    context.user_data["wheel_tg_username"] = update.message.text.strip().lstrip("@")
    await update.message.reply_text(
        "الخطوة 3 من 3\nأدخل <b>اسمك المفضل داخل البوت</b>:",
        parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB,
    )
    return WHEEL_BOT_NAME

async def wheel_get_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await wheel_cancel(update, context)
    context.user_data["wheel_bot_name"] = update.message.text.strip()

    full_name   = context.user_data["wheel_full_name"]
    tg_username = context.user_data["wheel_tg_username"]
    bot_name    = context.user_data["wheel_bot_name"]

    await update.message.reply_text(
        f"📋 <b>مراجعة بياناتك:</b>\n\n"
        f"👤 الاسم الكامل: <b>{full_name}</b>\n"
        f"🔗 اليوزر: <b>@{tg_username}</b>\n"
        f"🆔 الاسم في البوت: <b>{bot_name}</b>\n\n"
        "هل تريد تأكيد التسجيل؟ سيتم خصم 3 إحالات من رصيدك.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ تأكيد", callback_data="wheel_confirm"),
            InlineKeyboardButton("❌ إلغاء", callback_data="wheel_cancel"),
        ]]),
    )
    return WHEEL_CONFIRM

async def wheel_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "wheel_cancel":
        await query.edit_message_text("❌ تم إلغاء التسجيل.")
        await query.message.reply_text("تم الإلغاء. يمكنك التسجيل في أي وقت.", reply_markup=MAIN_KB)
        context.user_data.clear()
        return ConversationHandler.END

    data = get_user(user.id)
    if not data or data["available_referrals"] < 3:
        await query.edit_message_text("⚠️ رصيدك المتاح غير كافٍ. تحتاج إلى 3 إحالات نشطة.")
        await query.message.reply_text("العودة للقائمة الرئيسية.", reply_markup=MAIN_KB)
        context.user_data.clear()
        return ConversationHandler.END

    full_name   = context.user_data["wheel_full_name"]
    tg_username = context.user_data["wheel_tg_username"]
    bot_name    = context.user_data["wheel_bot_name"]

    consume_referrals(user.id)
    save_wheel_registration(user.id, full_name, tg_username, bot_name)
    updated = get_user(user.id)

    await send_log(context, updated, {
        "user_id": user.id, "full_name": full_name,
        "tg_username": tg_username, "bot_name": bot_name,
    })

    await query.edit_message_text(
        f"✅ <b>تم التسجيل بنجاح في العجلة!</b>\n\n"
        f"👤 الاسم الكامل: {full_name}\n"
        f"🔗 اليوزر: @{tg_username}\n"
        f"🆔 الاسم في البوت: {bot_name}\n\n"
        "سيتواصل معك فريقنا قريباً. حظاً موفقاً! 🎉",
        parse_mode=ParseMode.HTML,
    )
    await query.message.reply_text("يمكنك العودة للقائمة الرئيسية:", reply_markup=MAIN_KB)
    context.user_data.clear()
    return ConversationHandler.END

async def wheel_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم إلغاء عملية التسجيل.", reply_markup=MAIN_KB)
    context.user_data.clear()
    return ConversationHandler.END

# ─────────────────────────────────────────────
# لوحة تحكم المشرف — Callbacks
# ─────────────────────────────────────────────

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("⛔ ليس لديك صلاحية.", show_alert=True)
        return ConversationHandler.END

    d = query.data

    if d == "admin_back":
        await query.edit_message_text(
            "👑 <b>لوحة تحكم المشرف</b>\n\nاختر الإجراء المطلوب:",
            parse_mode=ParseMode.HTML, reply_markup=admin_panel_kb(),
        )
        return ConversationHandler.END

    if d == "admin_broadcast":
        await query.edit_message_text("📣 أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين:\n(أرسل /cancel للإلغاء)")
        return ADMIN_BROADCAST_MSG

    if d == "admin_channels":
        channels = get_channels()
        await query.edit_message_text(
            "📢 <b>إدارة القنوات</b>\n\nاضغط على اسم القناة لحذفها:",
            parse_mode=ParseMode.HTML, reply_markup=channels_manage_kb(channels),
        )
        return ConversationHandler.END

    if d.startswith("del_ch_"):
        delete_channel(int(d.split("_")[-1]))
        await query.edit_message_text(
            "✅ تم حذف القناة.\n\n📢 <b>إدارة القنوات:</b>",
            parse_mode=ParseMode.HTML, reply_markup=channels_manage_kb(get_channels()),
        )
        return ConversationHandler.END

    if d == "admin_add_channel":
        await query.edit_message_text(
            "➕ أرسل <b>اسم القناة</b> الجديدة:\n(أرسل /cancel للإلغاء)",
            parse_mode=ParseMode.HTML,
        )
        return ADMIN_ADD_CH_NAME

    if d == "admin_edit_balance":
        await query.edit_message_text(
            "👤 أرسل <b>آيدي المستخدم</b> الذي تريد تعديل رصيده:\n(أرسل /cancel للإلغاء)",
            parse_mode=ParseMode.HTML,
        )
        return ADMIN_EDIT_UID

    if d == "admin_wheel_list":
        regs = get_all_wheel_registrations()
        if not regs:
            await query.edit_message_text(
                "📋 لا يوجد مسجلون في العجلة حتى الآن.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]),
            )
            return ConversationHandler.END
        lines = ["📋 <b>قائمة المسجلين في العجلة:</b>\n"]
        for i, r in enumerate(regs[:20], 1):
            lines.append(
                f"{i}. <b>{r['full_name']}</b> | @{r['telegram_username']}\n"
                f"   🆔 البوت: {r['bot_name']} | آيدي: <code>{r['user_id']}</code>\n"
                f"   🎡 المشاركات: {r['wheel_participations']} | 📅 {r['registered_at'][:10]}"
            )
        if len(regs) > 20:
            lines.append(f"\n... و{len(regs)-20} آخرين")
        await query.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]),
        )
        return ConversationHandler.END

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم إلغاء العملية.", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def admin_broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/cancel":
        return await admin_cancel(update, context)
    sent = failed = 0
    for uid in get_all_user_ids():
        try:
            await update.message.copy_to(chat_id=uid)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(
        f"✅ تمت الإذاعة!\n📤 أُرسلت إلى: {sent} مستخدم\n❌ فشل الإرسال: {failed}",
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END

async def admin_add_ch_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/cancel":
        return await admin_cancel(update, context)
    context.user_data["new_ch_name"] = update.message.text.strip()
    await update.message.reply_text(
        "🔗 أرسل <b>رابط القناة</b> (مثال: https://t.me/channel):",
        parse_mode=ParseMode.HTML,
    )
    return ADMIN_ADD_CH_URL

async def admin_add_ch_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/cancel":
        return await admin_cancel(update, context)
    name = context.user_data.pop("new_ch_name", "قناة")
    add_channel(name, update.message.text.strip())
    await update.message.reply_text(
        f"✅ تمت إضافة القناة:\n📢 <b>{name}</b>\n🔗 {update.message.text.strip()}",
        parse_mode=ParseMode.HTML, reply_markup=MAIN_KB,
    )
    return ConversationHandler.END

async def admin_edit_uid_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/cancel":
        return await admin_cancel(update, context)
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ الرجاء إرسال آيدي صحيح (أرقام فقط).")
        return ADMIN_EDIT_UID
    user_data = get_user(uid)
    if not user_data:
        await update.message.reply_text(f"❌ لم يتم العثور على مستخدم بالآيدي {uid}.")
        return ADMIN_EDIT_UID
    context.user_data["edit_uid"] = uid
    await update.message.reply_text(
        f"✅ المستخدم: <code>{uid}</code>\n"
        f"📊 رصيده الحالي: {user_data['available_referrals']} إحالة\n\n"
        "أرسل الكمية للتعديل:\n"
        "• زيادة: رقم موجب (مثال: <code>5</code>)\n"
        "• نقصان: رقم سالب (مثال: <code>-3</code>)",
        parse_mode=ParseMode.HTML,
    )
    return ADMIN_EDIT_AMOUNT

async def admin_edit_amount_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/cancel":
        return await admin_cancel(update, context)
    try:
        delta = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ الرجاء إرسال رقم صحيح.")
        return ADMIN_EDIT_AMOUNT
    uid = context.user_data.pop("edit_uid", None)
    if update_user_balance(uid, delta):
        updated = get_user(uid)
        sign = "+" if delta > 0 else ""
        await update.message.reply_text(
            f"✅ تم تعديل رصيد المستخدم <code>{uid}</code>\n"
            f"التعديل: {sign}{delta}\n"
            f"الرصيد الجديد: {updated['available_referrals']} إحالة",
            parse_mode=ParseMode.HTML, reply_markup=MAIN_KB,
        )
    else:
        await update.message.reply_text("❌ حدث خطأ أثناء تعديل الرصيد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ─────────────────────────────────────────────
# التشغيل
# ─────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        print("❌ خطأ: BOT_TOKEN غير موجود في ملف .env")
        sys.exit(1)

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    wheel_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎡 التسجيل في العجلة$"), wheel_start)],
        states={
            WHEEL_FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, wheel_get_full_name)],
            WHEEL_USERNAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, wheel_get_username)],
            WHEEL_BOT_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, wheel_get_bot_name)],
            WHEEL_CONFIRM:   [CallbackQueryHandler(wheel_confirm_callback, pattern="^wheel_")],
        },
        fallbacks=[
            CommandHandler("cancel", wheel_cancel),
            MessageHandler(filters.Regex("^❌ إلغاء$"), wheel_cancel),
        ],
        allow_reentry=True,
    )

    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^admin_|^del_ch_")],
        states={
            ADMIN_BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_broadcast_receive)],
            ADMIN_ADD_CH_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_ch_name)],
            ADMIN_ADD_CH_URL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_ch_url)],
            ADMIN_EDIT_UID:      [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_uid_receive)],
            ADMIN_EDIT_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_amount_receive)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(wheel_conv)
    app.add_handler(admin_conv)
    app.add_handler(MessageHandler(filters.Regex("^🔗 نظام الإحالات$"), handle_referrals))
    app.add_handler(MessageHandler(filters.Regex("^(📢 قنواتنا|ℹ️ حول البوت والشروط)$"), handle_main_menu))

    print("✅ البوت يعمل الآن...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

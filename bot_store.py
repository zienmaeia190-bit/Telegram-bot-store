import json
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
import os

TOKEN = "7993490818:AAHwGNPmA6-OMk5kBcDdabEGGV9QYWGKtmg"
OWNER_ID = 7486398081  # معرفك الخاص

POINTS_FILE = "user_points.json"

# حالات المحادثة
(
    MAIN_MENU,
    WAIT_TRANSFER_NUMBER,
    WAIT_AMOUNT,
    WAIT_PUBG_ID,
) = range(4)

user_states = {}

# النقاط الافتراضية لكل مستخدم جديد
DEFAULT_POINTS = 20000

def load_points():
    if os.path.exists(POINTS_FILE):
        with open(POINTS_FILE, "r") as f:
            return json.load(f)
    else:
        return {}

def save_points(points):
    with open(POINTS_FILE, "w") as f:
        json.dump(points, f)

def get_points(user_id):
    points = load_points()
    return points.get(str(user_id), DEFAULT_POINTS)

def set_points(user_id, new_points):
    points = load_points()
    points[str(user_id)] = new_points
    save_points(points)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def show_main_menu(update, context):
    keyboard = [
        [InlineKeyboardButton("الشحن", callback_data="recharge")],
        [InlineKeyboardButton("الخدمات", callback_data="services")],
        [InlineKeyboardButton(f"رصيدي: {get_points(update.effective_user.id)} نقطة", callback_data="my_points")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("أهلاً بك في متجرنا! اختر من القائمة:", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text("أهلاً بك في متجرنا! اختر من القائمة:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "recharge":
        await query.message.reply_text(
            "يرجى إرسال رقم عملية التحويل:",
            reply_markup=ReplyKeyboardRemove()
        )
        user_states[query.from_user.id] = WAIT_TRANSFER_NUMBER
        return WAIT_TRANSFER_NUMBER

    elif query.data == "services":
        services_keyboard = [
            [InlineKeyboardButton("ببجي موبايل 60 شده", callback_data="pubg_60_uc")],
            [InlineKeyboardButton("رجوع", callback_data="back")],
        ]
        await query.message.edit_text("اختر الخدمة:", reply_markup=InlineKeyboardMarkup(services_keyboard))
        return MAIN_MENU

    elif query.data == "pubg_60_uc":
        await query.message.reply_text("يرجى إرسال الايدي الخاص بك في ببجي:")
        user_states[query.from_user.id] = WAIT_PUBG_ID
        return WAIT_PUBG_ID

    elif query.data == "my_points":
        await query.message.reply_text(f"رصيدك الحالي: {get_points(query.from_user.id)} نقطة.")
        return MAIN_MENU

    elif query.data == "back":
        await show_main_menu(update, context)
        return MAIN_MENU

    return MAIN_MENU

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = user_states.get(user_id, MAIN_MENU)

    # حالة الشحن - رقم العملية
    if state == WAIT_TRANSFER_NUMBER:
        context.user_data["transfer_number"] = text
        await update.message.reply_text("الرجاء إدخال المبلغ:")
        user_states[user_id] = WAIT_AMOUNT
        return WAIT_AMOUNT

    # حالة الشحن - المبلغ
    elif state == WAIT_AMOUNT:
        transfer_number = context.user_data.get("transfer_number")
        amount = text
        await update.message.reply_text(
            "تم استلام البيانات. سيتم مراجعة الطلب قريبًا.",
            reply_markup=ReplyKeyboardRemove()
        )
        # إرسال تنبيه للإدارة
        admin_id = OWNER_ID
        msg = f"طلب شحن جديد:\nالمستخدم: {update.effective_user.full_name} ({user_id})\nرقم العملية: {transfer_number}\nالمبلغ: {amount}"
        await context.bot.send_message(chat_id=admin_id, text=msg)
        user_states[user_id] = MAIN_MENU
        await show_main_menu(update, context)
        return MAIN_MENU

    # حالة خدمة ببجي
    elif state == WAIT_PUBG_ID:
        pubg_id = text
        points = get_points(user_id)
        if points < 10000:
            await update.message.reply_text("عذراً، رصيدك غير كافٍ! (المطلوب: 10000 نقطة)")
            user_states[user_id] = MAIN_MENU
            await show_main_menu(update, context)
            return MAIN_MENU

        new_points = points - 10000
        set_points(user_id, new_points)
        await update.message.reply_text(
            f"تم استلام الايدي بنجاح! سيتم تنفيذ الطلب قريباً. تم خصم 10000 نقطة. رصيدك الآن: {new_points} نقطة.",
            reply_markup=ReplyKeyboardRemove()
        )
        # إرسال تنبيه للإدارة
        admin_id = OWNER_ID
        msg = f"طلب خدمة ببجي 60 شده:\nالمستخدم: {update.effective_user.full_name} ({user_id})\nالايدي: {pubg_id}\nرصيده الآن: {new_points} نقطة"
        await context.bot.send_message(chat_id=admin_id, text=msg)
        user_states[user_id] = MAIN_MENU
        await show_main_menu(update, context)
        return MAIN_MENU

    else:
        await show_main_menu(update, context)
        return MAIN_MENU

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(button_handler)],
            WAIT_TRANSFER_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)],
            WAIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)],
            WAIT_PUBG_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

    # استقبال أي رسالة نصية وإعادة توجيهها للمعالج الرئيسي
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

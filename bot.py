# telegram_dating_bot.py
import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ---------- CONFIG ----------
BOT_TOKEN = "8378719727:AAFXRT1dLqzo3C4sz92Z9rxtUoObUeTKge4"  # <- replace with your token (or use env var)
DB_PATH = "dating_bot.db"

# ---------- States for registration ----------
NAME, AGE, GENDER, PREFERENCE, INTERESTS, BIO = range(6)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Database helpers ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            gender TEXT,
            preference TEXT,
            interests TEXT,
            bio TEXT,
            username TEXT,
            created_at TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS likes (
            liker_id INTEGER,
            liked_id INTEGER,
            timestamp TEXT,
            UNIQUE(liker_id, liked_id)
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS passes (
            passer_id INTEGER,
            passed_id INTEGER,
            timestamp TEXT,
            UNIQUE(passer_id, passed_id)
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
            user1 INTEGER,
            user2 INTEGER,
            timestamp TEXT,
            UNIQUE(user1, user2)
        )
        """
    )
    conn.commit()
    conn.close()

def save_profile(user_id, name, age, gender, preference, interests, bio, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute(
        """
        INSERT OR REPLACE INTO profiles
        (user_id, name, age, gender, preference, interests, bio, username, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, name, age, gender, preference, interests, bio, username, now),
    )
    conn.commit()
    conn.close()

def get_profile(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def insert_like(liker_id, liked_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    try:
        c.execute(
            "INSERT INTO likes (liker_id, liked_id, timestamp) VALUES (?, ?, ?)",
            (liker_id, liked_id, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def insert_pass(passer_id, passed_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    try:
        c.execute(
            "INSERT INTO passes (passer_id, passed_id, timestamp) VALUES (?, ?, ?)",
            (passer_id, passed_id, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def already_liked(liker_id, liked_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM likes WHERE liker_id = ? AND liked_id = ?",
        (liker_id, liked_id),
    )
    res = c.fetchone()
    conn.close()
    return bool(res)

def reciprocal_like_exists(a, b):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM likes WHERE liker_id = ? AND liked_id = ?", (b, a))
    res = c.fetchone()
    conn.close()
    return bool(res)

def create_match(a, b):
    user1, user2 = (a, b) if a <= b else (b, a)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    try:
        c.execute(
            "INSERT INTO matches (user1, user2, timestamp) VALUES (?, ?, ?)",
            (user1, user2, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def has_passed(passer_id, passed_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM passes WHERE passer_id = ? AND passed_id = ?", (passer_id, passed_id)
    )
    res = c.fetchone()
    conn.close()
    return bool(res)

def find_matches_for(user_id, max_results=5):
    user = get_profile(user_id)
    if not user:
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE user_id != ?", (user_id,))
    candidates = [dict(r) for r in c.fetchall()]
    conn.close()

    def normalize_interests(s):
        return {i.strip().lower() for i in (s or "").split(",") if i.strip()}

    u_interests = normalize_interests(user.get("interests", ""))

    results = []
    for cand in candidates:
        # preferences/gender checks
        if user["preference"].lower() != "any" and cand["gender"].lower() != user["preference"].lower():
            continue
        if cand["preference"].lower() != "any" and cand["preference"].lower() != user["gender"].lower():
            continue
        # age filter (+/-5)
        try:
            age_ok = abs(int(cand["age"]) - int(user["age"])) <= 5
        except Exception:
            age_ok = True
        if not age_ok:
            continue
        # skip if already liked or passed
        if already_liked(user_id, cand["user_id"]) or has_passed(user_id, cand["user_id"]):
            continue
        # interest overlap OR allow if either has no interests
        c_interests = normalize_interests(cand.get("interests", ""))
        if u_interests and c_interests:
            if len(u_interests.intersection(c_interests)) == 0:
                continue

        # compute score for ordering (more common interests -> higher)
        score = len(u_interests.intersection(c_interests))
        results.append((score, cand))

    # sort by score desc, return top N
    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:max_results]]

# ---------- Bot command handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Hey! 👋 Welcome to *Study* (dating) bot MVP.\n\n"
        "I'll collect a few details to create your profile.\n"
        "What's your *full name*? (send it as text)"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return NAME

async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Nice! How old are you? (send a number)")
    return AGE

async def age_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text("Please send your age as a number (e.g., 21).")
        return AGE
    context.user_data["age"] = int(txt)
    await update.message.reply_text("What's your gender? (Male / Female / Other)")
    return GENDER

async def gender_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    g = update.message.text.strip().capitalize()
    if g.lower() not in ("male", "female", "other"):
        await update.message.reply_text("Reply with Male, Female, or Other.")
        return GENDER
    context.user_data["gender"] = g
    await update.message.reply_text("Who are you interested in? (Male / Female / Any)")
    return PREFERENCE

async def pref_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = update.message.text.strip().capitalize()
    if p.lower() not in ("male", "female", "any"):
        await update.message.reply_text("Reply with Male, Female, or Any.")
        return PREFERENCE
    context.user_data["preference"] = p
    await update.message.reply_text(
        "List a few interests (comma-separated). Example: music, cricket, coding"
    )
    return INTERESTS

async def interests_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["interests"] = update.message.text.strip()
    await update.message.reply_text("Write a short bio about yourself (1-2 lines).")
    return BIO

async def bio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bio = update.message.text.strip()
    context.user_data["bio"] = bio

    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    d = context.user_data
    save_profile(
        user_id,
        d.get("name", ""),
        d.get("age", None),
        d.get("gender", ""),
        d.get("preference", ""),
        d.get("interests", ""),
        d.get("bio", ""),
        username,
    )
    await update.message.reply_text(
        "Profile saved! 🎉\n\nUse /profile to view your profile and /match to find someone."
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Profile creation cancelled. Use /start to try again.")
    context.user_data.clear()
    return ConversationHandler.END

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    p = get_profile(user_id)
    if not p:
        await update.message.reply_text("No profile found. Use /start to create one.")
        return
    txt = (
        f"*Your profile*\n\n"
        f"Name: {p['name']}\n"
        f"Age: {p['age']}\n"
        f"Gender: {p['gender']}\n"
        f"Preference: {p['preference']}\n"
        f"Interests: {p['interests']}\n"
        f"Bio: {p['bio']}\n"
        f"Telegram username: @{p['username']}" if p.get("username") else ""
    )
    await update.message.reply_text(txt, parse_mode="Markdown")

# ---------- Matching flow ----------
def build_profile_text(candidate: dict):
    txt = (
        f"*{candidate['name']}*, {candidate.get('age','?')} • {candidate.get('gender','')}\n"
        f"{candidate.get('bio','')} \n\n"
        f"Interests: {candidate.get('interests','(none)')}\n"
    )
    return txt

async def match_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not get_profile(user_id):
        await update.message.reply_text("Create a profile first with /start.")
        return
    matches = find_matches_for(user_id, max_results=1)
    if not matches:
        await update.message.reply_text("No matches found right now. Try again later.")
        return
    cand = matches[0]
    txt = build_profile_text(cand)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❤️ Like", callback_data=f"like_{cand['user_id']}"),
                InlineKeyboardButton("❌ Pass", callback_data=f"pass_{cand['user_id']}"),
            ]
        ]
    )
    await update.message.reply_text(txt, reply_markup=keyboard, parse_mode="Markdown")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("like_"):
        target_id = int(data.split("_", 1)[1])
        if already_liked(user_id, target_id):
            await query.edit_message_text("You already liked this profile.")
            return
        insert_like(user_id, target_id)
        # check reciprocal
        if reciprocal_like_exists(user_id, target_id):
            create_match(user_id, target_id)
            # fetch profiles to show usernames if available
            p1 = get_profile(user_id)
            p2 = get_profile(target_id)
            # notify both
            txt1 = "It's a MATCH! 🎉\n"
            if p2 and p2.get("username"):
                txt1 += f"You matched with *{p2['name']}*. Their Telegram: @{p2['username']}\n"
            else:
                txt1 += f"You matched with *{p2['name']}*. They haven't set a username — try messaging them via Telegram if possible.\n"
            txt2 = "It's a MATCH! 🎉\n"
            if p1 and p1.get("username"):
                txt2 += f"You matched with *{p1['name']}*. Their Telegram: @{p1['username']}\n"
            else:
                txt2 += f"You matched with *{p1['name']}*.\n"

            try:
                await context.bot.send_message(chat_id=user_id, text=txt1, parse_mode="Markdown")
                await context.bot.send_message(chat_id=target_id, text=txt2, parse_mode="Markdown")
            except Exception as e:
                logger.error("Error sending match messages: %s", e)
            await query.edit_message_text("You liked them — and it's a match! 🎉")
        else:
            await query.edit_message_text("You liked this profile. If they like you back, we'll notify you!")
    elif data.startswith("pass_"):
        target_id = int(data.split("_", 1)[1])
        if has_passed(user_id, target_id):
            await query.edit_message_text("Already passed.")
            return
        insert_pass(user_id, target_id)
        await query.edit_message_text("Passed — we'll show someone else next time.")
    else:
        await query.edit_message_text("Unknown action.")

# ---------- Main ----------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_handler)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, gender_handler)],
            PREFERENCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pref_handler)],
            INTERESTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, interests_handler)],
            BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, bio_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("profile", show_profile))
    app.add_handler(CommandHandler("match", match_cmd))
    app.add_handler(CallbackQueryHandler(callback_query_handler))

    logger.info("Bot starting (Polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()

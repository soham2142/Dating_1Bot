from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")  # must come from environment variable

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot started! Welcome 😎")

def main():
    # Build Application
    app = Application.builder().token(BOT_TOKEN).build()

    # Add Handlers
    app.add_handler(CommandHandler("start", start))

    # Run bot
    app.run_polling()

if __name__ == "__main__":
    main()

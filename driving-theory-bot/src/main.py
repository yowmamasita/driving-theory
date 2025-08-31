import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

from database.db_manager import DatabaseManager
from utils.question_loader import QuestionLoader
from handlers.quiz_handler import QuizHandler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()


class DrivingTheoryBot:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables")
        
        self.db_manager = DatabaseManager()
        # Get the parent directory of the driving-theory-bot folder
        questions_dir = Path(__file__).parent.parent.parent
        self.question_loader = QuestionLoader(questions_dir)
        self.quiz_handler = QuizHandler(self.db_manager, self.question_loader)
        self.application = None
    
    async def initialize(self):
        await self.db_manager.connect()
        logger.info("Database connected and initialized")
        
        # Restore active sessions from previous bot run
        await self.quiz_handler.restore_sessions()
    
    async def shutdown(self):
        await self.db_manager.close()
        logger.info("Database connection closed")
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Exception while handling an update: {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "An error occurred while processing your request. Please try again."
            )
    
    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.quiz_handler.handle_start))
        self.application.add_handler(CommandHandler("stats", self.quiz_handler.handle_stats))
        self.application.add_handler(CommandHandler("resend", self.quiz_handler.handle_resend))
        self.application.add_handler(CommandHandler("skip", self.quiz_handler.handle_skip))
        
        # Add message handler for text input (language selection and answers)
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.quiz_handler.handle_message
            )
        )
        
        self.application.add_error_handler(self.error_handler)
    
    async def run(self):
        await self.initialize()
        
        self.application = Application.builder().token(self.token).build()
        self.setup_handlers()
        
        await self.application.initialize()
        await self.application.start()
        
        logger.info("Bot started. Press Ctrl+C to stop.")
        
        await self.application.updater.start_polling()
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
        finally:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            await self.shutdown()


async def main():
    bot = DrivingTheoryBot()
    await bot.run()


if __name__ == '__main__':
    asyncio.run(main())
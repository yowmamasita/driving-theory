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

from database.optimized_db_manager import OptimizedDatabaseManager
from utils.optimized_question_loader import OptimizedQuestionLoader
from utils.rate_limiter import RateLimiter
from handlers.optimized_quiz_handler import OptimizedQuizHandler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()


class OptimizedDrivingTheoryBot:
    """
    Optimized bot capable of handling thousands of concurrent users.
    
    Key optimizations:
    - Database connection pooling (20 connections)
    - Batch writing for database operations
    - In-memory caching for frequently accessed data
    - Rate limiting to prevent abuse
    - Async I/O for all operations
    - Efficient memory usage with LRU caches
    """
    
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables")
        
        # Use optimized components
        self.db_manager = OptimizedDatabaseManager(pool_size=20)
        
        # Get the parent directory of the driving-theory-bot folder
        questions_dir = Path(__file__).parent.parent.parent
        self.question_loader = OptimizedQuestionLoader(questions_dir)
        
        # Rate limiter: 10 requests per minute per user, burst of 15
        self.rate_limiter = RateLimiter(rate=10, window=60, burst=15)
        
        # Use optimized quiz handler
        self.quiz_handler = OptimizedQuizHandler(self.db_manager, self.question_loader)
        
        self.application = None
    
    async def initialize(self):
        """Initialize all components"""
        await self.db_manager.connect()
        logger.info("Database pool connected and initialized")
        
        await self.question_loader.initialize()
        logger.info("Questions loaded and indexed")
        
        await self.rate_limiter.start()
        logger.info("Rate limiter started")
        
        # Restore active sessions from previous bot run
        await self.quiz_handler.restore_sessions()
        logger.info("Sessions restored")
    
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down bot...")
        
        await self.rate_limiter.stop()
        await self.db_manager.close()
        logger.info("Cleanup completed")
    
    def rate_limited_handler(self, handler):
        """Wrapper to add rate limiting to handlers"""
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            # Check rate limit
            if not await self.rate_limiter.check_rate_limit(user_id):
                remaining = self.rate_limiter.get_remaining_tokens(user_id)
                await update.message.reply_text(
                    f"⚠️ Rate limit exceeded. Please wait a moment.\n"
                    f"Remaining capacity: {remaining:.1f}"
                )
                return
            
            # Process request
            await handler(update, context)
        
        return wrapper
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced error handler with logging"""
        logger.error(f"Exception while handling an update: {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "An error occurred while processing your request. Please try again."
            )
    
    def setup_handlers(self):
        """Setup command and message handlers with rate limiting"""
        # Wrap handlers with rate limiting
        self.application.add_handler(
            CommandHandler("start", self.rate_limited_handler(self.quiz_handler.handle_start))
        )
        self.application.add_handler(
            CommandHandler("stats", self.rate_limited_handler(self.quiz_handler.handle_stats))
        )
        self.application.add_handler(
            CommandHandler("resend", self.rate_limited_handler(self.quiz_handler.handle_resend))
        )
        self.application.add_handler(
            CommandHandler("skip", self.rate_limited_handler(self.quiz_handler.handle_skip))
        )
        
        # Message handler for text input
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.rate_limited_handler(self.quiz_handler.handle_message)
            )
        )
        
        self.application.add_error_handler(self.error_handler)
    
    async def run(self):
        """Run the bot"""
        await self.initialize()
        
        # Configure application with optimizations
        self.application = (
            Application.builder()
            .token(self.token)
            .concurrent_updates(True)  # Process updates concurrently
            .pool_timeout(60.0)  # Longer timeout for heavy load
            .connection_pool_size(20)  # Larger connection pool
            .build()
        )
        
        self.setup_handlers()
        
        await self.application.initialize()
        await self.application.start()
        
        logger.info("Optimized bot started. Press Ctrl+C to stop.")
        logger.info("Configuration:")
        logger.info("- Database pool size: 20 connections")
        logger.info("- Rate limit: 10 requests/minute per user")
        logger.info("- Concurrent updates: Enabled")
        logger.info("- Memory optimization: LRU caching enabled")
        
        await self.application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True  # Don't process old messages on restart
        )
        
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
    bot = OptimizedDrivingTheoryBot()
    await bot.run()


if __name__ == '__main__':
    # Run with uvloop for better performance (optional)
    try:
        import uvloop
        uvloop.install()
        logger.info("Using uvloop for better performance")
    except ImportError:
        pass
    
    asyncio.run(main())
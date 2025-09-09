import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from functools import lru_cache
import logging
import json

from .db_pool import DatabasePool

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Optimized database manager for handling thousands of concurrent users.
    Uses connection pooling, caching, and batch operations.
    """
    
    def __init__(self, db_path: str = "driving_theory_bot.db", pool_size: int = 20):
        self.pool = DatabasePool(db_path, pool_size)
        self._user_cache = {}  # Simple cache for user data
        self._cache_lock = asyncio.Lock()
        self._batch_queue = []
        self._batch_lock = asyncio.Lock()
        self._batch_task = None
    
    async def connect(self):
        """Initialize database pool and create tables"""
        await self.pool.initialize()
        await self.initialize_database()
        
        # Start batch processor
        self._batch_task = asyncio.create_task(self._process_batch_writes())
    
    async def close(self):
        """Close database connections and cleanup"""
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        
        # Process any remaining batch writes
        await self._flush_batch()
        await self.pool.close()
    
    async def initialize_database(self):
        """Create database tables with optimized schema"""
        schema = """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                preferred_language TEXT NOT NULL DEFAULT 'english',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                total_questions_answered INTEGER DEFAULT 0
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS question_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_telegram_id INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                language TEXT NOT NULL,
                is_correct BOOLEAN NOT NULL,
                attempted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                time_taken_seconds INTEGER,
                FOREIGN KEY (user_telegram_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS spaced_repetition (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_telegram_id INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                language TEXT NOT NULL,
                repetition_count INTEGER DEFAULT 0,
                ease_factor REAL DEFAULT 2.5,
                interval_days INTEGER DEFAULT 1,
                next_review TIMESTAMP NOT NULL,
                last_reviewed TIMESTAMP NOT NULL,
                UNIQUE(user_telegram_id, question_id, language),
                FOREIGN KEY (user_telegram_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                user_telegram_id INTEGER PRIMARY KEY,
                current_question_id TEXT NOT NULL,
                language TEXT NOT NULL,
                question_start_time TIMESTAMP,
                awaiting_answer BOOLEAN DEFAULT 1,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_telegram_id) REFERENCES users(telegram_id)
            ) WITHOUT ROWID;

            -- Optimized indexes for concurrent access
            CREATE INDEX IF NOT EXISTS idx_attempts_user_time ON question_attempts(user_telegram_id, attempted_at DESC);
            CREATE INDEX IF NOT EXISTS idx_attempts_question ON question_attempts(question_id);
            CREATE INDEX IF NOT EXISTS idx_spaced_user_review ON spaced_repetition(user_telegram_id, next_review);
            CREATE INDEX IF NOT EXISTS idx_sessions_updated ON user_sessions(updated_at DESC);
        """
        
        async with self.pool.acquire() as conn:
            await conn.executescript(schema)
            await conn.commit()
    
    async def get_or_create_user(self, telegram_id: int, username: Optional[str] = None) -> Dict[str, Any]:
        """Get or create user with caching"""
        # Check cache first
        async with self._cache_lock:
            if telegram_id in self._user_cache:
                return self._user_cache[telegram_id]
        
        # Check database
        user = await self.pool.fetchone(
            "SELECT * FROM users WHERE telegram_id = ?", 
            (telegram_id,)
        )
        
        if not user:
            await self.pool.execute(
                "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
                (telegram_id, username)
            )
            user = await self.pool.fetchone(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
        
        user_dict = dict(user)
        
        # Update cache
        async with self._cache_lock:
            self._user_cache[telegram_id] = user_dict
        
        return user_dict
    
    async def update_user_language(self, telegram_id: int, language: str):
        """Update user language preference"""
        await self.pool.execute(
            "UPDATE users SET preferred_language = ? WHERE telegram_id = ?",
            (language, telegram_id)
        )
        
        # Update cache
        async with self._cache_lock:
            if telegram_id in self._user_cache:
                self._user_cache[telegram_id]['preferred_language'] = language
    
    async def record_question_attempt(
        self, 
        user_telegram_id: int, 
        question_id: str, 
        language: str,
        is_correct: bool,
        time_taken_seconds: Optional[int] = None
    ):
        """Queue question attempt for batch processing"""
        async with self._batch_lock:
            self._batch_queue.append({
                'type': 'attempt',
                'user_telegram_id': user_telegram_id,
                'question_id': question_id,
                'language': language,
                'is_correct': is_correct,
                'time_taken_seconds': time_taken_seconds,
                'timestamp': datetime.now()
            })
    
    async def _process_batch_writes(self):
        """Process batch writes periodically"""
        while True:
            try:
                await asyncio.sleep(2)  # Process every 2 seconds
                await self._flush_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in batch processor: {e}")
    
    async def _flush_batch(self):
        """Flush batch queue to database"""
        async with self._batch_lock:
            if not self._batch_queue:
                return
            
            batch = self._batch_queue[:]
            self._batch_queue.clear()
        
        # Group by type for efficient batch inserts
        attempts = [b for b in batch if b['type'] == 'attempt']
        
        if attempts:
            await self.pool.executemany(
                """INSERT INTO question_attempts 
                   (user_telegram_id, question_id, language, is_correct, time_taken_seconds, attempted_at) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(a['user_telegram_id'], a['question_id'], a['language'], 
                  a['is_correct'], a['time_taken_seconds'], a['timestamp']) for a in attempts]
            )
            
            # Update user totals
            user_updates = {}
            for a in attempts:
                user_id = a['user_telegram_id']
                user_updates[user_id] = user_updates.get(user_id, 0) + 1
            
            for user_id, count in user_updates.items():
                await self.pool.execute(
                    "UPDATE users SET total_questions_answered = total_questions_answered + ? WHERE telegram_id = ?",
                    (count, user_id)
                )
    
    async def get_user_statistics(self, telegram_id: int) -> Dict[str, Any]:
        """Get user statistics with optimized query"""
        result = await self.pool.fetchone(
            """SELECT 
                COUNT(*) as total_attempts,
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_answers,
                AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100 as accuracy_percentage
               FROM question_attempts 
               WHERE user_telegram_id = ?""",
            (telegram_id,)
        )
        
        return dict(result) if result else {}
    
    async def update_spaced_repetition(
        self,
        user_telegram_id: int,
        question_id: str,
        language: str,
        is_correct: bool
    ):
        """Update spaced repetition data"""
        sr_data = await self.pool.fetchone(
            """SELECT * FROM spaced_repetition 
               WHERE user_telegram_id = ? AND question_id = ? AND language = ?""",
            (user_telegram_id, question_id, language)
        )
        
        if not sr_data:
            next_review = datetime.now() + timedelta(days=1)
            await self.pool.execute(
                """INSERT INTO spaced_repetition 
                   (user_telegram_id, question_id, language, next_review, last_reviewed) 
                   VALUES (?, ?, ?, ?, ?)""",
                (user_telegram_id, question_id, language, next_review, datetime.now())
            )
        else:
            sr_dict = dict(sr_data)
            ease_factor = sr_dict['ease_factor']
            interval_days = sr_dict['interval_days']
            repetition_count = sr_dict['repetition_count']
            
            if is_correct:
                ease_factor = min(ease_factor + 0.1, 3.0)
                interval_days = max(1, int(interval_days * ease_factor))
                repetition_count += 1
            else:
                ease_factor = max(ease_factor - 0.2, 1.3)
                interval_days = 1
                repetition_count = 0
            
            next_review = datetime.now() + timedelta(days=interval_days)
            
            await self.pool.execute(
                """UPDATE spaced_repetition 
                   SET ease_factor = ?, interval_days = ?, repetition_count = ?, 
                       next_review = ?, last_reviewed = ?
                   WHERE user_telegram_id = ? AND question_id = ? AND language = ?""",
                (ease_factor, interval_days, repetition_count, next_review, datetime.now(),
                 user_telegram_id, question_id, language)
            )
    
    async def get_next_question_for_review(
        self, 
        user_telegram_id: int, 
        language: str
    ) -> Optional[str]:
        """Get next question for spaced repetition review"""
        result = await self.pool.fetchone(
            """SELECT question_id FROM spaced_repetition 
               WHERE user_telegram_id = ? AND language = ? AND next_review <= ?
               ORDER BY next_review ASC LIMIT 1""",
            (user_telegram_id, language, datetime.now())
        )
        
        return dict(result)['question_id'] if result else None
    
    async def get_attempted_questions(
        self, 
        user_telegram_id: int, 
        language: str
    ) -> List[str]:
        """Get list of attempted questions"""
        results = await self.pool.fetchall(
            """SELECT DISTINCT question_id FROM question_attempts 
               WHERE user_telegram_id = ? AND language = ?
               ORDER BY attempted_at DESC
               LIMIT 1000""",  # Limit for performance
            (user_telegram_id, language)
        )
        
        return [dict(r)['question_id'] for r in results]
    
    async def save_user_session(
        self,
        user_telegram_id: int,
        current_question_id: str,
        language: str,
        question_start_time: Optional[datetime] = None,
        awaiting_answer: bool = True
    ):
        """Save user session"""
        await self.pool.execute(
            """INSERT OR REPLACE INTO user_sessions 
               (user_telegram_id, current_question_id, language, question_start_time, awaiting_answer, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_telegram_id, current_question_id, language, question_start_time, awaiting_answer, datetime.now())
        )
    
    async def get_user_session(self, user_telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user session"""
        session = await self.pool.fetchone(
            "SELECT * FROM user_sessions WHERE user_telegram_id = ?",
            (user_telegram_id,)
        )
        
        return dict(session) if session else None
    
    async def clear_user_session(self, user_telegram_id: int):
        """Clear user session"""
        await self.pool.execute(
            "DELETE FROM user_sessions WHERE user_telegram_id = ?",
            (user_telegram_id,)
        )
    
    async def get_all_active_sessions(self) -> List[Dict[str, Any]]:
        """Get all active sessions within last 24 hours"""
        sessions = await self.pool.fetchall(
            """SELECT * FROM user_sessions 
               WHERE awaiting_answer = 1 
               AND datetime(updated_at) > datetime('now', '-24 hours')
               ORDER BY updated_at DESC
               LIMIT 10000""",  # Limit for safety
        )
        
        return [dict(s) for s in sessions]
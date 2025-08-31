import aiosqlite
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: str = "driving_theory_bot.db"):
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        await self.initialize_database()

    async def close(self):
        if self.connection:
            await self.connection.close()

    async def initialize_database(self):
        async with self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                preferred_language TEXT NOT NULL DEFAULT 'english',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                total_questions_answered INTEGER DEFAULT 0
            );

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
            );

            CREATE INDEX IF NOT EXISTS idx_attempts_user ON question_attempts(user_telegram_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_question ON question_attempts(question_id);
            CREATE INDEX IF NOT EXISTS idx_spaced_user ON spaced_repetition(user_telegram_id);
            CREATE INDEX IF NOT EXISTS idx_spaced_next_review ON spaced_repetition(next_review);
        """) as cursor:
            pass
        await self.connection.commit()

    async def get_or_create_user(self, telegram_id: int, username: Optional[str] = None) -> Dict[str, Any]:
        async with self.connection.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            user = await cursor.fetchone()
            
        if not user:
            await self.connection.execute(
                "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
                (telegram_id, username)
            )
            await self.connection.commit()
            async with self.connection.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            ) as cursor:
                user = await cursor.fetchone()
        
        return dict(user)

    async def update_user_language(self, telegram_id: int, language: str):
        await self.connection.execute(
            "UPDATE users SET preferred_language = ? WHERE telegram_id = ?",
            (language, telegram_id)
        )
        await self.connection.commit()

    async def record_question_attempt(
        self, 
        user_telegram_id: int, 
        question_id: str, 
        language: str,
        is_correct: bool,
        time_taken_seconds: Optional[int] = None
    ):
        await self.connection.execute(
            """INSERT INTO question_attempts 
               (user_telegram_id, question_id, language, is_correct, time_taken_seconds) 
               VALUES (?, ?, ?, ?, ?)""",
            (user_telegram_id, question_id, language, is_correct, time_taken_seconds)
        )
        
        await self.connection.execute(
            "UPDATE users SET total_questions_answered = total_questions_answered + 1 WHERE telegram_id = ?",
            (user_telegram_id,)
        )
        
        await self.connection.commit()

    async def get_user_statistics(self, telegram_id: int) -> Dict[str, Any]:
        async with self.connection.execute(
            """SELECT 
                COUNT(*) as total_attempts,
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct_answers,
                AVG(CASE WHEN is_correct THEN 1 ELSE 0 END) * 100 as accuracy_percentage
               FROM question_attempts 
               WHERE user_telegram_id = ?""",
            (telegram_id,)
        ) as cursor:
            stats = await cursor.fetchone()
        
        return dict(stats) if stats else {}

    async def update_spaced_repetition(
        self,
        user_telegram_id: int,
        question_id: str,
        language: str,
        is_correct: bool
    ):
        async with self.connection.execute(
            """SELECT * FROM spaced_repetition 
               WHERE user_telegram_id = ? AND question_id = ? AND language = ?""",
            (user_telegram_id, question_id, language)
        ) as cursor:
            sr_data = await cursor.fetchone()
        
        if not sr_data:
            next_review = datetime.now() + timedelta(days=1)
            await self.connection.execute(
                """INSERT INTO spaced_repetition 
                   (user_telegram_id, question_id, language, next_review, last_reviewed) 
                   VALUES (?, ?, ?, ?, ?)""",
                (user_telegram_id, question_id, language, next_review, datetime.now())
            )
        else:
            ease_factor = dict(sr_data)['ease_factor']
            interval_days = dict(sr_data)['interval_days']
            repetition_count = dict(sr_data)['repetition_count']
            
            if is_correct:
                ease_factor = min(ease_factor + 0.1, 3.0)
                interval_days = max(1, int(interval_days * ease_factor))
                repetition_count += 1
            else:
                ease_factor = max(ease_factor - 0.2, 1.3)
                interval_days = 1
                repetition_count = 0
            
            next_review = datetime.now() + timedelta(days=interval_days)
            
            await self.connection.execute(
                """UPDATE spaced_repetition 
                   SET ease_factor = ?, interval_days = ?, repetition_count = ?, 
                       next_review = ?, last_reviewed = ?
                   WHERE user_telegram_id = ? AND question_id = ? AND language = ?""",
                (ease_factor, interval_days, repetition_count, next_review, datetime.now(),
                 user_telegram_id, question_id, language)
            )
        
        await self.connection.commit()

    async def get_next_question_for_review(
        self, 
        user_telegram_id: int, 
        language: str
    ) -> Optional[str]:
        async with self.connection.execute(
            """SELECT question_id FROM spaced_repetition 
               WHERE user_telegram_id = ? AND language = ? AND next_review <= ?
               ORDER BY next_review ASC LIMIT 1""",
            (user_telegram_id, language, datetime.now())
        ) as cursor:
            result = await cursor.fetchone()
        
        return dict(result)['question_id'] if result else None

    async def get_attempted_questions(
        self, 
        user_telegram_id: int, 
        language: str
    ) -> List[str]:
        async with self.connection.execute(
            """SELECT DISTINCT question_id FROM question_attempts 
               WHERE user_telegram_id = ? AND language = ?""",
            (user_telegram_id, language)
        ) as cursor:
            results = await cursor.fetchall()
        
        return [dict(r)['question_id'] for r in results]
    
    async def save_user_session(
        self,
        user_telegram_id: int,
        current_question_id: str,
        language: str,
        question_start_time: Optional[datetime] = None,
        awaiting_answer: bool = True
    ):
        await self.connection.execute(
            """INSERT OR REPLACE INTO user_sessions 
               (user_telegram_id, current_question_id, language, question_start_time, awaiting_answer, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_telegram_id, current_question_id, language, question_start_time, awaiting_answer, datetime.now())
        )
        await self.connection.commit()
    
    async def get_user_session(self, user_telegram_id: int) -> Optional[Dict[str, Any]]:
        async with self.connection.execute(
            "SELECT * FROM user_sessions WHERE user_telegram_id = ?",
            (user_telegram_id,)
        ) as cursor:
            session = await cursor.fetchone()
        
        return dict(session) if session else None
    
    async def clear_user_session(self, user_telegram_id: int):
        await self.connection.execute(
            "DELETE FROM user_sessions WHERE user_telegram_id = ?",
            (user_telegram_id,)
        )
        await self.connection.commit()
    
    async def get_all_active_sessions(self) -> List[Dict[str, Any]]:
        async with self.connection.execute(
            """SELECT * FROM user_sessions 
               WHERE awaiting_answer = 1 
               AND datetime(updated_at) > datetime('now', '-24 hours')"""
        ) as cursor:
            sessions = await cursor.fetchall()
        
        return [dict(s) for s in sessions]
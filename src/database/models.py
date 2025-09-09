from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    telegram_id: int
    username: Optional[str]
    preferred_language: str
    created_at: datetime
    total_questions_answered: int = 0


@dataclass
class QuestionAttempt:
    id: Optional[int]
    user_telegram_id: int
    question_id: str
    language: str
    is_correct: bool
    attempted_at: datetime
    time_taken_seconds: Optional[int] = None


@dataclass
class SpacedRepetition:
    id: Optional[int]
    user_telegram_id: int
    question_id: str
    language: str
    repetition_count: int
    ease_factor: float
    interval_days: int
    next_review: datetime
    last_reviewed: datetime
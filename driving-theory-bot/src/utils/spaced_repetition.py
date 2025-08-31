from datetime import datetime, timedelta
from typing import Optional


class SpacedRepetitionCalculator:
    
    MIN_EASE_FACTOR = 1.3
    MAX_EASE_FACTOR = 3.0
    EASE_INCREMENT = 0.1
    EASE_DECREMENT = 0.2
    
    @staticmethod
    def calculate_next_interval(
        current_interval: int,
        ease_factor: float,
        is_correct: bool,
        repetition_count: int
    ) -> tuple[int, float, int]:
        
        if is_correct:
            new_ease_factor = min(ease_factor + SpacedRepetitionCalculator.EASE_INCREMENT, 
                                 SpacedRepetitionCalculator.MAX_EASE_FACTOR)
            new_repetition_count = repetition_count + 1
            
            if repetition_count == 0:
                new_interval = 1
            elif repetition_count == 1:
                new_interval = 3
            else:
                new_interval = max(1, int(current_interval * new_ease_factor))
        else:
            new_ease_factor = max(ease_factor - SpacedRepetitionCalculator.EASE_DECREMENT, 
                                 SpacedRepetitionCalculator.MIN_EASE_FACTOR)
            new_repetition_count = 0
            new_interval = 1
        
        return new_interval, new_ease_factor, new_repetition_count
    
    @staticmethod
    def should_review(next_review: datetime) -> bool:
        return datetime.now() >= next_review
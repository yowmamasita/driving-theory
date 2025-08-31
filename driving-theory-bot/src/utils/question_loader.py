import json
import random
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from functools import lru_cache
import asyncio


class QuestionLoader:
    """
    Optimized question loader with caching and efficient memory usage.
    Designed to handle thousands of concurrent users.
    """
    
    def __init__(self, questions_dir: Path):
        self.questions_dir = questions_dir
        self._questions_cache = {}
        self._cache_lock = asyncio.Lock()
        self._question_index = {}  # Fast lookup by ID
        self._loaded = False
    
    async def initialize(self):
        """Lazy load questions on first use"""
        if self._loaded:
            return
        
        async with self._cache_lock:
            if self._loaded:
                return
            
            self._questions_cache['english'] = await self._load_questions_async("driving_theory_questions.json")
            self._questions_cache['deutsch'] = await self._load_questions_async("driving_theory_questions_de.json")
            
            # Build index for fast lookups
            for lang in ['english', 'deutsch']:
                for q in self._questions_cache[lang]:
                    q_id = q.get('id')
                    if q_id:
                        if q_id not in self._question_index:
                            self._question_index[q_id] = {}
                        self._question_index[q_id][lang] = q
            
            self._loaded = True
    
    async def _load_questions_async(self, filename: str) -> List[Dict[str, Any]]:
        """Load questions asynchronously"""
        file_path = self.questions_dir / filename
        if not file_path.exists():
            return []
        
        # Run file I/O in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._load_questions_sync, file_path)
    
    def _load_questions_sync(self, file_path: Path) -> List[Dict[str, Any]]:
        """Synchronous question loading"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            transformed = []
            for q in data:
                # Extract correct answers
                correct_answers = []
                if q.get('correct_answers'):
                    for ca in q.get('correct_answers', []):
                        correct_answers.append(ca['text'])
                elif q.get('correct_answer'):
                    ca = q.get('correct_answer')
                    if isinstance(ca, dict):
                        correct_answers.append(ca['text'])
                    else:
                        correct_answers.append(ca)
                
                # Get the first local image path if available
                image_path = None
                local_images = q.get('local_image_paths', [])
                if local_images and len(local_images) > 0:
                    image_path = local_images[0]
                
                transformed_q = {
                    'id': q.get('question_id', q.get('question_number', '')),
                    'question_id': q.get('question_id', ''),
                    'question_number': q.get('question_number', ''),
                    'question': q.get('question_text', ''),
                    'question_text': q.get('question_text', ''),
                    'theme_name': q.get('theme_name', ''),
                    'chapter_name': q.get('chapter_name', ''),
                    'points': q.get('points', ''),
                    'options': [opt.get('text', '') for opt in q.get('options', []) if opt.get('text')],
                    'correctAnswers': correct_answers,
                    'image': image_path,
                    'local_image_paths': q.get('local_image_paths', []),
                    'local_video_paths': q.get('local_video_paths', []),
                    'video_urls': q.get('video_urls', []),
                    'image_urls': q.get('image_urls', []),
                    'explanation': q.get('comment', q.get('explanation', ''))
                }
                
                # Handle single correct answer
                if len(transformed_q['correctAnswers']) == 1:
                    transformed_q['correctAnswer'] = transformed_q['correctAnswers'][0]
                
                # Calculate hash for the question (for deduplication)
                q_hash = hashlib.md5(
                    json.dumps(transformed_q, sort_keys=True).encode()
                ).hexdigest()
                transformed_q['hash'] = q_hash
                
                transformed.append(transformed_q)
            
            return transformed
        else:
            return data.get('questions', [])
    
    @lru_cache(maxsize=128)
    def _get_question_pool(self, language: str, exclude_hash: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get cached question pool for a language"""
        if language == 'deutsch':
            questions = self._questions_cache.get('deutsch', [])
        elif language == 'mixed':
            questions = self._questions_cache.get('english', []) + self._questions_cache.get('deutsch', [])
        else:
            questions = self._questions_cache.get('english', [])
        
        if exclude_hash:
            # This creates a new list, but it's cached
            return [q for q in questions if q.get('hash') != exclude_hash]
        
        return questions
    
    async def get_random_question(
        self, 
        language: str, 
        exclude_ids: Optional[List[str]] = None,
        user_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Get random question with efficient exclusion"""
        await self.initialize()
        
        # Don't use deterministic seeding - we want true randomness
        # If you need reproducible randomness for testing, pass a specific seed
        
        questions = self._get_question_pool(language)
        
        if not questions:
            return None
        
        # For small exclusion lists, filter directly
        if exclude_ids and len(exclude_ids) < 100:
            available = [q for q in questions if q.get('id') not in exclude_ids]
            if not available:
                available = questions  # Reset if all questions exhausted
        else:
            available = questions
        
        return random.choice(available) if available else None
    
    async def get_question_by_id(self, question_id: str, language: str) -> Optional[Dict[str, Any]]:
        """Get question by ID using index for O(1) lookup"""
        await self.initialize()
        
        # Fast lookup using index
        if question_id in self._question_index:
            langs = self._question_index[question_id]
            if language in langs:
                return langs[language]
            # Fallback to any available language
            return next(iter(langs.values())) if langs else None
        
        return None
    
    def get_question_count(self, language: str) -> int:
        """Get total number of questions for a language"""
        questions = self._get_question_pool(language)
        return len(questions)
    
    def clear_cache(self):
        """Clear LRU cache to free memory if needed"""
        self._get_question_pool.cache_clear()
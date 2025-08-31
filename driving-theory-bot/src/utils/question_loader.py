import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Any


class QuestionLoader:
    def __init__(self, questions_dir: Path):
        self.questions_dir = questions_dir
        self.english_questions = self._load_questions("driving_theory_questions.json")
        self.deutsch_questions = self._load_questions("driving_theory_questions_de.json")
    
    def _load_questions(self, filename: str) -> List[Dict[str, Any]]:
        file_path = self.questions_dir / filename
        if not file_path.exists():
            return []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Handle both formats: array directly or nested under 'questions'
            if isinstance(data, list):
                # Transform the question format to match our expected structure
                transformed = []
                for q in data:
                    # Extract the correct answer texts from the correct_answers field
                    correct_answers = []
                    options = q.get('options', [])
                    
                    if options:
                        # Multiple choice question - extract text from correct answers
                        if q.get('correct_answers'):
                            for ca in q.get('correct_answers', []):
                                correct_answers.append(ca['text'])
                        elif q.get('correct_answer'):
                            ca = q.get('correct_answer')
                            if isinstance(ca, dict):
                                correct_answers.append(ca['text'])
                            else:
                                correct_answers.append(ca)
                    else:
                        # Fill-in-the-blank question - extract from letter field
                        if q.get('correct_answers'):
                            for ca in q.get('correct_answers', []):
                                # For fill-in questions, the answer is in the 'letter' field
                                answer = ca.get('letter', ca.get('text', ''))
                                if answer:
                                    correct_answers.append(answer)
                        elif q.get('correct_answer'):
                            ca = q.get('correct_answer')
                            if isinstance(ca, dict):
                                answer = ca.get('letter', ca.get('text', ''))
                                if answer:
                                    correct_answers.append(answer)
                            else:
                                correct_answers.append(ca)
                    
                    # Get the first local image and video paths if available
                    image_path = None
                    local_images = q.get('local_image_paths', [])
                    if local_images and len(local_images) > 0:
                        image_path = local_images[0]
                    
                    video_path = None
                    local_videos = q.get('local_video_paths', [])
                    if local_videos and len(local_videos) > 0:
                        video_path = local_videos[0]
                    
                    transformed_q = {
                        'id': q.get('question_id', q.get('question_number', '')),
                        'question': q.get('question_text', ''),
                        'options': [opt.get('text', '') for opt in q.get('options', []) if opt.get('text')],
                        'correctAnswers': correct_answers,
                        'image': image_path,
                        'video': video_path,
                        'explanation': q.get('comment', q.get('explanation', '')),
                        'theme_name': q.get('theme_name', ''),
                        'chapter_name': q.get('chapter_name', ''),
                        'points': q.get('points', '')
                    }
                    # Handle single correct answer
                    if len(transformed_q['correctAnswers']) == 1:
                        transformed_q['correctAnswer'] = transformed_q['correctAnswers'][0]
                    transformed.append(transformed_q)
                return transformed
            else:
                return data.get('questions', [])
    
    def get_random_question(
        self, 
        language: str, 
        exclude_ids: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        if language == 'deutsch':
            questions = self.deutsch_questions
        elif language == 'mixed':
            questions = self.english_questions + self.deutsch_questions
        else:
            questions = self.english_questions
        
        if not questions:
            return None
        
        available_questions = questions
        if exclude_ids:
            available_questions = [q for q in questions if q.get('id') not in exclude_ids]
        
        if not available_questions:
            available_questions = questions
        
        return random.choice(available_questions)
    
    def get_question_by_id(self, question_id: str, language: str) -> Optional[Dict[str, Any]]:
        if language == 'deutsch':
            questions = self.deutsch_questions
        else:
            questions = self.english_questions
        
        for question in questions:
            if question.get('id') == question_id:
                return question
        
        for question in self.english_questions + self.deutsch_questions:
            if question.get('id') == question_id:
                return question
        
        return None
import asyncio
import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Set

from telegram import Update
from telegram.ext import ContextTypes

from config import QUESTION_DELAY_SECONDS
from database.db_manager import DatabaseManager
from utils.question_loader import QuestionLoader

logger = logging.getLogger(__name__)


class QuizHandler:
    def __init__(self, db_manager: DatabaseManager, question_loader: QuestionLoader):
        self.db = db_manager
        self.question_loader = question_loader
        self.active_questions: Dict[int, Dict] = {}
        self.question_start_times: Dict[int, datetime] = {}
        self.awaiting_answer: Set[int] = set()
    
    async def restore_sessions(self):
        """Restore active sessions from database on bot restart"""
        sessions = await self.db.get_all_active_sessions()
        for session in sessions:
            user_id = session['user_telegram_id']
            question_id = session.get('current_question_id')
            language = session.get('language', 'english')
            
            if question_id:
                # Look up the actual question by ID
                question = self.question_loader.get_question_by_id(question_id, language)
                if question:
                    self.active_questions[user_id] = question
                    if session['question_start_time']:
                        self.question_start_times[user_id] = datetime.fromisoformat(session['question_start_time'])
                    if session['awaiting_answer']:
                        self.awaiting_answer.add(user_id)
                else:
                    logger.warning(f"Could not find question {question_id} for user {user_id}")
        
        if sessions:
            logger.info(f"Restored {len(sessions)} active sessions")
    
    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await self.db.get_or_create_user(user.id, user.username)
        
        # Simple text-based language selection
        await update.message.reply_text(
            f"Welcome to the Driving Theory Bot! 🚗\n\n"
            f"Please choose your preferred language:\n"
            f"1. English\n"
            f"2. Deutsch\n"
            f"3. Mixed\n\n"
            f"Reply with 1, 2, or 3"
        )
        context.user_data['awaiting_language'] = True
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        # Handle language selection
        if context.user_data.get('awaiting_language'):
            await self.handle_language_selection(update, context, text)
            return
        
        # Handle quiz answers
        if user_id in self.awaiting_answer:
            await self.handle_answer(update, context, text)
            return
        
        # Check if user has an active session in database
        session = await self.db.get_user_session(user_id)
        if session and session['awaiting_answer']:
            # Restore session by looking up the question
            question_id = session.get('current_question_id')
            language = session.get('language', 'english')
            
            if question_id:
                question = self.question_loader.get_question_by_id(question_id, language)
                if question:
                    self.active_questions[user_id] = question
                    self.awaiting_answer.add(user_id)
                    context.user_data['language'] = language
                    
                    await update.message.reply_text(
                        "📚 Resuming your previous session...\n"
                        "Please answer the question above or type 'skip' to skip it."
                    )
                    await self.handle_answer(update, context, text)
                    return
        
        # If not awaiting anything, remind user of commands
        await update.message.reply_text(
            "Available commands:\n"
            "/start - Begin a new quiz session\n"
            "/stats - View statistics & current question\n"
            "/resend - Resend current question\n"
            "/skip - Skip to next question"
        )
    
    async def handle_language_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        user_id = update.effective_user.id
        
        language_map = {
            '1': 'english',
            'english': 'english',
            'e': 'english',
            '2': 'deutsch',
            'deutsch': 'deutsch',
            'german': 'deutsch',
            'd': 'deutsch',
            '3': 'mixed',
            'mixed': 'mixed',
            'm': 'mixed'
        }
        
        language = language_map.get(text.lower())
        
        if not language:
            await update.message.reply_text(
                "Please reply with 1 (English), 2 (Deutsch), or 3 (Mixed)"
            )
            return
        
        await self.db.update_user_language(user_id, language)
        context.user_data['language'] = language
        context.user_data['awaiting_language'] = False
        
        await update.message.reply_text(f"Language set to: {language.capitalize()}")
        await self.send_next_question(update.message, user_id, language)
    
    async def _get_next_question(self, user_id: int, language: str):
        """Get the next question without displaying it"""
        # Check for spaced repetition review
        review_question_id = await self.db.get_next_question_for_review(user_id, language)
        
        if review_question_id:
            question = self.question_loader.get_question_by_id(review_question_id, language)
            if question:
                question['is_review'] = True
                return question
        
        # Get random question
        attempted_questions = await self.db.get_attempted_questions(user_id, language)
        question = self.question_loader.get_random_question(language, attempted_questions)
        if question:
            question['is_review'] = False
        return question
    
    async def send_next_question(self, message, user_id: int, language: str):
        # Check for spaced repetition review
        review_question_id = await self.db.get_next_question_for_review(user_id, language)
        
        if review_question_id:
            question = self.question_loader.get_question_by_id(review_question_id, language)
            if question:
                await message.reply_text("📚 Time for review! This question is due for spaced repetition.")
        else:
            attempted_questions = await self.db.get_attempted_questions(user_id, language)
            question = self.question_loader.get_random_question(language, attempted_questions)
        
        if not question:
            await message.reply_text("No questions available. Please check your question files.")
            return
        
        self.active_questions[user_id] = question
        self.question_start_times[user_id] = datetime.now()
        self.awaiting_answer.add(user_id)
        
        # Save session to database (only the question ID)
        await self.db.save_user_session(
            user_id,
            question.get('id', ''),
            language,
            datetime.now(),
            True
        )
        
        # Check for donation reminder
        user_stats = await self.db.get_user_statistics(user_id)
        total_attempts = user_stats.get('total_attempts', 0)
        
        if total_attempts > 0 and total_attempts % 100 == 0:
            await message.reply_text(
                "🎉 Congratulations on answering 100 questions!\n\n"
                "If you're enjoying this bot, please consider supporting future projects:\n"
                "https://paypal.me/yowmamasita"
            )
        
        await self._display_question(message, question)
    
    async def _display_question(self, message, question: Dict):
        # Build header with metadata
        header_parts = []
        
        if question.get('theme_name'):
            header_parts.append(f"📚 {question['theme_name']}")
        
        if question.get('chapter_name'):
            header_parts.append(f"📖 {question['chapter_name']}")
        
        if question.get('id'):
            header_parts.append(f"🔢 {question['id']}")
        
        if question.get('points'):
            header_parts.append(f"⭐ {question['points']}")
        
        if question.get('is_review'):
            header_parts.append("🔄 Review Question")
        
        header = "\n".join(header_parts)
        
        question_text = f"❓ {question.get('question', 'No question text')}"
        
        if header:
            full_text = f"{header}\n\n{question_text}"
        else:
            full_text = question_text
        
        # Handle media (both video and image if available)
        base_dir = Path(__file__).parent.parent.parent.parent
        media_sent = False
        
        # Check if we have both video and image
        has_video = question.get('video') and (base_dir / question['video']).exists()
        has_image = question.get('image') and (base_dir / question['image']).exists()
        
        # Debug logging
        if question.get('video'):
            logger.info(f"Question has video: {question['video']}")
            logger.info(f"Video path: {base_dir / question['video']}")
            logger.info(f"Video exists: {(base_dir / question['video']).exists()}")
        if question.get('image'):
            logger.info(f"Question has image: {question['image']}")
            logger.info(f"Image exists: {(base_dir / question['image']).exists()}")
        
        if has_video and has_image:
            # Send both: video first with caption, then image without caption
            video_path = base_dir / question['video']
            image_path = base_dir / question['image']
            
            logger.info(f"Sending both video and image for question {question.get('id')}")
            
            try:
                # Send video with full caption
                with open(video_path, 'rb') as vid:
                    await message.reply_video(
                        video=vid,
                        caption=full_text + "\n\n🎬 Video shows the scenario",
                        supports_streaming=True
                    )
                    logger.info("Video sent successfully")
                
                # Send image as supplementary (e.g., initial position)
                with open(image_path, 'rb') as img:
                    await message.reply_photo(
                        photo=img,
                        caption="📸 Initial situation / Reference image"
                    )
                    logger.info("Image sent successfully")
                media_sent = True
            except Exception as e:
                logger.error(f"Error sending media: {e}")
                logger.error(f"Video path was: {video_path}")
                logger.error(f"Image path was: {image_path}")
                await message.reply_text(full_text + f"\n\n[Media files available but failed to send]")
                media_sent = True
        
        elif has_video:
            # Only video available
            video_path = base_dir / question['video']
            try:
                with open(video_path, 'rb') as vid:
                    await message.reply_video(
                        video=vid,
                        caption=full_text,
                        supports_streaming=True
                    )
                media_sent = True
            except Exception as e:
                logger.error(f"Error sending video: {e}")
                await message.reply_text(full_text + f"\n\n[Video: {question['video']}]")
                media_sent = True
        
        elif has_image:
            # Only image available
            image_path = base_dir / question['image']
            try:
                with open(image_path, 'rb') as img:
                    await message.reply_photo(
                        photo=img,
                        caption=full_text
                    )
                media_sent = True
            except Exception as e:
                logger.error(f"Error sending image: {e}")
                await message.reply_text(full_text + f"\n\n[Image: {question['image']}]")
                media_sent = True
        
        # If no media was sent, just send text
        if not media_sent:
            await message.reply_text(full_text)
        
        # Display options or input prompt based on question type
        options = question.get('options', [])
        
        if options:
            # Multiple choice question
            options_text = "\n"
            for i, option in enumerate(options):
                letter = chr(65 + i)  # A, B, C, etc.
                options_text += f"{letter}. {option}\n"
            
            options_text += "\n📝 Reply with your answer(s) (e.g., A or AB or A,B or A B)"
            options_text += "\n⏭️ Type 'skip' to skip this question"
            
            await message.reply_text(options_text)
        else:
            # Fill-in-the-blank question
            await message.reply_text(
                "✍️ Type your answer directly (number or text)\n"
                "⏭️ Type 'skip' to skip this question"
            )
    
    def parse_answer_text(self, text: str) -> List[int]:
        """Parse user input to extract answer indices"""
        text = text.upper().strip()
        
        # Check for skip
        if text.lower() == 'skip':
            return None
        
        # Remove all non-letter characters
        letters = re.findall(r'[A-Z]', text)
        
        # Convert letters to indices (A=0, B=1, etc.)
        indices = []
        for letter in letters:
            index = ord(letter) - ord('A')
            if index >= 0 and index < 26:  # Valid letter range
                indices.append(index)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_indices = []
        for idx in indices:
            if idx not in seen:
                seen.add(idx)
                unique_indices.append(idx)
        
        return unique_indices
    
    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        user_id = update.effective_user.id
        
        # Remove user from awaiting set
        if user_id in self.awaiting_answer:
            self.awaiting_answer.remove(user_id)
        
        question = self.active_questions.get(user_id)
        if not question:
            await update.message.reply_text("No active question found. Use /start to begin.")
            return
        
        # Handle skip
        if text.lower().strip() == 'skip':
            await update.message.reply_text("Question skipped. Loading next question...")
            language = context.user_data.get('language', 'english')
            await self.send_next_question(update.message, user_id, language)
            return
        
        # Check if this is a multiple choice or fill-in-the-blank question
        options = question.get('options', [])
        
        if options:
            # Multiple choice question - parse letters
            selected_indices = self.parse_answer_text(text)
            
            if selected_indices is None:
                await update.message.reply_text("Question skipped. Loading next question...")
                language = context.user_data.get('language', 'english')
                await self.send_next_question(update.message, user_id, language)
                return
            
            # Validate answer indices
            num_options = len(options)
            selected_indices = [idx for idx in selected_indices if idx < num_options]
            
            if not selected_indices:
                await update.message.reply_text(
                    "Invalid answer. Please reply with letter(s) like A, BC, or A,B,C\n"
                    "Try again or type 'skip' to skip this question."
                )
                self.awaiting_answer.add(user_id)  # Re-add to awaiting
                return
            
            await self._process_multiple_choice_answer(update, user_id, selected_indices, question, context)
        else:
            # Fill-in-the-blank question - process direct text answer
            user_answer = text.strip()
            await self._process_text_answer(update, user_id, user_answer, question, context)
    
    async def _process_multiple_choice_answer(self, update, user_id: int, selected_indices: list, question: Dict, context: ContextTypes.DEFAULT_TYPE):
        # Get correct answers
        correct_answers = question.get('correctAnswers', question.get('correctAnswer', []))
        if not isinstance(correct_answers, list):
            correct_answers = [correct_answers]
        
        # Find correct indices
        correct_indices = []
        options = question.get('options', [])
        for i, option in enumerate(options):
            if option in correct_answers:
                correct_indices.append(i)
        
        # Check if answer is correct
        is_correct = set(selected_indices) == set(correct_indices)
        
        # Calculate time taken
        time_taken = None
        if user_id in self.question_start_times:
            time_taken = int((datetime.now() - self.question_start_times[user_id]).total_seconds())
            del self.question_start_times[user_id]
        
        # Record attempt
        language = context.user_data.get('language', 'english')
        question_id = question.get('id', str(random.randint(1000, 9999)))
        
        await self.db.record_question_attempt(
            user_id, question_id, language, is_correct, time_taken
        )
        
        await self.db.update_spaced_repetition(
            user_id, question_id, language, is_correct
        )
        
        # Prepare response
        if is_correct:
            response = "✅ Correct! Well done!"
            # Show explanation even for correct answers if available
            if question.get('explanation'):
                response += f"\n\n💡 {question['explanation']}"
        else:
            correct_letters = [chr(65 + i) for i in correct_indices]
            selected_letters = [chr(65 + i) for i in selected_indices]
            response = f"❌ Incorrect.\n"
            response += f"Your answer: {', '.join(selected_letters)}\n"
            response += f"Correct answer: {', '.join(correct_letters)}"
            
            if question.get('explanation'):
                response += f"\n\n💡 {question['explanation']}"
        
        # Add statistics
        stats = await self.db.get_user_statistics(user_id)
        accuracy = stats.get('accuracy_percentage', 0) or 0
        total = stats.get('total_attempts', 0)
        
        response += f"\n\n📊 Your stats: {total} questions, {accuracy:.1f}% accuracy"
        
        await update.message.reply_text(response)
        
        # Clean up current question
        if user_id in self.active_questions:
            del self.active_questions[user_id]
        
        # Clear current session
        await self.db.clear_user_session(user_id)
        
        # Pick the next question NOW (before waiting)
        next_question = await self._get_next_question(user_id, language)
        
        if next_question:
            # Store the next question immediately
            self.active_questions[user_id] = next_question
            self.question_start_times[user_id] = datetime.now()
            self.awaiting_answer.add(user_id)
            
            # Save session with the next question ID only
            await self.db.save_user_session(
                user_id,
                next_question.get('id', ''),
                language,
                datetime.now(),
                True
            )
            
            # NOW wait before sending next question
            await update.message.reply_text(f"⏳ Next question in {QUESTION_DELAY_SECONDS} seconds...")
            await asyncio.sleep(QUESTION_DELAY_SECONDS)
            
            # Display the already-selected question
            await self._display_question(update.message, next_question)
        else:
            await update.message.reply_text("No more questions available.")
    
    async def _process_text_answer(self, update, user_id: int, user_answer: str, question: Dict, context: ContextTypes.DEFAULT_TYPE):
        """Process fill-in-the-blank text answers"""
        # Get correct answer(s)
        correct_answers = question.get('correctAnswers', question.get('correctAnswer', []))
        if not isinstance(correct_answers, list):
            correct_answers = [correct_answers]
        
        # For fill-in-the-blank, the answer is usually a number or short text
        # Normalize the user's answer (remove spaces, handle commas as decimal points)
        normalized_user = user_answer.replace(' ', '').replace(',', '.')
        
        # Check if answer is correct
        is_correct = False
        correct_answer_text = ""
        
        for ca in correct_answers:
            # The correct answer might be in the text field or as a string
            if isinstance(ca, str):
                correct_answer_text = ca
            else:
                correct_answer_text = ca  # Already normalized in question loader
            
            # Normalize correct answer
            normalized_correct = str(correct_answer_text).replace(' ', '').replace(',', '.')
            
            # Case-insensitive comparison
            if normalized_user.lower() == normalized_correct.lower():
                is_correct = True
                break
        
        # Calculate time taken
        time_taken = None
        if user_id in self.question_start_times:
            time_taken = int((datetime.now() - self.question_start_times[user_id]).total_seconds())
            del self.question_start_times[user_id]
        
        # Record attempt
        language = context.user_data.get('language', 'english')
        question_id = question.get('id', str(random.randint(1000, 9999)))
        
        await self.db.record_question_attempt(
            user_id, question_id, language, is_correct, time_taken
        )
        
        await self.db.update_spaced_repetition(
            user_id, question_id, language, is_correct
        )
        
        # Prepare response
        if is_correct:
            response = "✅ Correct! Well done!"
            if question.get('explanation'):
                response += f"\n\n💡 {question['explanation']}"
        else:
            response = f"❌ Incorrect.\n"
            response += f"Your answer: {user_answer}\n"
            response += f"Correct answer: {correct_answer_text}"
            
            if question.get('explanation'):
                response += f"\n\n💡 {question['explanation']}"
        
        # Add statistics
        stats = await self.db.get_user_statistics(user_id)
        accuracy = stats.get('accuracy_percentage', 0) or 0
        total = stats.get('total_attempts', 0)
        
        response += f"\n\n📊 Your stats: {total} questions, {accuracy:.1f}% accuracy"
        
        await update.message.reply_text(response)
        
        # Clean up current question
        if user_id in self.active_questions:
            del self.active_questions[user_id]
        
        # Clear current session
        await self.db.clear_user_session(user_id)
        
        # Pick the next question NOW (before waiting)
        next_question = await self._get_next_question(user_id, language)
        
        if next_question:
            # Store the next question immediately
            self.active_questions[user_id] = next_question
            self.question_start_times[user_id] = datetime.now()
            self.awaiting_answer.add(user_id)
            
            # Save session with the next question ID only
            await self.db.save_user_session(
                user_id,
                next_question.get('id', ''),
                language,
                datetime.now(),
                True
            )
            
            # NOW wait before sending next question
            await update.message.reply_text(f"⏳ Next question in {QUESTION_DELAY_SECONDS} seconds...")
            await asyncio.sleep(QUESTION_DELAY_SECONDS)
            
            # Display the already-selected question
            await self._display_question(update.message, next_question)
        else:
            await update.message.reply_text("No more questions available.")
    
    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user statistics and current question status"""
        user_id = update.effective_user.id
        
        # Build response with both stats and status
        response_parts = ["📊 Your Statistics:\n"]
        
        # Get user statistics
        stats = await self.db.get_user_statistics(user_id)
        total = stats.get('total_attempts', 0)
        correct = stats.get('correct_answers', 0) or 0
        accuracy = stats.get('accuracy_percentage', 0) or 0
        
        response_parts.append(f"Total Questions: {total}")
        response_parts.append(f"Correct Answers: {int(correct)}")
        response_parts.append(f"Accuracy: {accuracy:.1f}%")
        
        # Check for current question
        question = self.active_questions.get(user_id)
        if not question:
            # Try to get from database
            session = await self.db.get_user_session(user_id)
            if session:
                question_id = session.get('current_question_id')
                language = session.get('language', 'english')
                if question_id:
                    question = self.question_loader.get_question_by_id(question_id, language)
        
        # Add current question status if exists
        if question:
            response_parts.append("\n📋 Current Question:\n")
            
            if question.get('theme_name'):
                response_parts.append(f"📚 Theme: {question['theme_name']}")
            
            if question.get('chapter_name'):
                response_parts.append(f"📖 Chapter: {question['chapter_name']}")
            
            if question.get('id'):
                response_parts.append(f"🔢 ID: {question['id']}")
            
            if question.get('points'):
                response_parts.append(f"⭐ Points: {question['points']}")
            
            if question.get('is_review'):
                response_parts.append("🔄 Review question")
            
            # Add time info if available
            if user_id in self.question_start_times:
                time_elapsed = int((datetime.now() - self.question_start_times[user_id]).total_seconds())
                response_parts.append(f"⏱️ Time elapsed: {time_elapsed}s")
            
            if user_id in self.awaiting_answer:
                response_parts.append("\n✍️ Awaiting your answer...")
        else:
            response_parts.append("\n📋 No active question")
        
        await update.message.reply_text("\n".join(response_parts))
    
    async def handle_resend(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resend the current question"""
        user_id = update.effective_user.id
        
        # Check if user has an active question
        question = self.active_questions.get(user_id)
        
        if not question:
            # Check database for saved session
            session = await self.db.get_user_session(user_id)
            if session:
                question_id = session.get('current_question_id')
                language = session.get('language', 'english')
                if question_id:
                    question = self.question_loader.get_question_by_id(question_id, language)
                    if question:
                        # Restore to active questions
                        self.active_questions[user_id] = question
                        self.awaiting_answer.add(user_id)
                        context.user_data['language'] = language
        
        if question:
            # Don't send the "resending" message - just display the question with media
            await self._display_question(update.message, question)
        else:
            await update.message.reply_text(
                "No active question to resend. Use /start to begin a new session."
            )
    
    async def handle_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Skip the current question"""
        user_id = update.effective_user.id
        
        # Check if user has an active question
        if user_id not in self.active_questions:
            # Try to restore from database
            session = await self.db.get_user_session(user_id)
            if session:
                question_id = session.get('current_question_id')
                language = session.get('language', 'english')
                if question_id:
                    question = self.question_loader.get_question_by_id(question_id, language)
                    if question:
                        self.active_questions[user_id] = question
                        context.user_data['language'] = language
                    else:
                        await update.message.reply_text("No active question to skip. Use /start to begin.")
                        return
                else:
                    await update.message.reply_text("No active question to skip. Use /start to begin.")
                    return
            else:
                await update.message.reply_text("No active question to skip. Use /start to begin.")
                return
        
        # Remove from awaiting if present
        if user_id in self.awaiting_answer:
            self.awaiting_answer.remove(user_id)
        
        await update.message.reply_text("⏭️ Question skipped. Loading next question...")
        
        language = context.user_data.get('language', 'english')
        await self.send_next_question(update.message, user_id, language)
    

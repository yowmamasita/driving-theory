# Driving Theory Bot

A Telegram bot for practicing driving theory questions with spaced repetition learning.

## Features

- Support for English, German (Deutsch), and mixed language questions
- Single and multiple-choice questions
- Image support for questions with diagrams
- Spaced repetition algorithm for optimal learning
- Progress tracking and statistics
- SQLite database for persistent storage
- Donation reminder every 100 questions

## Setup

1. Create a Telegram bot via [@BotFather](https://t.me/botfather) and get your bot token

2. Copy the environment file and add your token:
```bash
cp .env.example .env
# Edit .env and add your TELEGRAM_BOT_TOKEN
```

3. Place your question JSON files in the parent directory:
   - `driving_theory_questions.json` (English questions)
   - `driving_theory_questions_de.json` (German questions)

4. Run the bot:
```bash
./run.sh
```

Or directly with uv:
```bash
cd src && uv run python main.py
```

## Question File Format

Questions should be in JSON format:

```json
{
  "questions": [
    {
      "id": "q1",
      "question": "What is the speed limit in urban areas?",
      "options": ["30 km/h", "50 km/h", "70 km/h", "100 km/h"],
      "correctAnswer": "50 km/h",
      "explanation": "The default speed limit in urban areas is 50 km/h",
      "image": "images/urban_speed.png"
    },
    {
      "id": "q2",
      "question": "Which documents must you carry while driving?",
      "options": ["Driver's license", "Vehicle registration", "Insurance proof", "Passport"],
      "correctAnswers": ["Driver's license", "Vehicle registration"],
      "explanation": "You must carry your license and registration at all times"
    }
  ]
}
```

## Bot Commands

- `/start` - Start the bot and select language
- `/stats` - View your statistics and current question details
- `/resend` - Resend the current question
- `/skip` - Skip the current question and get a new one

## Architecture

The bot follows KISS, DRY, YAGNI, and SOLID principles:

- **Database Layer** (`database/`): SQLite management and models
- **Handlers** (`handlers/`): Telegram bot interaction logic
- **Utils** (`utils/`): Question loading and spaced repetition algorithm
- **Main** (`main.py`): Bot initialization and configuration

## Dependencies

Managed with [uv](https://github.com/astral-sh/uv):
- python-telegram-bot: Telegram Bot API wrapper
- aiosqlite: Async SQLite database
- python-dotenv: Environment variable management

## Support

If you find this bot helpful, consider supporting future projects:
https://paypal.me/yowmamasita
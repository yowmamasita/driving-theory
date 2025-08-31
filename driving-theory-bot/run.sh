#!/bin/bash

echo "Starting Driving Theory Bot..."

if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    echo "Please create a .env file with your TELEGRAM_BOT_TOKEN"
    echo "You can copy .env.example as a template"
    exit 1
fi

cd src && uv run python main.py
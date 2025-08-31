#!/bin/bash

echo "Starting Driving Theory Bot..."
echo "Optimized for thousands of concurrent users"
echo ""

if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    echo "Please create a .env file with your TELEGRAM_BOT_TOKEN"
    echo "You can copy .env.example as a template"
    exit 1
fi

echo "Configuration:"
echo "- Database pool: 20 connections"
echo "- Rate limiting: 10 requests/minute per user"
echo "- Memory caching: Enabled"
echo "- Concurrent processing: Enabled"
echo ""

cd src && uv run python main.py
"""
Production configuration for handling thousands of concurrent users.
"""

# Database Configuration
DATABASE = {
    'path': 'driving_theory_bot.db',
    'pool_size': 20,  # Number of concurrent database connections
    'batch_size': 100,  # Batch size for writes
    'batch_interval': 2,  # Seconds between batch writes
    'cache_size': 10000,  # SQLite cache size
}

# Rate Limiting Configuration
RATE_LIMIT = {
    'requests_per_minute': 10,  # Max requests per user per minute
    'burst_capacity': 15,  # Max burst requests
    'cleanup_interval': 300,  # Cleanup old buckets every 5 minutes
}

# Caching Configuration
CACHE = {
    'user_cache_size': 10000,  # Number of users to cache in memory
    'question_cache_size': 128,  # LRU cache size for questions
    'session_timeout': 86400,  # 24 hours in seconds
}

# Telegram Bot Configuration
TELEGRAM = {
    'concurrent_updates': True,  # Process updates concurrently
    'pool_timeout': 60.0,  # Connection pool timeout
    'connection_pool_size': 20,  # HTTP connection pool size
    'read_timeout': 30.0,  # Read timeout for API calls
    'write_timeout': 30.0,  # Write timeout for API calls
    'connect_timeout': 30.0,  # Connect timeout for API calls
}

# Performance Tuning
PERFORMANCE = {
    'use_uvloop': True,  # Use uvloop for better async performance
    'max_workers': 4,  # Thread pool executor workers
    'queue_size': 1000,  # Max pending requests per user
    'cleanup_interval': 3600,  # Clean old data every hour
}

# Monitoring Configuration
MONITORING = {
    'log_level': 'INFO',
    'metrics_enabled': True,
    'health_check_interval': 60,  # Seconds
    'alert_threshold': {
        'response_time': 5.0,  # Alert if response > 5 seconds
        'error_rate': 0.01,  # Alert if error rate > 1%
        'queue_size': 500,  # Alert if queue > 500 requests
    }
}

# Scaling Recommendations
"""
For handling different user loads:

100-500 concurrent users:
- Database pool: 10 connections
- Rate limit: 15 req/min
- Cache: 5000 users

500-2000 concurrent users:
- Database pool: 20 connections  
- Rate limit: 10 req/min
- Cache: 10000 users

2000-5000 concurrent users:
- Database pool: 30 connections
- Rate limit: 8 req/min
- Cache: 20000 users
- Consider sharding database

5000+ concurrent users:
- Use PostgreSQL instead of SQLite
- Implement Redis for caching
- Deploy multiple bot instances with load balancer
- Use message queue (RabbitMQ/Kafka) for async processing
"""
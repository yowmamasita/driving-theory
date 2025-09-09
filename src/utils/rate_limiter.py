import asyncio
import time
from collections import defaultdict, deque
from typing import Optional, Any
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for handling thousands of concurrent users.
    Prevents abuse while ensuring fair access to bot resources.
    """
    
    def __init__(
        self,
        rate: int = 10,  # Requests per window
        window: int = 60,  # Time window in seconds
        burst: int = 15   # Max burst capacity
    ):
        self.rate = rate
        self.window = window
        self.burst = burst
        self._buckets = defaultdict(lambda: {'tokens': rate, 'last_update': time.time()})
        self._lock = asyncio.Lock()
        self._request_queue = defaultdict(deque)
        self._cleanup_task = None
    
    async def start(self):
        """Start the cleanup task"""
        self._cleanup_task = asyncio.create_task(self._cleanup_old_buckets())
    
    async def stop(self):
        """Stop the cleanup task"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def check_rate_limit(self, user_id: int) -> bool:
        """Check if user is within rate limits"""
        async with self._lock:
            bucket = self._buckets[user_id]
            now = time.time()
            
            # Refill tokens based on time passed
            time_passed = now - bucket['last_update']
            tokens_to_add = (time_passed / self.window) * self.rate
            bucket['tokens'] = min(self.burst, bucket['tokens'] + tokens_to_add)
            bucket['last_update'] = now
            
            if bucket['tokens'] >= 1:
                bucket['tokens'] -= 1
                return True
            
            return False
    
    async def wait_if_limited(self, user_id: int, timeout: float = 30.0) -> bool:
        """Wait until rate limit allows request or timeout"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if await self.check_rate_limit(user_id):
                return True
            
            # Calculate wait time until next token
            async with self._lock:
                bucket = self._buckets[user_id]
                tokens_needed = 1 - bucket['tokens']
                wait_time = (tokens_needed * self.window) / self.rate
                wait_time = min(wait_time, 1.0)  # Cap at 1 second checks
            
            await asyncio.sleep(wait_time)
        
        return False
    
    async def _cleanup_old_buckets(self):
        """Clean up old buckets to prevent memory leak"""
        while True:
            try:
                await asyncio.sleep(300)  # Clean every 5 minutes
                
                async with self._lock:
                    now = time.time()
                    cutoff = now - (self.window * 2)
                    
                    to_remove = [
                        user_id for user_id, bucket in self._buckets.items()
                        if bucket['last_update'] < cutoff
                    ]
                    
                    for user_id in to_remove:
                        del self._buckets[user_id]
                    
                    if to_remove:
                        logger.info(f"Cleaned up {len(to_remove)} old rate limit buckets")
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in rate limiter cleanup: {e}")
    
    def get_remaining_tokens(self, user_id: int) -> float:
        """Get remaining tokens for a user"""
        bucket = self._buckets.get(user_id)
        if not bucket:
            return self.rate
        
        now = time.time()
        time_passed = now - bucket['last_update']
        tokens_to_add = (time_passed / self.window) * self.rate
        return min(self.burst, bucket['tokens'] + tokens_to_add)


class UserRequestQueue:
    """
    Queue system for handling user requests with priority.
    Ensures fair processing when system is under load.
    """
    
    def __init__(self, max_queue_size: int = 1000):
        self.max_queue_size = max_queue_size
        self._queues = defaultdict(lambda: asyncio.Queue(maxsize=10))
        self._processing = set()
        self._lock = asyncio.Lock()
    
    async def add_request(self, user_id: int, request: Any) -> bool:
        """Add request to user's queue"""
        queue = self._queues[user_id]
        
        if queue.full():
            return False  # Reject if user's queue is full
        
        await queue.put(request)
        return True
    
    async def get_request(self, user_id: int) -> Optional[Any]:
        """Get next request for user"""
        queue = self._queues[user_id]
        
        if queue.empty():
            return None
        
        return await queue.get()
    
    async def process_user_requests(self, user_id: int, processor):
        """Process all requests for a user"""
        async with self._lock:
            if user_id in self._processing:
                return  # Already processing this user
            self._processing.add(user_id)
        
        try:
            queue = self._queues[user_id]
            while not queue.empty():
                request = await queue.get()
                await processor(request)
        finally:
            async with self._lock:
                self._processing.discard(user_id)
                
                # Clean up empty queue
                if queue.empty():
                    del self._queues[user_id]
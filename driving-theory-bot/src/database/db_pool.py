import asyncio
import aiosqlite
from contextlib import asynccontextmanager
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class DatabasePool:
    """
    Database connection pool for handling concurrent connections efficiently.
    Uses multiple connections to handle thousands of concurrent users.
    """
    
    def __init__(self, db_path: str = "driving_theory_bot.db", pool_size: int = 10):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool = []
        self._used_connections = set()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(pool_size)
        self._initialized = False
    
    async def initialize(self):
        """Initialize the connection pool"""
        if self._initialized:
            return
            
        async with self._lock:
            if self._initialized:
                return
                
            # Create initial connections
            for _ in range(min(3, self.pool_size)):  # Start with 3 connections
                conn = await self._create_connection()
                self._pool.append(conn)
            
            self._initialized = True
            logger.info(f"Database pool initialized with {len(self._pool)} connections")
    
    async def _create_connection(self) -> aiosqlite.Connection:
        """Create a new database connection with optimized settings"""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        
        # Optimize for concurrent access
        await conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for better concurrency
        await conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes
        await conn.execute("PRAGMA cache_size=10000")  # Larger cache for better performance
        await conn.execute("PRAGMA temp_store=MEMORY")  # Use memory for temp tables
        await conn.execute("PRAGMA mmap_size=30000000000")  # Memory-mapped I/O
        
        return conn
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool"""
        await self._semaphore.acquire()
        conn = None
        
        try:
            async with self._lock:
                if self._pool:
                    conn = self._pool.pop()
                elif len(self._used_connections) < self.pool_size:
                    conn = await self._create_connection()
                else:
                    # Wait for a connection to be released
                    while not self._pool:
                        await asyncio.sleep(0.01)
                    conn = self._pool.pop()
                
                self._used_connections.add(conn)
            
            yield conn
            
        finally:
            if conn:
                async with self._lock:
                    self._used_connections.discard(conn)
                    self._pool.append(conn)
            self._semaphore.release()
    
    async def close(self):
        """Close all connections in the pool"""
        async with self._lock:
            for conn in self._pool:
                await conn.close()
            for conn in self._used_connections:
                await conn.close()
            
            self._pool.clear()
            self._used_connections.clear()
            self._initialized = False
    
    async def execute(self, query: str, params: tuple = ()):
        """Execute a query using a connection from the pool"""
        async with self.acquire() as conn:
            await conn.execute(query, params)
            await conn.commit()
    
    async def executemany(self, query: str, params: list):
        """Execute many queries using a connection from the pool"""
        async with self.acquire() as conn:
            await conn.executemany(query, params)
            await conn.commit()
    
    async def fetchone(self, query: str, params: tuple = ()):
        """Fetch one result using a connection from the pool"""
        async with self.acquire() as conn:
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchone()
    
    async def fetchall(self, query: str, params: tuple = ()):
        """Fetch all results using a connection from the pool"""
        async with self.acquire() as conn:
            async with conn.execute(query, params) as cursor:
                return await cursor.fetchall()
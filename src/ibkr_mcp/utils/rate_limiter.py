"""
Token bucket rate limiter for IBKR API requests.
"""

import asyncio
import time
from typing import Optional

from loguru import logger


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter to prevent exceeding IBKR API limits.

    IBKR has a limit of ~50 messages/second. This limiter ensures
    we stay well under that limit to avoid disconnections.
    """

    def __init__(
        self,
        rate: float = 45.0,  # tokens per second (conservative)
        capacity: Optional[float] = None,  # max tokens (defaults to rate)
    ):
        """
        Initialize rate limiter.

        Args:
            rate: Tokens added per second
            capacity: Maximum token capacity (burst size)
        """
        self.rate = rate
        self.capacity = capacity or rate
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> float:
        """
        Acquire tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            Time waited in seconds
        """
        async with self._lock:
            wait_time = 0.0

            # Refill tokens based on time elapsed
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now

            # Wait if not enough tokens
            if self.tokens < tokens:
                deficit = tokens - self.tokens
                wait_time = deficit / self.rate

                if wait_time > 0:
                    logger.debug(f"Rate limiter: waiting {wait_time:.3f}s")
                    await asyncio.sleep(wait_time)

                    # Refill after waiting
                    now = time.monotonic()
                    elapsed = now - self.last_update
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                    self.last_update = now

            # Consume tokens
            self.tokens -= tokens

            return wait_time

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """
        Try to acquire tokens without waiting.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens were acquired, False otherwise
        """
        # Refill tokens
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def available_tokens(self) -> float:
        """Get current available tokens."""
        now = time.monotonic()
        elapsed = now - self.last_update
        return min(self.capacity, self.tokens + elapsed * self.rate)

    def reset(self) -> None:
        """Reset rate limiter to full capacity."""
        self.tokens = self.capacity
        self.last_update = time.monotonic()

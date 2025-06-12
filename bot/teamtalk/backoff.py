import random
import time


class Backoff:
    def __init__(self, base: int = 1, exponent: float = 2, max_value: float = 60, max_tries: int = None):
        self.base = base
        self.exponent = exponent
        self.max_value = max_value
        self.max_tries = max_tries
        self._attempts = 0

    def delay(self) -> float | None:
        '''Calculates the next delay duration. Returns None if max_tries is exceeded.'''
        if self.max_tries is not None and self._attempts >= self.max_tries:
            return None

        calculated_delay = self.base * (self.exponent ** self._attempts)

        # Apply jitter (e.g., up to 50% of current calculated delay)
        jitter = random.uniform(0, calculated_delay * 0.5)

        actual_delay = min(calculated_delay + jitter, self.max_value)

        self._attempts += 1
        return actual_delay

    def reset(self):
        '''Resets the attempt counter.'''
        self._attempts = 0

    @property
    def attempts(self) -> int:
        '''Returns the current number of attempts.'''
        return self._attempts

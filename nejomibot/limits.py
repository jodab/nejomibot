"""How often: at most so many in a period, as for the weather's calls about
places named (weather.py) and each person's commands (commands.py)."""

import time
from collections import deque
from collections.abc import Callable


class Window:
    """When something happened lately, so that it happens at most so many
    times in a period."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.times: deque[float] = deque()

    def wait(self, most: int, period: float) -> float:
        """Seconds until one more fits, with at most most in any period
        seconds; 0 if one fits now."""
        now = self.clock()
        while self.times and now - self.times[0] >= period:
            self.times.popleft()
        if len(self.times) < most:
            return 0.0
        return self.times[-most] + period - now

    def take(self) -> None:
        """One more, now."""
        self.times.append(self.clock())

    def clear(self) -> None:
        self.times.clear()

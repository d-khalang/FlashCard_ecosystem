"""Types shared across use cases."""
from typing import Union

# Telegram user id; callers still pass both forms (see refactor doc, #9).
UserId = Union[str, int]

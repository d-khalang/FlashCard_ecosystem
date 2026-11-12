"""The app's clock can run ahead for development; the real clock and production code stay put."""
import re
from datetime import timedelta
from pathlib import Path

import pytest

from flashcard.utils import time as clock

SRC = Path(__file__).resolve().parents[3] / "src" / "flashcard"


@pytest.fixture(autouse=True)
def restore_clock(monkeypatch):
    monkeypatch.setattr(clock, "_clock_offset", timedelta(0))


def test_shifting_moves_the_app_clock_but_not_the_real_one():
    before_app, before_real = clock.now_utc(), clock.real_now_utc()

    clock.shift_clock(timedelta(days=2))

    assert clock.now_utc() - before_app >= timedelta(days=2)
    assert clock.real_now_utc() - before_real < timedelta(minutes=1)
    clock.shift_clock(timedelta(0))
    assert clock.now_utc() - clock.real_now_utc() < timedelta(minutes=1)


def test_the_clock_cannot_run_behind():
    with pytest.raises(ValueError):
        clock.shift_clock(timedelta(hours=-1))


def test_no_production_code_shifts_the_clock():
    users = [path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py")
             if "shift_clock" in path.read_text(encoding="utf-8")]

    assert users == ["utils/time.py"]


def test_production_code_reads_the_time_only_through_the_clock():
    """A direct read would ignore a shifted clock (and make time harder to test)."""
    direct = re.compile(r"datetime\.(now|utcnow|today)\(|date\.today\(|time\.time\(")
    users = [path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py")
             if direct.search(path.read_text(encoding="utf-8"))]

    assert users == ["utils/time.py"]

# Copyright (c) CodeBuddy Code
# MIT License

"""Calendar-expression parser for systemd's OnCalendar syntax.

Scope and design
-----------------
This module implements a deliberately small subset of systemd's
OnCalendar grammar. It parses a single, common shape of calendar event:

    [DOW] [DATE] TIME

where

    DOW  := weekday | weekday..weekday | *          (optional)
    DATE := *-*-* | YYYY-MM-DD                      (optional)
    TIME := HH:MM | HH:MM:SS                        (required)

Concretely:

    "Mon..Fri 09:00"
    "*-*-* 02:00:00"
    "2024-01-15 12:30"
    "09:00"
    "Mon 09:00"
    ".. 09:00"
    "* 09:00"
    "*-*-* 09:00"

List expressions ("Mon,Wed,Fri"), repetition ("Mon..Fri/2"), and the
sec/usec syntax are NOT supported. If you need them, extend the parser
rather than wrapping it with pre-processing; systemd's list handling is
stateful and quietly quirky and a wrapper would just hide the quirks.

This module also provides no I/O and no wall-clock access; callers pass
in a clock function so tests are deterministic.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Sequence

# Weekday name -> ISO-8601 day number (Mon=1 .. Sun=7). systemd accepts both
# full names and 3-letter abbreviations (case-insensitive).
_WEEKDAYS = {
    "mon": 1, "monday": 1,
    "tue": 2, "tuesday": 2,
    "wed": 3, "wednesday": 3,
    "thu": 4, "thursday": 4,
    "fri": 5, "friday": 5,
    "sat": 6, "saturday": 6,
    "sun": 7, "sunday": 7,
}


class ParseError(ValueError):
    """Raised when an OnCalendar expression is malformed or unsupported."""


@dataclass(frozen=True)
class _Parsed:
    weekdays: Optional[Sequence[int]]  # None means "no DOW restriction"
    date: Optional[_dt.date]
    hour: int
    minute: int
    second: int


def _parse_dow_range(token: str) -> List[int]:
    """Parse a weekday or weekday..weekday token into a list of ISO days."""
    if ".." in token:
        a, b = token.split("..", 1)
        if not a and not b:
            # ".." means every day, same as "*".
            return [1, 2, 3, 4, 5, 6, 7]
        if not a or not b:
            raise ParseError(f"weekday range '{token}' has empty bound")
        start = _WEEKDAYS.get(a.lower())
        end = _WEEKDAYS.get(b.lower())
        if start is None or end is None:
            raise ParseError(f"unknown weekday in '{token}'")
        if start <= end:
            return list(range(start, end + 1))
        # Wrap across the week boundary, e.g. "Fri..Mon" = Fri,Sat,Sun,Mon.
        return list(range(start, 8)) + list(range(1, end + 1))
    low = token.lower()
    if low == "*":
        return [1, 2, 3, 4, 5, 6, 7]
    day = _WEEKDAYS.get(low)
    if day is None:
        raise ParseError(f"unknown weekday '{token}'")
    return [day]


def _parse_time(token: str) -> tuple:
    parts = token.split(":")
    if len(parts) == 2:
        h, m, s = parts[0], parts[1], "00"
    elif len(parts) == 3:
        h, m, s = parts
    else:
        raise ParseError(f"invalid time '{token}'")
    if len(h) != 2 or len(m) != 2 or len(s) != 2:
        raise ParseError(
            f"time '{token}' components must be zero-padded to 2 digits"
        )
    try:
        hour, minute, second = int(h), int(m), int(s)
    except ValueError:
        raise ParseError(f"non-numeric time '{token}'")
    if not (0 <= hour <= 23):
        raise ParseError(f"hour {hour} out of range")
    if not (0 <= minute <= 59):
        raise ParseError(f"minute {minute} out of range")
    if not (0 <= second <= 59):
        raise ParseError(f"second {second} out of range")
    return hour, minute, second


def _parse_date(token: str) -> Optional[_dt.date]:
    if token == "*-*-*":
        return None
    # Accept YYYY-M-D but each field must be exactly as systemd emits it:
    # 4 digits, 2 digits, 2 digits. We keep the strictness to surface typos
    # like "2024-1-05" early instead of silently accepting it.
    parts = token.split("-")
    if len(parts) != 3:
        raise ParseError(f"invalid date '{token}'")
    y, m, d = parts
    if len(y) != 4 or len(m) != 2 or len(d) != 2:
        raise ParseError(f"date '{token}' must be YYYY-MM-DD with zero padding")
    try:
        yi, mi, di = int(y), int(m), int(d)
    except ValueError:
        raise ParseError(f"non-numeric date '{token}'")
    try:
        return _dt.date(yi, mi, di)
    except ValueError as e:
        raise ParseError(f"invalid date '{token}': {e}")


def _looks_like_time(token: str) -> bool:
    return ":" in token


def _looks_like_date(token: str) -> bool:
    return token != "*" and token.count("-") >= 2 and not token.startswith("-")


def _looks_like_dow(token: str) -> bool:
    low = token.lower()
    if low in ("*", ".."):
        return True
    if ".." in token:
        a, b = token.split("..", 1)
        return _weekday_lookup(a) is not None or _weekday_lookup(b) is not None
    return _weekday_lookup(token) is not None


def _weekday_lookup(token: str) -> Optional[int]:
    if not token:
        return None
    return _WEEKDAYS.get(token.lower())


def _parse(expr: str) -> _Parsed:
    raw = expr.strip()
    if not raw:
        raise ParseError("empty calendar expression")
    tokens = raw.split()
    if len(tokens) > 3:
        raise ParseError(f"expression has too many tokens: {raw!r}")

    dow_tok: Optional[str] = None
    date_tok: Optional[str] = None
    time_tok: Optional[str] = None

    # Classify by structural signal, not by position, so users may omit
    # the weekday field and still have a two-token "DATE TIME" expression
    # that is not misread as "DOW TIME".
    for tok in tokens:
        if _looks_like_time(tok):
            if time_tok is not None:
                raise ParseError(f"multiple time tokens in {raw!r}")
            time_tok = tok
        elif _looks_like_date(tok):
            if date_tok is not None:
                raise ParseError(f"multiple date tokens in {raw!r}")
            date_tok = tok
        elif _looks_like_dow(tok):
            if dow_tok is not None:
                raise ParseError(f"multiple weekday tokens in {raw!r}")
            dow_tok = tok
        else:
            raise ParseError(f"unrecognized token {tok!r} in {raw!r}")

    if time_tok is None:
        raise ParseError(f"calendar expression {raw!r} has no time component")

    hour, minute, second = _parse_time(time_tok)

    weekdays: Optional[Sequence[int]]
    if dow_tok is None:
        weekdays = None
    else:
        weekdays = tuple(sorted(set(_parse_dow_range(dow_tok))))

    date = _parse_date(date_tok) if date_tok is not None else None

    return _Parsed(weekdays=weekdays, date=date, hour=hour, minute=minute, second=second)


@dataclass
class CalendarExpression:
    """A compiled, iterable systemd OnCalendar expression.

    Usage:

        >>> from systemd_timer_calendar_parser import CalendarExpression
        >>> expr = CalendarExpression("Mon..Fri 09:00")
        >>> expr.next_after(datetime(2024, 1, 1, 8, 0))
        datetime.datetime(2024, 1, 1, 9, 0)

    Notes
    -----
    - time zone: naive datetime in, naive datetime out. The caller owns tz.
    - monotonicity: next_after is monotonic; if ``strict_after`` is True (the
      default) the returned datetime is strictly greater than ``after``.
      If False, an instant exactly matching the expression may be returned
      even when it equals ``after``.
    - clock: the optional ``clock`` callable is used only by the default
      argument of next_after(after=None). It lets tests inject a fixed
      "now" instead of touching the wall clock.
    """

    expression: str
    _parsed: _Parsed
    clock: Callable[[], _dt.datetime]

    def __init__(
        self,
        expression: str,
        *,
        clock: Callable[[], _dt.datetime] = _dt.datetime.now,
    ) -> None:
        self.expression = expression
        self._parsed = _parse(expression)
        self.clock = clock

    @property
    def weekdays(self) -> Optional[Sequence[int]]:
        """ISO weekday numbers (Mon=1 .. Sun=7) this fires on, or None."""
        return self._parsed.weekdays

    @property
    def date(self) -> Optional[_dt.date]:
        """Fixed date, or None for "any day"."""
        return self._parsed.date

    @property
    def hour(self) -> int:
        return self._parsed.hour

    @property
    def minute(self) -> int:
        return self._parsed.minute

    @property
    def second(self) -> int:
        return self._parsed.second

    def matches(self, dt: _dt.datetime) -> bool:
        """Return True iff ``dt`` satisfies this expression's constraints."""
        p = self._parsed
        if p.date is not None and dt.date() != p.date:
            return False
        if p.weekdays is not None and dt.isoweekday() not in p.weekdays:
            return False
        return (
            dt.hour == p.hour
            and dt.minute == p.minute
            and dt.second == p.second
        )

    def next_after(
        self,
        after: Optional[_dt.datetime] = None,
        *,
        strict_after: bool = True,
        max_days: int = 366 * 8,
    ) -> _dt.datetime:
        """Return the first datetime strictly after (or at) ``after``.

        ``after`` defaults to ``self.clock()``. Because the clock is a
        constructor-injected callable, tests that need a fixed reference
        point pass it explicitly and never touch the wall clock.

        The search advances one second at a time and is therefore exact
        but linear in the gap to the next match. ``max_days`` bounds the
        search so a misconfigured expression cannot loop forever.
        """
        if after is None:
            after = self.clock()
        if after.tzinfo is not None:
            raise ValueError("after must be a naive datetime")

        if strict_after:
            cursor = after.replace(microsecond=0) + _dt.timedelta(seconds=1)
        else:
            cursor = after.replace(microsecond=0)
            if self.matches(cursor):
                return cursor
            cursor = cursor + _dt.timedelta(seconds=1)

        deadline = cursor + _dt.timedelta(days=max_days)
        while cursor <= deadline:
            # Jump to the candidate time-of-day on the current date, then
            # (only) if that has already passed, advance to the next day.
            candidate = cursor.replace(
                hour=self.hour, minute=self.minute, second=self.second
            )
            if candidate >= cursor and self.matches(candidate):
                return candidate
            cursor = (cursor + _dt.timedelta(days=1)).replace(
                hour=0, minute=0, second=0
            )
        raise ParseError(
            f"no match for {self.expression!r} within {max_days} days"
        )

    def iter_from(
        self,
        after: Optional[_dt.datetime] = None,
        *,
        strict_after: bool = True,
        max_days: int = 366 * 8,
    ) -> Iterator[_dt.datetime]:
        """Yield successive matching datetimes starting after ``after``.

        The generator stops after ``max_days`` without a match to prevent
        infinite loops on never-matching expressions.
        """
        if after is None:
            after = self.clock()
        if after.tzinfo is not None:
            raise ValueError("after must be a naive datetime")

        cursor = self.next_after(
            after, strict_after=strict_after, max_days=max_days
        )
        while True:
            yield cursor
            cursor = self.next_after(cursor, strict_after=True, max_days=max_days)

    def __repr__(self) -> str:
        return f"CalendarExpression({self.expression!r})"

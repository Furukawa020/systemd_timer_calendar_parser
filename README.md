# systemd-timer-calendar-parser

Parses systemd OnCalendar time expressions like `Mon..Fri 09:00` and `*-*-* 02:00:00` into comparable, iterable Python datetime objects.

## Usage

```python
from systemd_timer_calendar_parser import CalendarExpression
from datetime import datetime

expr = CalendarExpression("Mon..Fri 09:00")

# Next firing strictly after a given instant:
print(expr.next_after(datetime(2024, 1, 1, 8, 0)))   # 2024-01-01 09:00:00

# Iterate every firing from a given instant:
for t in expr.iter_from(datetime(2024, 1, 1, 8, 0)):
    print(t)
    if t.year > 2024:
        break

# Check whether an instant matches the expression:
print(expr.matches(datetime(2024, 1, 1, 9, 0)))   # True (Monday)

# Deterministic "now" for testing: pass a clock callable.
fixed = datetime(2024, 1, 1, 8, 0)
expr2 = CalendarExpression("09:00", clock=lambda: fixed)
print(expr2.next_after())                          # 2024-01-01 09:00:00
```

## Why this exists

systemd timers use a compact calendar grammar (`OnCalendar=`) that is awkward to reason about in application code. This library turns a string like `Mon..Fri 09:00` into an object you can ask `next_after(t)` and `matches(t)` of, without depending on `systemd-analyze` or any third-party package.

The trade-off: this implements a small, deliberately chosen subset of the grammar. It supports a single event of the shape `[weekday] [date] time`, where `weekday` is `Mon`, `Mon..Fri`, `Fri..Mon` (wrap-around), `*`, or `..`; `date` is `*-*-*` or `YYYY-MM-DD`; and `time` is `HH:MM` or `HH:MM:SS` with zero-padded fields. It does **not** support list expressions (`Mon,Wed,Fri`), step values (`Mon..Fri/2`), or `~` approximate dates. If you need those, extend the parser directly rather than wrapping it; systemd's list and step semantics are quietly stateful and a wrapper would just hide the quirks.

## Edge you will hit

Time fields must be zero-padded: `09:00` parses, `9:00` does not. Dates must be `YYYY-MM-DD` with 2-digit month and day: `2024-01-15` parses, `2024-1-15` does not. This strictness is intentional — it surfaces typos early rather than silently accepting a malformed expression and firing at the wrong time.

`next_after` is naive-timezone only: pass a naive `datetime`, get a naive `datetime` back. Time-zone handling is the caller's responsibility. The search is bounded by `max_days` (default ~8 years) so a misconfigured expression that can never match raises `ParseError` instead of looping forever.

## Exports

- `CalendarExpression(expression, *, clock=datetime.now)` — parse and hold a calendar expression.
  - `.weekdays` — `Optional[Tuple[int, ...]]` of ISO weekday numbers (Mon=1..Sun=7), or `None` if no weekday filter.
  - `.date` — `Optional[date]` fixed date, or `None` for any day.
  - `.hour`, `.minute`, `.second` — `int` time components.
  - `.matches(dt) -> bool`
  - `.next_after(after=None, *, strict_after=True, max_days=...) -> datetime`
  - `.iter_from(after=None, *, strict_after=True, max_days=...) -> Iterator[datetime]`
- `ParseError` — subclass of `ValueError`, raised on malformed or unsupported expressions.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.


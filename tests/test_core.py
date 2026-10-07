# Copyright (c) CodeBuddy Code
# MIT License

import datetime as dt
import unittest

from systemd_timer_calendar_parser import CalendarExpression, ParseError


class TestParsing(unittest.TestCase):
    def test_simple_time(self):
        e = CalendarExpression("09:00")
        self.assertIsNone(e.weekdays)
        self.assertIsNone(e.date)
        self.assertEqual(e.hour, 9)
        self.assertEqual(e.minute, 0)
        self.assertEqual(e.second, 0)

    def test_dow_range(self):
        e = CalendarExpression("Mon..Fri 09:00")
        self.assertEqual(e.weekdays, (1, 2, 3, 4, 5))
        self.assertEqual(e.hour, 9)

    def test_single_dow(self):
        e = CalendarExpression("Wed 10:30")
        self.assertEqual(e.weekdays, (3,))

    def test_dow_wrap_around(self):
        # Fri..Mon wraps: Fri,Sat,Sun,Mon
        e = CalendarExpression("Fri..Mon 08:00")
        self.assertEqual(e.weekdays, (1, 5, 6, 7))

    def test_dow_star_means_every_day(self):
        e = CalendarExpression("* 09:00")
        self.assertEqual(e.weekdays, (1, 2, 3, 4, 5, 6, 7))

    def test_dotdot_means_every_day(self):
        e = CalendarExpression(".. 09:00")
        self.assertEqual(e.weekdays, (1, 2, 3, 4, 5, 6, 7))

    def test_wildcard_date(self):
        e = CalendarExpression("*-*-* 02:00:00")
        self.assertIsNone(e.date)
        self.assertEqual(e.hour, 2)
        self.assertEqual(e.second, 0)

    def test_fixed_date(self):
        e = CalendarExpression("2024-01-15 12:30")
        self.assertEqual(e.date, dt.date(2024, 1, 15))
        self.assertIsNone(e.weekdays)

    def test_dow_date_time(self):
        e = CalendarExpression("Mon 2024-01-15 12:30")
        self.assertEqual(e.weekdays, (1,))
        self.assertEqual(e.date, dt.date(2024, 1, 15))
        self.assertEqual(e.hour, 12)

    def test_case_insensitive_dow(self):
        e = CalendarExpression("MONDAY 09:00")
        self.assertEqual(e.weekdays, (1,))

    def test_rejects_empty(self):
        with self.assertRaises(ParseError):
            CalendarExpression("")

    def test_rejects_missing_time(self):
        with self.assertRaises(ParseError):
            CalendarExpression("Mon..Fri")

    def test_rejects_bad_hour(self):
        with self.assertRaises(ParseError):
            CalendarExpression("24:00")

    def test_rejects_unpadded_time(self):
        with self.assertRaises(ParseError):
            CalendarExpression("9:00")

    def test_rejects_unknown_dow(self):
        with self.assertRaises(ParseError):
            CalendarExpression("Funday 09:00")

    def test_rejects_invalid_date(self):
        with self.assertRaises(ParseError):
            CalendarExpression("2024-13-01 09:00")

    def test_rejects_too_many_tokens(self):
        with self.assertRaises(ParseError):
            CalendarExpression("Mon 2024-01-01 09:00 extra")

    def test_rejects_multiple_time_tokens(self):
        with self.assertRaises(ParseError):
            CalendarExpression("09:00 10:00")

    def test_rejects_bad_second(self):
        with self.assertRaises(ParseError):
            CalendarExpression("09:00:60")

    def test_rejects_unpadded_date(self):
        with self.assertRaises(ParseError):
            CalendarExpression("2024-1-05 09:00")


class TestNextAfter(unittest.TestCase):
    def test_next_on_same_day(self):
        e = CalendarExpression("09:00")
        got = e.next_after(dt.datetime(2024, 1, 1, 8, 0))
        self.assertEqual(got, dt.datetime(2024, 1, 1, 9, 0))

    def test_next_on_next_day(self):
        e = CalendarExpression("09:00")
        got = e.next_after(dt.datetime(2024, 1, 1, 10, 0))
        self.assertEqual(got, dt.datetime(2024, 1, 2, 9, 0))

    def test_strict_after_excludes_exact_match(self):
        e = CalendarExpression("09:00")
        got = e.next_after(dt.datetime(2024, 1, 1, 9, 0))
        self.assertEqual(got, dt.datetime(2024, 1, 2, 9, 0))

    def test_non_strict_allows_exact_match(self):
        e = CalendarExpression("09:00")
        got = e.next_after(
            dt.datetime(2024, 1, 1, 9, 0), strict_after=False
        )
        self.assertEqual(got, dt.datetime(2024, 1, 1, 9, 0))

    def test_microseconds_stripped(self):
        e = CalendarExpression("09:00")
        got = e.next_after(
            dt.datetime(2024, 1, 1, 9, 0, 0, 500), strict_after=False
        )
        self.assertEqual(got, dt.datetime(2024, 1, 1, 9, 0))

    def test_weekday_filter_skips_weekend(self):
        # 2024-01-05 is a Friday; next Mon..Fri 09:00 is Mon 2024-01-08.
        e = CalendarExpression("Mon..Fri 09:00")
        got = e.next_after(dt.datetime(2024, 1, 5, 12, 0))
        self.assertEqual(got, dt.datetime(2024, 1, 8, 9, 0))

    def test_fixed_date_only_matches_that_date(self):
        e = CalendarExpression("2024-01-15 12:30")
        got = e.next_after(dt.datetime(2024, 1, 10, 0, 0))
        self.assertEqual(got, dt.datetime(2024, 1, 15, 12, 30))

    def test_fixed_date_after_target_jumps_far(self):
        e = CalendarExpression("2024-01-15 12:30")
        # No future match within the bounded window.
        with self.assertRaises(ParseError):
            e.next_after(dt.datetime(2024, 6, 1, 0, 0))

    def test_default_clock_injected(self):
        # Deterministic: pass an explicit clock that returns a fixed now.
        fake_now = dt.datetime(2024, 1, 1, 8, 0)
        e = CalendarExpression("09:00", clock=lambda: fake_now)
        got = e.next_after()
        self.assertEqual(got, dt.datetime(2024, 1, 1, 9, 0))

    def test_rejects_tz_aware(self):
        e = CalendarExpression("09:00")
        with self.assertRaises(ValueError):
            e.next_after(dt.datetime(2024, 1, 1, 8, 0, tzinfo=dt.timezone.utc))

    def test_second_precision(self):
        e = CalendarExpression("02:00:00")
        got = e.next_after(dt.datetime(2024, 1, 1, 1, 59, 59))
        self.assertEqual(got, dt.datetime(2024, 1, 1, 2, 0, 0))


class TestMatches(unittest.TestCase):
    def test_matches_exact(self):
        e = CalendarExpression("Mon..Fri 09:00")
        # 2024-01-01 is a Monday.
        self.assertTrue(e.matches(dt.datetime(2024, 1, 1, 9, 0)))

    def test_no_match_weekend(self):
        e = CalendarExpression("Mon..Fri 09:00")
        # 2024-01-06 is a Saturday.
        self.assertFalse(e.matches(dt.datetime(2024, 1, 6, 9, 0)))

    def test_no_match_wrong_time(self):
        e = CalendarExpression("09:00")
        self.assertFalse(e.matches(dt.datetime(2024, 1, 1, 9, 30)))

    def test_no_match_wrong_date(self):
        e = CalendarExpression("2024-01-15 12:30")
        self.assertFalse(e.matches(dt.datetime(2024, 1, 14, 12, 30)))

    def test_no_dow_matches_any_day(self):
        e = CalendarExpression("09:00")
        self.assertTrue(e.matches(dt.datetime(2024, 1, 6, 9, 0)))  # Sat
        self.assertTrue(e.matches(dt.datetime(2024, 1, 7, 9, 0)))  # Sun


class TestIterFrom(unittest.TestCase):
    def test_iter_yields_in_order(self):
        e = CalendarExpression("09:00")
        it = e.iter_from(dt.datetime(2024, 1, 1, 8, 0))
        a = next(it)
        b = next(it)
        c = next(it)
        self.assertEqual(a, dt.datetime(2024, 1, 1, 9, 0))
        self.assertEqual(b, dt.datetime(2024, 1, 2, 9, 0))
        self.assertEqual(c, dt.datetime(2024, 1, 3, 9, 0))

    def test_iter_weekday_only(self):
        e = CalendarExpression("Mon 09:00")
        it = e.iter_from(dt.datetime(2024, 1, 1, 8, 0))  # Monday
        a = next(it)
        b = next(it)
        self.assertEqual(a, dt.datetime(2024, 1, 1, 9, 0))
        self.assertEqual(b, dt.datetime(2024, 1, 8, 9, 0))


class TestRepr(unittest.TestCase):
    def test_repr(self):
        e = CalendarExpression("Mon..Fri 09:00")
        self.assertEqual(repr(e), "CalendarExpression('Mon..Fri 09:00')")


if __name__ == "__main__":
    unittest.main()

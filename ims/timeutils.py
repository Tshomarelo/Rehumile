"""Calendar-day helpers that work on any database (shared by the finance app and HR).

The `field__date=day` lookup makes MySQL convert every stored time with CONVERT_TZ, which needs the server's time
zone tables. Where those tables are not loaded (a local MariaDB, some hosts) the conversion returns NULL and the
lookup silently matches nothing, so a day's trailer sales and refills vanish from the EOD without any error.

`on_day()` asks for the same rows with two plain comparisons instead, using the site's time zone (settings.TIME_ZONE,
Africa/Johannesburg), so it gives the same answer everywhere.
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone


def as_date(day):
    """A date from a date, a datetime or text such as "2026-09-01" (as typed in a filter). Raises ValueError otherwise."""
    if isinstance(day, datetime):
        return timezone.localtime(day).date() if timezone.is_aware(day) else day.date()
    if isinstance(day, date):
        return day
    return date.fromisoformat(str(day).strip()[:10])


def day_bounds(day):
    """(start, end) of a calendar day in the site's time zone, as aware datetimes; `end` is exclusive."""
    day = as_date(day)
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))


def range_bounds(first_day, last_day):
    """(start, end) covering first_day through last_day inclusive."""
    return day_bounds(first_day)[0], day_bounds(last_day)[1]


def on_day(field, day):
    """Filter kwargs for rows whose `field` falls on `day`: Model.objects.filter(**on_day('timestamp', d))."""
    start, end = day_bounds(day)
    return {f'{field}__gte': start, f'{field}__lt': end}


def between_days(field, first_day, last_day):
    start, end = range_bounds(first_day, last_day)
    return {f'{field}__gte': start, f'{field}__lt': end}


def local_date(value):
    """The site's calendar date of a stored time (aware datetimes are stored in UTC, whose date can differ)."""
    if value is None:
        return None
    return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()


# ── optional / user-typed dates (query strings) ─────────────────────────────

def parse_day(value):
    """A date from a date/datetime/'YYYY-MM-DD' string, or None when empty or unreadable (never raises)."""
    if value in (None, ''):
        return None
    try:
        return as_date(value)
    except (ValueError, TypeError):
        return None


def since(field, day):
    """Filter kwargs: rows on/after `day` (start of that day). Empty dict when `day` is missing or unreadable."""
    d = parse_day(day)
    return {f'{field}__gte': day_bounds(d)[0]} if d else {}


def until(field, day):
    """Filter kwargs: rows on/before `day` (up to the end of that day). Empty dict when missing or unreadable."""
    d = parse_day(day)
    return {f'{field}__lt': day_bounds(d)[1]} if d else {}

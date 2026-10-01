"""
Light upkeep that finance pages trigger when they load: post recurring costs that have come due and mark
unpaid invoices overdue. Both are idempotent, and this runs at most once an hour (per server process; a second
run just finds nothing to do), so a page load never double-posts. The daily_jobs command still sends reminders.
"""
import time

from django.core.cache import cache

KEY = 'ims:housekeeping:last_run'
INTERVAL_SECONDS = 3600


def run_if_due(user=None, force=False):
    """Returns {'ran': bool, 'recurring_posted': n, 'marked_overdue': n}."""
    now = time.time()
    last = cache.get(KEY)
    if not force and last and now - last < INTERVAL_SECONDS:
        return {'ran': False, 'recurring_posted': 0, 'marked_overdue': 0}
    cache.set(KEY, now, INTERVAL_SECONDS * 2)
    from . import billing, collections as coll, recurring
    today = billing._today()
    posted = len(recurring.post_due(today, user=user if getattr(user, 'is_authenticated', False) else None))
    overdue = coll.mark_overdue(today)
    return {'ran': True, 'recurring_posted': posted, 'marked_overdue': overdue}

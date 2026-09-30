"""Posts Expense records for recurring-expense templates whose due date has arrived."""
from datetime import date

from django.db import IntegrityError, transaction

from .ledger import ensure_seeded, post_expense
from .models import Expense, RecurringExpense


def post_due(today=None, user=None):
    """
    Create an Expense (and its ledger entries) for every due, unposted occurrence.
    Safe to run as often as you like: an occurrence can only be posted once.
    Returns the list of created Expense objects.
    """
    today = today or date.today()
    ensure_seeded()
    created = []
    for tpl in RecurringExpense.objects.select_related('expense_category__account').filter(is_active=True, start_date__lte=today):
        for due in tpl.occurrences(today):
            cat = tpl.expense_category
            try:
                with transaction.atomic():
                    exp = Expense.objects.create(
                        category=cat.kind, account=cat.account, expense_category=cat, amount=tpl.amount, vendor=tpl.vendor,
                        description=(tpl.description or tpl.name)[:500], expense_date=due,
                        cash_flow_stream=cat.default_cash_flow_stream, payment_status=tpl.payment_status,
                        is_recurring=True, recurring_frequency={'annual': 'annual', 'quarterly': 'quarterly'}.get(tpl.frequency, 'monthly'),
                        recurring_source=tpl, occurrence_date=due, recorded_by=user or tpl.created_by,
                    )
                    post_expense(exp)
                created.append(exp)
            except IntegrityError:
                pass                                   # already posted (two jobs raced)
            tpl.last_posted_for = due
        tpl.save(update_fields=['last_posted_for', 'updated_at'])
    return created

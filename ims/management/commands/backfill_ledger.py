from django.core.management.base import BaseCommand

from ims.models import Invoice, PurchaseSlip, PayrollEntry, Expense, Account
from ims.ledger import (
    seed_chart_of_accounts, post_invoice_sent, post_invoice_paid,
    post_expense, post_payroll_entry,
)


class Command(BaseCommand):
    help = (
        "Seeds the Chart of Accounts (if not already seeded) and replays historical "
        "paid invoices, purchase slips, and frozen payroll runs into the General Ledger. "
        "Safe to re-run — every posting is idempotent."
    )

    def handle(self, *args, **options):
        created = seed_chart_of_accounts()
        self.stdout.write(self.style.SUCCESS(f"Chart of Accounts: {created} account(s) created, {Account.objects.count()} total."))

        sent_count = 0
        paid_count = 0
        for inv in Invoice.objects.filter(status__in=("sent", "paid", "overdue")):
            if post_invoice_sent(inv):
                sent_count += 1
        for inv in Invoice.objects.filter(status="paid"):
            if post_invoice_paid(inv):
                paid_count += 1
        self.stdout.write(self.style.SUCCESS(f"Invoices: {sent_count} sent-entries, {paid_count} paid-entries posted."))

        expense_count = 0
        wrapped_count = 0
        for slip in PurchaseSlip.objects.all():
            if hasattr(slip, "expense"):
                expense = slip.expense
            else:
                category = "capital" if slip.cash_flow_stream == "icf" else "operating"
                account_key = "FIXED_ASSETS" if category == "capital" else "OPEX_OTHER"
                expense = Expense.objects.create(
                    category=category,
                    account=Account.objects.get(system_key=account_key),
                    amount=slip.amount,
                    vendor=slip.supplier_name,
                    description=slip.notes,
                    expense_date=slip.purchase_date,
                    cash_flow_stream=slip.cash_flow_stream,
                    payment_status="paid",
                    purchase_slip=slip,
                    recorded_by=slip.uploaded_by,
                )
                wrapped_count += 1
            if post_expense(expense):
                expense_count += 1
        self.stdout.write(self.style.SUCCESS(
            f"Purchase Slips: {wrapped_count} wrapped into new Expense records, {expense_count} ledger entries posted."
        ))

        # Any Expense rows created directly (not via PurchaseSlip wrapping) still need posting.
        direct_expense_count = 0
        for expense in Expense.objects.filter(purchase_slip__isnull=True):
            if post_expense(expense):
                direct_expense_count += 1
        self.stdout.write(self.style.SUCCESS(f"Direct Expenses: {direct_expense_count} ledger entries posted."))

        payroll_count = 0
        for entry in PayrollEntry.objects.filter(is_frozen=True):
            if post_payroll_entry(entry):
                payroll_count += 1
        self.stdout.write(self.style.SUCCESS(f"Payroll: {payroll_count} frozen entries posted."))

        self.stdout.write(self.style.SUCCESS("Backfill complete."))

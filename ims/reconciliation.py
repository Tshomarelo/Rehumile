"""
Bank reconciliation — parses bank-statement CSV exports and matches each
line against BANK_CASH ledger entries.

The point of this module is trust: the ledger says what SHOULD have moved
through the bank account; the statement says what DID. Auto-matching pairs
them up, and whatever is left over on either side is exactly the list of
things to explain at month-end:

- unmatched statement lines  = money that moved in the real bank account
  but was never recorded in the books
- unmatched ledger entries   = money the books claim moved, but the bank
  never saw
"""
import csv
import io
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction as db_transaction

from .models import BankStatementLine, LedgerEntry


class StatementParseError(Exception):
    """Raised with a user-facing message when a file can't be parsed."""


# ─────────────────────────────────────────────────────────────────────────────
# CSV parsing — tolerant of the common SA bank export shapes
# ─────────────────────────────────────────────────────────────────────────────

DATE_FORMATS = ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%d-%m-%Y', '%d %b %Y', '%d %B %Y', '%Y%m%d')

DATE_HEADERS = ('date', 'transaction date', 'txn date', 'value date', 'posting date')
DESC_HEADERS = ('description', 'narrative', 'details', 'reference', 'transaction description', 'memo')
AMOUNT_HEADERS = ('amount', 'value', 'transaction amount')
DEBIT_HEADERS = ('debit', 'debit amount', 'money out', 'withdrawals', 'paid out')
CREDIT_HEADERS = ('credit', 'credit amount', 'money in', 'deposits', 'paid in')
BALANCE_HEADERS = ('balance', 'running balance', 'closing balance')


def _parse_date(value):
    value = (value or '').strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value):
    """Handles 'R 1 234,56', '(500.00)' negatives, '1,234.56', '-250'."""
    value = (value or '').strip()
    if not value:
        return None
    negative = value.startswith('(') and value.endswith(')')
    cleaned = re.sub(r'[R$€£\s()]', '', value)
    # If both separators appear, the last one is the decimal point
    if ',' in cleaned and '.' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        # Lone comma: decimal if followed by exactly 2 digits, else thousands
        if re.search(r',\d{2}$', cleaned):
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def _find_column(headers, candidates):
    for i, h in enumerate(headers):
        if h in candidates:
            return i
    for i, h in enumerate(headers):
        if any(c in h for c in candidates):
            return i
    return None


def parse_statement_csv(file_bytes, filename=''):
    """Returns a list of {'line_date', 'description', 'amount', 'balance'}
    dicts. Raises StatementParseError with a user-facing message on failure."""
    if filename.lower().endswith('.pdf') or file_bytes[:5] == b'%PDF-':
        raise StatementParseError(
            'PDF statements are not supported yet — please export the statement '
            'from your bank as CSV and upload that instead.'
        )

    try:
        text = file_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode('latin-1')
        except UnicodeDecodeError:
            raise StatementParseError('Could not read the file — is it a valid CSV export?')

    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel

    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        raise StatementParseError('The file is empty.')

    headers = [c.strip().lower() for c in rows[0]]
    date_col = _find_column(headers, DATE_HEADERS)
    desc_col = _find_column(headers, DESC_HEADERS)
    amount_col = _find_column(headers, AMOUNT_HEADERS)
    debit_col = _find_column(headers, DEBIT_HEADERS)
    credit_col = _find_column(headers, CREDIT_HEADERS)
    balance_col = _find_column(headers, BALANCE_HEADERS)

    if date_col is None or (amount_col is None and debit_col is None and credit_col is None):
        raise StatementParseError(
            'Could not find the required columns. The CSV needs a date column '
            '(e.g. "Date") and either an "Amount" column or "Debit"/"Credit" '
            'columns. Found columns: ' + ', '.join(headers)
        )

    def cell(row, idx):
        return row[idx].strip() if idx is not None and idx < len(row) else ''

    lines, skipped = [], 0
    for row in rows[1:]:
        line_date = _parse_date(cell(row, date_col))
        if line_date is None:
            skipped += 1
            continue

        if amount_col is not None:
            amount = _parse_amount(cell(row, amount_col))
        else:
            debit = _parse_amount(cell(row, debit_col)) or Decimal('0')
            credit = _parse_amount(cell(row, credit_col)) or Decimal('0')
            # Bank exports list both columns as positive figures:
            # credit = money in, debit = money out
            amount = abs(credit) - abs(debit)
        if amount is None or amount == 0:
            skipped += 1
            continue

        lines.append({
            'line_date': line_date,
            'description': cell(row, desc_col)[:500],
            'amount': amount,
            'balance': _parse_amount(cell(row, balance_col)),
        })

    if not lines:
        raise StatementParseError(
            f'No usable transaction rows found ({skipped} rows skipped). '
            'Check that the file has date and amount values.'
        )
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Matching engine — statement lines vs BANK_CASH ledger entries
# ─────────────────────────────────────────────────────────────────────────────

MATCH_WINDOW_DAYS = 3


def _cash_entries_between(date_from, date_to, pad_days=MATCH_WINDOW_DAYS):
    return (
        LedgerEntry.objects
        .filter(
            account__system_key='BANK_CASH',
            transaction__transaction_date__gte=date_from - timedelta(days=pad_days),
            transaction__transaction_date__lte=date_to + timedelta(days=pad_days),
        )
        .select_related('transaction')
        .order_by('transaction__transaction_date')
    )


@db_transaction.atomic
def auto_match(statement):
    """Matches every line of `statement` against BANK_CASH ledger entries by
    exact amount within ±MATCH_WINDOW_DAYS, closest date first. Each ledger
    entry can satisfy at most one line. Manual matches are left untouched.
    Returns a summary dict."""
    lines = list(statement.lines.all())
    if not lines:
        return summarize(statement)

    date_from = min(l.line_date for l in lines)
    date_to = max(l.line_date for l in lines)
    statement.date_from, statement.date_to = date_from, date_to
    statement.save(update_fields=['date_from', 'date_to'])

    entries = list(_cash_entries_between(date_from, date_to))
    used_entry_ids = set(
        BankStatementLine.objects
        .filter(matched_entry__isnull=False)
        .exclude(statement=statement)
        .values_list('matched_entry_id', flat=True)
    )
    used_entry_ids.update(
        l.matched_entry_id for l in lines if l.match_status == 'manual' and l.matched_entry_id
    )

    for line in lines:
        if line.match_status == 'manual':
            continue  # someone reviewed this by hand — don't second-guess them
        line.match_status, line.matched_entry = 'unmatched', None

        wanted_debit = line.amount > 0  # money into the bank = BANK_CASH debit
        target = abs(line.amount)
        best, best_gap = None, None
        for e in entries:
            if e.id in used_entry_ids:
                continue
            moved = e.debit if wanted_debit else e.credit
            if moved != target:
                continue
            gap = abs((e.transaction.transaction_date - line.line_date).days)
            if gap > MATCH_WINDOW_DAYS:
                continue
            if best is None or gap < best_gap:
                best, best_gap = e, gap
        if best is not None:
            line.match_status, line.matched_entry = 'matched', best
            used_entry_ids.add(best.id)

        line.save(update_fields=['match_status', 'matched_entry'])

    return summarize(statement)


def summarize(statement):
    """Reconciliation report for a statement: match rate, money in/out, and
    both discrepancy lists (bank-only lines and books-only ledger entries)."""
    lines = list(statement.lines.select_related('matched_entry', 'matched_entry__transaction'))
    matched = [l for l in lines if l.match_status in ('matched', 'manual')]
    unmatched = [l for l in lines if l.match_status == 'unmatched']

    total_in = sum((l.amount for l in lines if l.amount > 0), Decimal('0'))
    total_out = sum((-l.amount for l in lines if l.amount < 0), Decimal('0'))

    unmatched_ledger = []
    if statement.date_from and statement.date_to:
        matched_ids = {l.matched_entry_id for l in matched if l.matched_entry_id}
        also_used = set(
            BankStatementLine.objects
            .filter(matched_entry__isnull=False)
            .exclude(statement=statement)
            .values_list('matched_entry_id', flat=True)
        )
        for e in _cash_entries_between(statement.date_from, statement.date_to, pad_days=0):
            if e.id in matched_ids or e.id in also_used:
                continue
            unmatched_ledger.append({
                'entry_id': str(e.id),
                'date': str(e.transaction.transaction_date),
                'description': e.transaction.description,
                'amount': float(e.debit - e.credit),
                'memo': e.memo,
            })

    return {
        'lines_total': len(lines),
        'lines_matched': len(matched),
        'lines_unmatched': len(unmatched),
        'match_rate_pct': round(len(matched) / len(lines) * 100, 1) if lines else 0,
        'bank_money_in': float(total_in),
        'bank_money_out': float(total_out),
        'unmatched_bank_lines': [{
            'id': str(l.id),
            'date': str(l.line_date),
            'description': l.description,
            'amount': float(l.amount),
        } for l in unmatched],
        'unmatched_ledger_entries': unmatched_ledger,
        'is_clean': not unmatched and not unmatched_ledger,
    }

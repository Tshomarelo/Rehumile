"""
Financial statement generation — reads the general ledger (never writes to
it) and produces Income Statement, Balance Sheet, and Cash Flow Statement
data. Because every ledger.post_transaction() call is balance-checked at
write time, Assets == Liabilities + Equity is an invariant of the Balance
Sheet, not something these functions have to force to agree.
"""
from decimal import Decimal

from django.db.models import Sum, Q

from .models import Account, LedgerEntry


def _signed_balance(account_obj, debit_total, credit_total):
    debit_total = debit_total or Decimal('0')
    credit_total = credit_total or Decimal('0')
    if account_obj.normal_balance == 'debit':
        return debit_total - credit_total
    return credit_total - debit_total


def account_balances(account_type=None, account_subtype=None, date_from=None, date_to=None, as_of_date=None):
    """Returns {account: signed_balance} for every active account matching the filters."""
    qs = Account.objects.filter(is_active=True)
    if account_type:
        qs = qs.filter(account_type=account_type)
    if account_subtype:
        qs = qs.filter(account_subtype=account_subtype)

    entry_filter = Q()
    if date_from:
        entry_filter &= Q(transaction__transaction_date__gte=date_from)
    if date_to:
        entry_filter &= Q(transaction__transaction_date__lte=date_to)
    if as_of_date:
        entry_filter &= Q(transaction__transaction_date__lte=as_of_date)

    results = {}
    for acct in qs:
        agg = LedgerEntry.objects.filter(entry_filter, account=acct).aggregate(
            d=Sum('debit'), c=Sum('credit'),
        )
        balance = _signed_balance(acct, agg['d'], agg['c'])
        if balance != 0:
            results[acct] = balance
    return results


def income_statement(date_from, date_to):
    revenue_accounts = account_balances(account_type='revenue', date_from=date_from, date_to=date_to)
    cogs_accounts = account_balances(account_type='expense', account_subtype='cogs', date_from=date_from, date_to=date_to)
    opex_accounts = account_balances(account_type='expense', account_subtype='operating_expense', date_from=date_from, date_to=date_to)

    revenue = sum(revenue_accounts.values(), Decimal('0'))
    cogs = sum(cogs_accounts.values(), Decimal('0'))
    opex = sum(opex_accounts.values(), Decimal('0'))
    gross_profit = revenue - cogs
    net_profit = gross_profit - opex

    def _rows(d):
        return [{'code': a.code, 'name': a.name, 'amount': float(v)} for a, v in sorted(d.items(), key=lambda kv: kv[0].code)]

    return {
        'period': {'date_from': str(date_from), 'date_to': str(date_to)},
        'revenue': {'total': float(revenue), 'accounts': _rows(revenue_accounts)},
        'cogs': {'total': float(cogs), 'accounts': _rows(cogs_accounts)},
        'gross_profit': float(gross_profit),
        'gross_profit_margin_pct': round(float(gross_profit / revenue * 100), 2) if revenue else 0,
        'operating_expenses': {'total': float(opex), 'accounts': _rows(opex_accounts)},
        'net_profit': float(net_profit),
        'net_profit_margin_pct': round(float(net_profit / revenue * 100), 2) if revenue else 0,
    }


def balance_sheet(as_of_date):
    """
    Assets = Liabilities + Equity is a true invariant of the ledger, but only
    once Revenue/Expense activity is folded into Equity. Since there is no
    formal fiscal-year closing entry (yet), this computes a live
    "Current Earnings" line (all-time Revenue - Expenses, not yet closed)
    and includes it under Equity — exactly what any accounting package shows
    on a balance sheet pulled mid-year, before the books are formally closed.
    """
    asset_accounts = account_balances(account_type='asset', as_of_date=as_of_date)
    liability_accounts = account_balances(account_type='liability', as_of_date=as_of_date)
    equity_accounts = account_balances(account_type='equity', as_of_date=as_of_date)

    revenue_accounts = account_balances(account_type='revenue', as_of_date=as_of_date)
    expense_accounts = account_balances(account_type='expense', as_of_date=as_of_date)
    current_earnings = sum(revenue_accounts.values(), Decimal('0')) - sum(expense_accounts.values(), Decimal('0'))

    assets = sum(asset_accounts.values(), Decimal('0'))
    liabilities = sum(liability_accounts.values(), Decimal('0'))
    equity = sum(equity_accounts.values(), Decimal('0')) + current_earnings

    def _rows(d):
        return [{'code': a.code, 'name': a.name, 'amount': float(v)} for a, v in sorted(d.items(), key=lambda kv: kv[0].code)]

    equity_rows = _rows(equity_accounts)
    if current_earnings != 0:
        equity_rows.append({'code': '3900', 'name': 'Current Earnings (Not Yet Closed)', 'amount': float(current_earnings)})

    return {
        'as_of_date': str(as_of_date),
        'assets': {'total': float(assets), 'accounts': _rows(asset_accounts)},
        'liabilities': {'total': float(liabilities), 'accounts': _rows(liability_accounts)},
        'equity': {'total': float(equity), 'accounts': equity_rows},
        'liabilities_plus_equity': float(liabilities + equity),
        'balances': assets == (liabilities + equity),
    }


def cash_flow_statement(date_from, date_to):
    qs = LedgerEntry.objects.filter(
        account__system_key='BANK_CASH',
        transaction__transaction_date__gte=date_from,
        transaction__transaction_date__lte=date_to,
    ).values('transaction__cash_flow_stream').annotate(
        inflow=Sum('debit'), outflow=Sum('credit'),
    )
    streams = {'ocf': {'inflow': 0.0, 'outflow': 0.0}, 'icf': {'inflow': 0.0, 'outflow': 0.0}, 'fcf': {'inflow': 0.0, 'outflow': 0.0}}
    for row in qs:
        stream = row['transaction__cash_flow_stream']
        if stream in streams:
            streams[stream]['inflow'] = float(row['inflow'] or 0)
            streams[stream]['outflow'] = float(row['outflow'] or 0)

    net_by_stream = {k: v['inflow'] - v['outflow'] for k, v in streams.items()}
    net_change_in_cash = sum(net_by_stream.values())

    return {
        'period': {'date_from': str(date_from), 'date_to': str(date_to)},
        'operating': {**streams['ocf'], 'net': net_by_stream['ocf']},
        'investing': {**streams['icf'], 'net': net_by_stream['icf']},
        'financing': {**streams['fcf'], 'net': net_by_stream['fcf']},
        'net_change_in_cash': net_change_in_cash,
    }


def break_even_units(fixed_costs, avg_revenue_per_unit, avg_variable_cost_per_unit):
    """Break-Even Units = Fixed Costs / (Avg Revenue Per Unit - Avg Variable Cost Per Unit)"""
    denominator = Decimal(str(avg_revenue_per_unit)) - Decimal(str(avg_variable_cost_per_unit))
    if denominator <= 0:
        return None
    return float(Decimal(str(fixed_costs)) / denominator)

"""
API for the integrated finance modules:

  GET  /finance/summary/           paid / unpaid / expenses / revenue + workings
  GET  /finance/trend/             weekly / monthly / yearly series (Business Intelligence)
  *    /expense-categories/        manage expense categories (wired to ledger accounts)
  *    /quotations/                quotations, quote -> invoice, quoted-vs-actual cost
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import finance
from .ledger import ensure_seeded
from .models import (
    Account, Company, Expense, ExpenseCategory, Invoice, InvoiceItem,
    Quotation, QuotationItem, ServicePrice,
)

FINANCE_ROLES = ('admin', 'finance')
READ_ROLES = ('admin', 'finance', 'cashier', 'technician', 'agent')


def _denied():
    return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)


def _dec(value, default='0'):
    try:
        return Decimal(str(value if value not in (None, '') else default))
    except InvalidOperation:
        raise ValueError(f'"{value}" is not a valid number.')


# ─────────────────────────────────────────────────────────────────────────────
# Finance summary + trend
# ─────────────────────────────────────────────────────────────────────────────

class FinanceSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in FINANCE_ROLES:
            return _denied()
        p = request.query_params
        try:
            start, end, label = finance.resolve_period(
                p.get('period', 'month'), p.get('date'), p.get('date_from'), p.get('date_to'))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        data = finance.summary(start, end)
        data['period']['label'] = label
        data['period']['type'] = p.get('period', 'month')
        return Response(data)


class FinanceTrendView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in FINANCE_ROLES + ('agent',):
            return _denied()
        p = request.query_params
        try:
            return Response(finance.trend(p.get('granularity', 'monthly'), p.get('periods'), anchor=p.get('date')))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# Expense categories
# ─────────────────────────────────────────────────────────────────────────────

def _category_dict(c, spent=None):
    return {
        'id': str(c.id), 'name': c.name, 'kind': c.kind,
        'account': str(c.account_id), 'account_name': f"{c.account.code} — {c.account.name}",
        'default_cash_flow_stream': c.default_cash_flow_stream,
        'monthly_budget': float(c.monthly_budget), 'description': c.description,
        'is_active': c.is_active, 'is_system': c.is_system,
        'spent_this_month': float(spent or 0),
    }


class ExpenseCategoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        if request.user.role not in READ_ROLES:
            return _denied()
        ensure_seeded()
        qs = ExpenseCategory.objects.select_related('account')
        if request.query_params.get('is_active') in ('1', 'true', 'True'):
            qs = qs.filter(is_active=True)
        kind = request.query_params.get('kind')
        if kind:
            qs = qs.filter(kind=kind)
        month_start = date.today().replace(day=1)
        spent = dict(
            Expense.objects.filter(expense_date__gte=month_start, expense_category__isnull=False)
            .values_list('expense_category').annotate(t=Sum('amount')).values_list('expense_category', 't')
        )
        return Response([_category_dict(c, spent.get(c.id)) for c in qs])

    def _apply(self, cat, d):
        for f in ('name', 'kind', 'description', 'default_cash_flow_stream'):
            if f in d:
                setattr(cat, f, (d[f] or '').strip() if isinstance(d[f], str) else d[f])
        if 'account' in d:
            try:
                cat.account = Account.objects.get(pk=d['account'])
            except (Account.DoesNotExist, ValueError, DjangoValidationError):
                raise ValueError('Account not found.')
        if 'monthly_budget' in d:
            cat.monthly_budget = _dec(d['monthly_budget'])
            if cat.monthly_budget < 0:
                raise ValueError('Budget cannot be negative.')
        if 'is_active' in d:
            cat.is_active = bool(d['is_active'])
        if cat.kind not in ('cogs', 'operating', 'capital'):
            raise ValueError('kind must be cogs, operating or capital.')
        if not cat.name:
            raise ValueError('name is required.')
        # A category can only post to an account of the right type.
        if cat.account_id:
            want = 'asset' if cat.kind == 'capital' else 'expense'
            if cat.account.account_type != want:
                raise ValueError(f'A {cat.get_kind_display()} category must use an {want} account.')

    def post(self, request):
        if request.user.role not in FINANCE_ROLES:
            return _denied()
        cat = ExpenseCategory()
        try:
            d = request.data
            if not d.get('account'):
                raise ValueError('account is required.')
            self._apply(cat, d)
            if ExpenseCategory.objects.filter(name__iexact=cat.name).exists():
                raise ValueError('A category with that name already exists.')
            if 'default_cash_flow_stream' not in d:
                cat.default_cash_flow_stream = 'icf' if cat.kind == 'capital' else 'ocf'
            cat.save()
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response(_category_dict(cat), status=201)

    def patch(self, request, pk):
        if request.user.role not in FINANCE_ROLES:
            return _denied()
        try:
            cat = ExpenseCategory.objects.select_related('account').get(pk=pk)
        except ExpenseCategory.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        try:
            self._apply(cat, request.data)
            if ExpenseCategory.objects.filter(name__iexact=cat.name).exclude(pk=cat.pk).exists():
                raise ValueError('A category with that name already exists.')
            cat.save()
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response(_category_dict(cat))

    def delete(self, request, pk):
        if request.user.role not in FINANCE_ROLES:
            return _denied()
        try:
            cat = ExpenseCategory.objects.get(pk=pk)
        except ExpenseCategory.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        if cat.expenses.exists():
            # Keep history intact: hide instead of delete.
            cat.is_active = False
            cat.save(update_fields=['is_active', 'updated_at'])
            return Response({'detail': 'Category has expenses, so it was deactivated instead of deleted.', 'deactivated': True})
        if cat.is_system:
            return Response({'detail': 'Built-in categories cannot be deleted — deactivate it instead.'}, status=400)
        cat.delete()
        return Response(status=204)


# ─────────────────────────────────────────────────────────────────────────────
# Quotations
# ─────────────────────────────────────────────────────────────────────────────

def _next_quote_number():
    year = date.today().year
    prefix = f"Q-{year}-"
    last = Quotation.objects.filter(quote_number__startswith=prefix).order_by('-quote_number').first()
    n = int(last.quote_number.rsplit('-', 1)[1]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def _quote_summary(q):
    return {
        'id': str(q.id), 'quote_number': q.quote_number, 'client_name': q.client_name,
        'company': str(q.company_id) if q.company_id else None, 'title': q.title, 'status': q.status,
        'issue_date': q.issue_date.isoformat(), 'valid_until': q.valid_until.isoformat() if q.valid_until else None,
        'subtotal': float(q.subtotal), 'tax_amount': float(q.tax_amount), 'total_amount': float(q.total_amount),
        'estimated_cost': float(q.estimated_cost),
        'expected_margin': float(q.subtotal - q.estimated_cost),
        'invoice': str(q.invoice_id) if q.invoice_id else None,
        'invoice_number': q.invoice.invoice_number if q.invoice_id else None,
    }


def _quote_detail(q):
    data = _quote_summary(q)
    expenses = list(q.expenses.select_related('expense_category', 'account').order_by('-expense_date'))
    actual = sum((e.amount for e in expenses), Decimal('0'))
    data.update({
        'client_email': q.client_email, 'client_phone': q.client_phone, 'vat_rate': float(q.vat_rate),
        'notes': q.notes, 'terms': q.terms,
        'sent_at': q.sent_at.isoformat() if q.sent_at else None,
        'items': [{
            'id': str(i.id), 'service_price': str(i.service_price_id) if i.service_price_id else None,
            'description': i.description, 'quantity': float(i.quantity), 'unit_price': float(i.unit_price),
            'unit_cost': float(i.unit_cost), 'cost_category': str(i.cost_category_id) if i.cost_category_id else None,
            'cost_category_name': i.cost_category.name if i.cost_category_id else None,
            'line_total': float(i.line_total), 'line_cost': float(i.line_cost),
        } for i in q.items.select_related('cost_category')],
        'actual_cost': float(actual),
        'cost_variance': float(actual - q.estimated_cost),       # + = over the estimate
        'actual_margin': float(q.subtotal - actual),
        'actual_margin_pct': round(float((q.subtotal - actual) / q.subtotal * 100), 1) if q.subtotal else 0,
        'expenses': [{
            'id': str(e.id), 'vendor': e.vendor, 'description': e.description, 'amount': float(e.amount),
            'expense_date': e.expense_date.isoformat(),
            'category': e.expense_category.name if e.expense_category_id else e.account.name,
            'payment_status': e.payment_status,
        } for e in expenses],
    })
    return data


def _save_items(quote, items):
    quote.items.all().delete()
    for order, it in enumerate(items or []):
        desc = (it.get('description') or '').strip()
        sp = None
        if it.get('service_price'):
            sp = ServicePrice.objects.filter(pk=it['service_price']).first()
            if sp and not desc:
                desc = sp.name
        if not desc:
            raise ValueError('Every line needs a description.')
        qty, price, cost = _dec(it.get('quantity'), '1'), _dec(it.get('unit_price')), _dec(it.get('unit_cost'))
        if qty <= 0 or price < 0 or cost < 0:
            raise ValueError('Quantity must be above zero; prices and costs cannot be negative.')
        cat = None
        if it.get('cost_category'):
            cat = ExpenseCategory.objects.filter(pk=it['cost_category']).first()
        QuotationItem.objects.create(
            quotation=quote, service_price=sp, description=desc[:255], quantity=qty,
            unit_price=price, unit_cost=cost, cost_category=cat, display_order=order)


def _apply_quote_fields(q, d):
    for f in ('client_name', 'client_email', 'client_phone', 'title', 'notes', 'terms'):
        if f in d:
            setattr(q, f, (d[f] or '').strip())
    if 'company' in d:
        q.company = Company.objects.filter(pk=d['company']).first() if d['company'] else None
        if q.company and not q.client_name:
            q.client_name = q.company.name
    if 'issue_date' in d and d['issue_date']:
        q.issue_date = date.fromisoformat(str(d['issue_date'])[:10])
    if 'valid_until' in d:
        q.valid_until = date.fromisoformat(str(d['valid_until'])[:10]) if d['valid_until'] else None
    if 'vat_rate' in d:
        q.vat_rate = _dec(d['vat_rate'])
        if not (0 <= q.vat_rate <= 100):
            raise ValueError('vat_rate must be between 0 and 100.')
    if not q.client_name:
        raise ValueError('client_name is required.')


class QuotationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in FINANCE_ROLES + ('agent',):
            return _denied()
        qs = Quotation.objects.select_related('invoice')
        p = request.query_params
        if p.get('search'):
            qs = qs.filter(Q(quote_number__icontains=p['search']) | Q(client_name__icontains=p['search']) | Q(title__icontains=p['search']))
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        if p.get('date_from'):
            qs = qs.filter(issue_date__gte=p['date_from'])
        if p.get('date_to'):
            qs = qs.filter(issue_date__lte=p['date_to'])
        # Quotes past their validity date that nobody answered are expired (lazy, no cron needed).
        Quotation.objects.filter(status__in=('draft', 'sent'), valid_until__lt=date.today()).update(status='expired')
        rows = [_quote_summary(q) for q in qs[:300]]
        open_value = sum((r['total_amount'] for r in rows if r['status'] in ('sent',)), 0)
        won = sum((r['total_amount'] for r in rows if r['status'] in ('accepted', 'invoiced')), 0)
        return Response({'results': rows, 'count': len(rows), 'open_value': round(open_value, 2), 'won_value': round(won, 2)})

    @transaction.atomic
    def post(self, request):
        if request.user.role not in FINANCE_ROLES:
            return _denied()
        d = request.data
        q = Quotation(issue_date=date.today(), created_by=request.user, quote_number=_next_quote_number())
        try:
            from .views import _company_settings
            cs = _company_settings()
            q.vat_rate = Decimal(cs.vat_rate or 0) * 100
            q.terms = cs.payment_terms
            _apply_quote_fields(q, d)
            if not q.valid_until:
                q.valid_until = q.issue_date + timedelta(days=30)
            q.save()
            _save_items(q, d.get('items'))
        except (ValueError, TypeError) as exc:
            transaction.set_rollback(True)
            return Response({'detail': str(exc)}, status=400)
        q.recalculate()
        return Response(_quote_detail(q), status=201)


class QuotationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        return Quotation.objects.select_related('invoice', 'company').filter(pk=pk).first()

    def get(self, request, pk):
        if request.user.role not in FINANCE_ROLES + ('agent',):
            return _denied()
        q = self._get(pk)
        return Response(_quote_detail(q)) if q else Response({'detail': 'Not found.'}, status=404)

    @transaction.atomic
    def patch(self, request, pk):
        if request.user.role not in FINANCE_ROLES:
            return _denied()
        q = self._get(pk)
        if not q:
            return Response({'detail': 'Not found.'}, status=404)
        if q.status in ('accepted', 'invoiced'):
            return Response({'detail': 'An accepted quotation can no longer be edited.'}, status=400)
        try:
            _apply_quote_fields(q, request.data)
            q.save()
            if 'items' in request.data:
                _save_items(q, request.data['items'])
        except (ValueError, TypeError) as exc:
            transaction.set_rollback(True)
            return Response({'detail': str(exc)}, status=400)
        q.recalculate()
        return Response(_quote_detail(q))

    def delete(self, request, pk):
        if request.user.role not in FINANCE_ROLES:
            return _denied()
        q = self._get(pk)
        if not q:
            return Response({'detail': 'Not found.'}, status=404)
        if q.status not in ('draft', 'declined', 'expired'):
            return Response({'detail': 'Only draft, declined or expired quotations can be deleted.'}, status=400)
        q.delete()
        return Response(status=204)


def _email_quote(quote, base_url):
    if not quote.client_email:
        return False
    from django.core.mail import send_mail
    from django.conf import settings
    lines = '\n'.join(f"  - {i.description}: {i.quantity:g} x R{i.unit_price:,.2f} = R{i.line_total:,.2f}" for i in quote.items.all())
    body = (
        f"Hi {quote.client_name},\n\nThank you for your interest in Rehumile TMW. Quotation {quote.quote_number}:\n\n{lines}\n\n"
        f"Subtotal: R{quote.subtotal:,.2f}\nVAT: R{quote.tax_amount:,.2f}\nTotal: R{quote.total_amount:,.2f}\n\n"
        f"Valid until {quote.valid_until:%d %B %Y}.\n\n{quote.notes}\n\nRegards,\nRehumile TMW"
    )
    try:
        send_mail(f"Quotation {quote.quote_number} — Rehumile TMW", body, settings.DEFAULT_FROM_EMAIL,
                  [quote.client_email], fail_silently=False)
        return True
    except Exception:
        return False


class QuotationActionView(APIView):
    """POST {action: send|accept|decline|convert} — quote lifecycle."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        if request.user.role not in FINANCE_ROLES:
            return _denied()
        q = Quotation.objects.select_related('company').filter(pk=pk).first()
        if not q:
            return Response({'detail': 'Not found.'}, status=404)
        action = request.data.get('action')
        now = timezone.now()
        emailed = None

        if action == 'send':
            if not q.items.exists():
                return Response({'detail': 'Add at least one line before sending.'}, status=400)
            if q.status not in ('draft', 'sent', 'expired'):
                return Response({'detail': f'Cannot send a {q.status} quotation.'}, status=400)
            q.status, q.sent_at = 'sent', now
            q.save(update_fields=['status', 'sent_at', 'updated_at'])
            if request.data.get('email'):
                emailed = _email_quote(q, f"{request.scheme}://{request.get_host()}")
        elif action == 'accept':
            if q.status not in ('draft', 'sent'):
                return Response({'detail': f'Cannot accept a {q.status} quotation.'}, status=400)
            q.status, q.decided_at = 'accepted', now
            q.save(update_fields=['status', 'decided_at', 'updated_at'])
        elif action == 'decline':
            if q.status not in ('draft', 'sent', 'accepted'):
                return Response({'detail': f'Cannot decline a {q.status} quotation.'}, status=400)
            q.status, q.decided_at = 'declined', now
            q.save(update_fields=['status', 'decided_at', 'updated_at'])
        elif action == 'convert':
            if q.status == 'invoiced':
                return Response({'detail': 'Already converted to an invoice.'}, status=400)
            if q.status != 'accepted':
                return Response({'detail': 'Accept the quotation before converting it to an invoice.'}, status=400)
            self._convert(q)
        else:
            return Response({'detail': 'action must be send, accept, decline or convert.'}, status=400)

        data = _quote_detail(Quotation.objects.select_related('invoice').get(pk=q.pk))
        if emailed is not None:
            data['emailed'] = emailed
        return Response(data)

    def _convert(self, q):
        from .views import _next_invoice_number
        today = date.today()
        inv = Invoice.objects.create(
            invoice_number=_next_invoice_number(), company=q.company,
            billing_period_start=today, billing_period_end=today,
            subtotal=q.subtotal, tax_rate=q.vat_rate, tax_amount=q.tax_amount, total_amount=q.total_amount,
            ticket_count=0, hours_worked=0, status='draft', invoice_type='adhoc',
            description=f"{q.title or 'Quotation'} ({q.quote_number})"[:500],
            notes=f"Created from quotation {q.quote_number} for {q.client_name}.",
            due_date=today + timedelta(days=30),
        )
        for it in q.items.all():
            InvoiceItem.objects.create(
                invoice=inv, description=it.description, quantity=it.quantity,
                unit_price=it.unit_price, amount=it.line_total, item_type='service')
        q.invoice, q.status = inv, 'invoiced'
        q.save(update_fields=['invoice', 'status', 'updated_at'])

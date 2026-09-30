"""Payslip / tax certificate import, preview, publish and reissue."""
import csv
import io
import re
import zipfile
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import audit
from .notify import notify
from ..models import Employee, ImportBatch, Payslip, TaxCertificate


def _split_pdf(fileobj):
    """Yield (page_text, single_page_pdf_bytes) for each page of a combined PDF."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(fileobj)
    for page in reader.pages:
        w = PdfWriter()
        w.add_page(page)
        buf = io.BytesIO()
        w.write(buf)
        yield (page.extract_text() or ''), buf.getvalue()


def _match(company, text=None, name=None):
    """Find the employee whose number appears in the text or file name."""
    hay = f"{text or ''} {name or ''}"
    tokens = set(re.findall(r'[A-Za-z0-9\-]+', hay))
    hits = list(Employee.objects.filter(company=company, employee_number__in=tokens))
    if len(hits) == 1:
        return hits[0], ''
    return None, ('More than one employee number found' if hits else 'No employee number found')


def _read_amounts(data_file):
    out = {}
    if not data_file:
        return out
    data_file.open('rb')
    text = io.TextIOWrapper(data_file, encoding='utf-8-sig')
    for row in csv.DictReader(text):
        num = (row.get('employee_number') or '').strip()
        try:
            out[num] = tuple(Decimal((row.get(k) or '').replace(',', '').strip() or '0') for k in ('gross', 'deductions', 'net'))
        except InvalidOperation:
            continue
    return out


def _units(batch):
    name = batch.source_file.name.lower()
    batch.source_file.open('rb')
    if name.endswith('.zip'):
        with zipfile.ZipFile(batch.source_file) as z:
            for info in z.infolist():
                if info.filename.lower().endswith('.pdf') and not info.is_dir():
                    data = z.read(info)
                    text = ''
                    try:
                        text = next(_split_pdf(io.BytesIO(data)))[0]
                    except Exception:
                        pass
                    yield text, data, info.filename
    else:
        for text, data in _split_pdf(batch.source_file):
            yield text, data, ''


@transaction.atomic
def build_preview(batch):
    """Split/match the upload into DRAFT rows. Nothing is visible to employees."""
    amounts = _read_amounts(batch.data_file)
    made = matched = 0
    for text, data, fname in _units(batch):
        emp, note = _match(batch.company, text, fname)
        made += 1
        matched += bool(emp)
        label = emp.employee_number if emp else f'unmatched-{made}'
        cf = ContentFile(data, name=f'{label}.pdf')
        if batch.kind == 'PAYSLIP':
            g = d = n = None
            if emp and emp.employee_number in amounts:
                g, d, n = amounts[emp.employee_number]
            version = 1 + Payslip.objects.filter(employee=emp, pay_period=batch.pay_period).count() if emp else 1
            Payslip.objects.create(employee=emp, pay_period=batch.pay_period, batch=batch, file=cf, version=version,
                                   gross=g, deductions=d, net=n, match_note=note, created_by=batch.uploaded_by)
        else:
            version = 1 + TaxCertificate.objects.filter(employee=emp, tax_year=batch.tax_year, cert_type=batch.cert_type).count() if emp else 1
            TaxCertificate.objects.create(employee=emp, tax_year=batch.tax_year, cert_type=batch.cert_type, batch=batch,
                                          file=cf, version=version, match_note=note, created_by=batch.uploaded_by)
    batch.summary = f"{made} document(s), {matched} matched, {made - matched} need attention"
    batch.save(update_fields=['summary'])
    return made, matched


def _rows(batch):
    return batch.payslips if batch.kind == 'PAYSLIP' else batch.certificates


@transaction.atomic
def publish(batch, user=None):
    """Make matched drafts visible. A newer version supersedes older published ones."""
    now = timezone.now()
    rows = _rows(batch).filter(status='DRAFT', employee__isnull=False).select_related('employee__user')
    users, n = [], 0
    for r in rows:
        older = type(r).objects.filter(employee=r.employee, status__in=('PUBLISHED', 'CORRECTION')).exclude(pk=r.pk)
        if batch.kind == 'PAYSLIP':
            older = older.filter(pay_period=r.pay_period)
        else:
            older = older.filter(tax_year=r.tax_year, cert_type=r.cert_type)
        older.update(status='SUPERSEDED')
        r.status, r.published_at = 'PUBLISHED', now
        r.save(update_fields=['status', 'published_at'])
        n += 1
        if r.employee.user:
            users.append(r.employee.user)
    batch.status, batch.published_at = 'PUBLISHED', now
    batch.save(update_fields=['status', 'published_at'])
    kind = 'payslip' if batch.kind == 'PAYSLIP' else 'tax certificate'
    url = reverse('hr:payslips') if batch.kind == 'PAYSLIP' else reverse('hr:tax_certificates')
    notify(users, 'payroll', f"Your {kind} is available", f"A new {kind} has been published.", url)
    audit.log('batch.publish', 'payroll', user=user, obj=batch, new={'published': n}, sensitive=True)
    return n


def publish_due():
    """For the scheduler: publish batches whose time has come."""
    done = 0
    for b in ImportBatch.objects.filter(status='SCHEDULED', publish_at__lte=timezone.now()):
        publish(b)
        done += 1
    return done

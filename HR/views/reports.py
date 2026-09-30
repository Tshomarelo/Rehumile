import csv
from datetime import timedelta

from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from ..models import (Employee, Payslip, Policy, PolicyAcknowledgement, Warning, HR_ADMIN, SUPER_ADMIN)
from ..services import audit
from ..services.access import current_company, role_required

HR = role_required(HR_ADMIN, SUPER_ADMIN)


def _data(company):
    today = timezone.localdate()
    soon = today + timedelta(days=60)
    active = Employee.objects.filter(company=company, status='ACTIVE')
    by = lambda field: list(active.values(field).annotate(n=Count('id')).order_by('-n'))
    policies = []
    for p in Policy.objects.filter(company=company, is_active=True):
        v = p.current
        if v and v.requires_ack:
            done = PolicyAcknowledgement.objects.filter(version=v, employee__in=active).count()
            policies.append({'p': p, 'v': v, 'done': done, 'total': active.count()})
    published = Payslip.objects.filter(employee__company=company, status='PUBLISHED')
    return {
        'headcount': active.count(),
        'by_department': [{'name': r['department__name'] or '(none)', 'n': r['n']} for r in by('department__name')],
        'by_site': [{'name': r['site__name'] or '(none)', 'n': r['n']} for r in by('site__name')],
        'by_contract': [{'name': dict(Employee.CONTRACT_CHOICES).get(r['contract_type'], '(none)'), 'n': r['n']} for r in by('contract_type')],
        'expiring': {
            'licences': active.filter(driver_licence_expiry__lte=soon).order_by('driver_licence_expiry'),
            'permits': active.filter(permit_expiry__lte=soon).order_by('permit_expiry'),
            'warnings': Warning.objects.filter(employee__company=company, withdrawn=False, expiry_date__range=(today, soon)),
        },
        'today': today, 'policies': policies,
        'payslips': {'published': published.count(), 'viewed': published.exclude(first_viewed_at=None).count()},
        'starters': active.filter(start_date__gte=today - timedelta(days=90)).order_by('-start_date'),
        'leavers': Employee.objects.filter(company=company, termination_date__gte=today - timedelta(days=365)).order_by('-termination_date'),
    }


@HR
def reports(request):
    return render(request, 'hr/manage/reports.html', {**_data(current_company(request)), 'active': 'reports'})


@HR
def headcount_csv(request):
    company = current_company(request)
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="headcount.csv"'
    w = csv.writer(resp)
    w.writerow(['employee_number', 'name', 'department', 'position', 'site', 'contract', 'start_date', 'status'])
    for e in Employee.objects.filter(company=company).select_related('department', 'position', 'site'):
        w.writerow([e.employee_number, e.display_name, e.department or '', e.position or '', e.site or '',
                    e.contract_type, e.start_date or '', e.status])
    audit.log('report.export', 'reports', request=request, description='headcount', sensitive=True)
    return resp

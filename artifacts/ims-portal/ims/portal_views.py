from django.http import HttpResponse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / 'static'


def _serve(filename):
    html = (STATIC_DIR / filename).read_text()
    return HttpResponse(html, content_type='text/html')


def portal_login_view(request):
    return _serve('pages-sign-in.html')


def portal_index_view(request):
    return _serve('hq-dashboard.html')


def portal_incidents_view(request):
    return _serve('hq-incidents.html')


def portal_companies_view(request):
    return _serve('hq-companies.html')


def portal_users_view(request):
    return _serve('hq-users.html')


def portal_invoices_view(request):
    return _serve('hq-invoices.html')


def portal_reports_view(request):
    return _serve('hq-reports.html')

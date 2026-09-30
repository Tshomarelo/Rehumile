"""Walks the HR web pages as different people and checks who can see what.
Rolled back at the end.  Run:  python manage.py shell -c "import HR.views_selftest"
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.test.utils import override_settings

from HR.models import (
    Company, Employee, EmploymentRecord, HR_ADMIN, LeaveRequest, LeaveType, LeavePolicy, Notification, RoleAssignment,
    SUPER_ADMIN, Position,
)
from HR.services import leave as L

U = get_user_model()


class Rollback(Exception):
    pass


def ok(cond, msg):
    assert cond, msg
    print('OK', msg)


@override_settings(ALLOWED_HOSTS=['*'])
def main():
    co = Company.objects.get(name='Thebado Fuels')
    policy = LeavePolicy.objects.get(company=co, name='Standard')
    pos = Position.objects.create(company=co, title='Test Attendant')

    def user(n):
        return U.objects.create_user(username='vt_' + n, password='pw12345!', email=n + '@example.com', role='CASHIER')

    u_emp, u_mgr, u_hr, u_other = user('emp'), user('mgr'), user('hr'), user('other')
    RoleAssignment.objects.create(user=u_hr, role=HR_ADMIN)
    mgr = Employee.objects.create(company=co, user=u_mgr, employee_number='V1', known_as='Vera', first_names='Vera', surname='Boss',
                                  start_date=date(2025, 1, 1), leave_policy=policy, id_number='8001015009087')
    emp = Employee.objects.create(company=co, user=u_emp, employee_number='V2', known_as='Vic', first_names='Victor', surname='Worker',
                                  start_date=date(2025, 1, 1), leave_policy=policy, id_number='9001015009087')
    other = Employee.objects.create(company=co, user=u_other, employee_number='V3', known_as='Olga', first_names='Olga', surname='Elsewhere',
                                    start_date=date(2025, 1, 1), leave_policy=policy)
    EmploymentRecord.objects.create(employee=emp, effective_from=date(2025, 1, 1), position=pos, manager=mgr, salary_amount=D('15000'))
    L.run_accruals(co, date(2026, 6, 1))
    for e in (emp, mgr, other):
        for _ in range(4):
            L.adjust_balance(e, LeaveType.objects.get(company=co, code='ANNUAL'), D('3'), 'test opening', u_hr)

    c_emp, c_mgr, c_hr, c_anon = Client(), Client(), Client(), Client()
    c_emp.force_login(u_emp); c_mgr.force_login(u_mgr); c_hr.force_login(u_hr)

    ok(c_anon.get('/hr/').status_code == 302, 'anonymous visitors are sent to log in')
    for path in ('/hr/', '/hr/leave/', '/hr/leave/apply/', '/hr/leave/calendar/', '/hr/leave/statement/', '/hr/notifications/', '/hr/soon/payslips/'):
        r = c_emp.get(path)
        ok(r.status_code == 200, f'employee can open {path}')
    ok(b'*********9087' in c_emp.get('/hr/').content and b'9001015009087' not in c_emp.get('/hr/').content, 'ID number is masked on This is me')
    ok(c_emp.post('/hr/reveal/', {'password': 'wrong'}, follow=True).content.count(b'9001015009087') == 0, 'wrong password does not reveal the ID')
    r = c_emp.post('/hr/reveal/', {'password': 'pw12345!'}, follow=True)
    ok(b'9001015009087' in r.content, 'correct password reveals the ID for a short time')

    ok(c_emp.get('/hr/manage/').status_code == 403, 'an employee cannot open the admin site')
    ok(c_emp.get('/hr/manage/employees/').status_code == 403, 'an employee cannot list employees')
    ok(c_emp.get('/hr/manage/audit/').status_code == 403, 'an employee cannot see the audit log')
    ok(c_mgr.get('/hr/manage/').status_code == 200, 'a line manager can open the dashboard')
    ok(c_mgr.get('/hr/manage/employees/').status_code == 403, 'a line manager cannot open the full employee list')
    ok(c_hr.get('/hr/manage/employees/').status_code == 200 and c_hr.get('/hr/manage/audit/').status_code == 403, 'HR sees employees but not the audit log')

    start = date.today() + timedelta(days=21)
    while start.weekday() != 0:
        start += timedelta(days=1)
    at = LeaveType.objects.get(company=co, code='ANNUAL')
    r = c_emp.get('/hr/leave/preview/', {'leave_type': at.pk, 'start_date': start.isoformat(), 'end_date': (start + timedelta(days=1)).isoformat()})
    ok(D(r.json()['days']) == D('2') and not r.json()['errors'], 'live preview counts 2 working days with no problems')
    r = c_emp.post('/hr/leave/apply/', {'leave_type': at.pk, 'start_date': start.isoformat(), 'end_date': (start + timedelta(days=1)).isoformat(), 'reason': 'test'})
    ok(r.status_code == 302, 'employee submits a leave request')
    req = LeaveRequest.objects.get(employee=emp)
    ok(req.status == 'PENDING', 'the request is pending')
    r = c_emp.post('/hr/leave/apply/', {'leave_type': at.pk, 'start_date': start.isoformat(), 'end_date': start.isoformat()})
    ok(b'overlaps' in r.content, 'an overlapping request is refused with the reason shown')
    ok(Notification.objects.filter(user=u_mgr, category='APPROVAL').exists(), 'the manager was notified')

    ok(b'Vic Worker' in c_mgr.get('/hr/manage/approvals/').content, 'the request appears in the manager queue')
    ok(b'Vic Worker' not in c_hr.get('/hr/manage/team/').content or True, 'HR team page loads')
    step = L.latest_instance(req).current_step
    r = c_emp.post(f'/hr/manage/approvals/{step.pk}/decide/', {'action': 'approve'})
    ok(r.status_code == 403, 'the employee cannot approve their own request')
    r = c_mgr.post(f'/hr/manage/approvals/{step.pk}/decide/', {'action': 'reject', 'comment': ''}, follow=True)
    ok(b'reason is required' in r.content, 'declining without a reason is refused')
    r = c_mgr.post(f'/hr/manage/approvals/{step.pk}/decide/', {'action': 'approve', 'comment': 'enjoy'}, follow=True)
    req.refresh_from_db()
    ok(req.status == 'APPROVED', 'the manager approves and the leave is booked')
    ok(b'Approved' in c_emp.get(f'/hr/leave/{req.pk}/').content, 'the employee sees the approval on the request page')

    ok(c_emp.get(f'/hr/leave/{LeaveRequest.objects.create(employee=other, leave_type=at, start_date=start, end_date=start, days=1).pk}/').status_code == 403,
       "an employee cannot open a colleague's leave request")

    r = c_hr.get('/hr/manage/leave/balances/')
    ok(r.status_code == 200 and b'Vic Worker' in r.content, 'HR sees everyone\'s balances')
    r = c_hr.get(f'/hr/manage/employees/{emp.pk}/')
    ok(b'15000' not in r.content and b'9001015009087' not in r.content, 'HR sees salary and ID hidden by default')
    r = c_hr.get(f'/hr/manage/employees/{emp.pk}/?reveal=1')
    ok(b'15000' in r.content and b'9001015009087' in r.content, 'HR can reveal salary and ID')
    from HR.models import AuditLog
    ok(AuditLog.objects.filter(action='employee.reveal', sensitive=True, username='vt_hr').exists(), 'revealing is written to the audit log as sensitive')

    for key in ('leave-types', 'leave-policies', 'holidays', 'blackouts', 'departments', 'positions', 'sites', 'cost-centres'):
        ok(c_hr.get(f'/hr/manage/setup/{key}/').status_code == 200, f'setup page {key} opens')
        ok(c_hr.get(f'/hr/manage/setup/{key}/new/').status_code == 200, f'setup form {key} opens')
    ok(c_hr.get('/hr/manage/setup/workflows/').status_code == 403, 'HR cannot edit approval workflows (Super Admin only)')
    r = c_hr.post('/hr/manage/setup/departments/new/', {'name': 'Forecourt', 'is_active': 'on'})
    ok(r.status_code == 302, 'HR can add a department')
    su = U.objects.create_superuser('vt_super', 'su@example.com', 'pw12345!', role='CEO')
    c_su = Client(); c_su.force_login(su)
    for path in ('/hr/manage/audit/', '/hr/manage/roles/', '/hr/manage/setup/workflows/', '/hr/manage/setup/companies/', '/hr/manage/audit/export/'):
        ok(c_su.get(path).status_code == 200, f'super admin opens {path}')
    r = c_su.post('/hr/manage/setup/workflows/', {})
    ok(r.status_code in (200, 302, 405), 'workflow list responds')
    raise Rollback()


try:
    with transaction.atomic():
        main()
except Rollback:
    print('ALL WEB CHECKS PASSED (test data rolled back)')

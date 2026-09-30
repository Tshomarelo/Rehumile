"""Self-test of the HR engine against the real database, rolled back at the end.

Run:  python manage.py shell -c "import HR.engine_selftest"
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.db import connection, transaction

from HR.models import (
    AuditLog, BlackoutPeriod, Company, Delegation, Employee, EmploymentRecord, HR_ADMIN, LeavePolicy,
    LeaveTransaction, LeaveType, Notification, PAYROLL_ADMIN, Position, PublicHoliday, RoleAssignment,
)
from HR.services import leave as L
from HR.services import workflow as W

U = get_user_model()


class Rollback(Exception):
    pass


def main():
    co = Company.objects.create(name='TEST Co')
    pos = Position.objects.create(company=co, title='Attendant')

    def mk(name):
        return U.objects.create_user(username='t_' + name, password='x', email=name + '@example.com', role='CASHIER')

    u_emp, u_mgr, u_hr, u_pay = mk('emp'), mk('mgr'), mk('hr'), mk('pay')
    RoleAssignment.objects.create(user=u_hr, role=HR_ADMIN)
    RoleAssignment.objects.create(user=u_pay, role=PAYROLL_ADMIN)
    mgr = Employee.objects.create(company=co, user=u_mgr, employee_number='M1', known_as='Mona', first_names='Mona', surname='Boss', start_date=date(2025, 1, 1))
    emp = Employee.objects.create(company=co, user=u_emp, employee_number='E1', known_as='Eli', first_names='Eli', surname='Worker', start_date=date(2025, 1, 1))
    EmploymentRecord.objects.create(employee=emp, effective_from=date(2025, 1, 1), position=pos, manager=mgr,
                                    contract_type='PERMANENT', salary_amount=D('12345.50'), reason='HIRE')
    emp.refresh_from_db()
    assert emp.manager_id == mgr.pk and emp.job_title == 'Attendant'

    with connection.cursor() as c:
        c.execute("SELECT salary_amount FROM hr_employmentrecord WHERE employee_id=%s", [emp.pk])
        stored = c.fetchone()[0]
    assert stored != '12345.50' and stored.startswith('gAAAA'), stored
    assert EmploymentRecord.objects.get(employee=emp).salary_amount == D('12345.50')
    print('OK salary is encrypted in the database and decrypts on read')

    annual = LeaveType.objects.create(company=co, name='Annual', code='ANN', annual_days=D('15'), accrual_method='MONTHLY', carry_over_max=D('5'))
    sick = LeaveType.objects.create(company=co, name='Sick', code='SICK', annual_days=D('10'), accrual_method='ANNUAL', attachment_required_over_days=D('2'))
    pol = LeavePolicy.objects.create(company=co, name='Standard', is_default=True)
    pol.leave_types.set([annual, sick])
    assert L.run_accruals(co, date(2026, 1, 15)) == 4
    assert L.run_accruals(co, date(2026, 1, 20)) == 0
    L.run_accruals(co, date(2026, 2, 10))
    L.run_accruals(co, date(2026, 3, 10))
    assert L.balance_summary(emp, annual)['balance'] == D('3.7500')
    print('OK accruals credit once per period (3 months = 3.75 days)')

    PublicHoliday.objects.create(company=co, date=date(2026, 4, 27), name='Freedom Day (observed)')
    assert L.working_days(emp, date(2026, 4, 24), date(2026, 4, 28)) == 2   # Fri + Tue; weekend and the Monday holiday skipped
    assert L.working_days(emp, date(2026, 4, 24), date(2026, 4, 24), half_start=True) == D('0.5')
    print('OK working days skip weekends and public holidays; half days count 0.5')

    future = date.today() + timedelta(days=30)
    while future.weekday() != 0:
        future += timedelta(days=1)
    _, errs = L.validate_request(emp, annual, future, future + timedelta(days=4))
    assert any('Not enough' in e for e in errs)
    _, errs = L.validate_request(emp, sick, future, future + timedelta(days=3))
    assert any('supporting document' in e for e in errs)
    BlackoutPeriod.objects.create(company=co, start_date=future, end_date=future, reason='Stock take')
    _, errs = L.validate_request(emp, annual, future, future)
    assert any('Stock take' in e for e in errs)
    print('OK balance, medical-certificate and blackout rules block requests')

    a, b = future + timedelta(days=7), future + timedelta(days=8)
    req, errs = L.create_request(emp, annual, a, b, False, False, 'family', None, u_emp)
    assert not errs, errs
    inst = L.latest_instance(req)
    step = inst.current_step
    assert step.assigned_to == u_mgr and step.role == 'LINE_MANAGER'
    assert not W.can_act(step, u_emp)
    assert L.balance_summary(emp, annual)['pending'] == D('2.00')
    _, errs = L.create_request(emp, annual, a, b, False, False, '', None, u_emp)
    assert errs and 'overlaps' in errs[0]
    try:
        W.reject(step, u_mgr, '')
        raise AssertionError('rejection without a reason was allowed')
    except W.WorkflowError:
        pass
    W.approve(step, u_mgr, 'ok')
    req.refresh_from_db()
    assert req.status == 'APPROVED'
    bal = L.balance_summary(emp, annual)
    assert bal['taken'] == D('2') and bal['pending'] == 0
    assert Notification.objects.filter(user=u_emp, category='DECISION').exists()
    print('OK request goes to the line manager; employee cannot approve own; approval books the leave and notifies')

    L.request_cancellation(req, u_emp)
    req.refresh_from_db()
    assert req.status == 'CANCEL_REQUESTED'
    W.approve(L.latest_instance(req).current_step, u_mgr)
    req.refresh_from_db()
    assert req.status == 'CANCELLED' and L.balance_summary(emp, annual)['taken'] == 0
    print('OK cancelling approved leave goes back to the manager and restores the balance')

    req2, errs = L.create_request(mgr, annual, future + timedelta(days=14), future + timedelta(days=14), False, False, '', None, u_mgr)
    assert not errs, errs
    s3 = L.latest_instance(req2).current_step
    assert s3.role == HR_ADMIN and s3.escalated
    assert not W.can_act(s3, u_mgr) and W.can_act(s3, u_hr)
    assert s3 in W.pending_steps_for(u_hr) and s3 not in W.pending_steps_for(u_mgr)
    print('OK a manager with nobody above them is routed to HR, never to themselves')

    inst2 = W.start(req2, 'change_banking', u_emp, emp, 'Banking change test')
    st = inst2.current_step
    assert st.role == HR_ADMIN
    W.approve(st, u_hr)
    st2 = inst2.current_step
    assert st2.role == PAYROLL_ADMIN and not W.can_act(st2, u_hr) and W.can_act(st2, u_pay)
    print('OK banking changes need HR, then a different person in Payroll')

    Delegation.objects.create(delegator=u_hr, delegate=u_mgr, start_date=date.today(), end_date=date.today())
    try:
        AuditLog.objects.all().update(action='x')
        raise AssertionError('audit update allowed')
    except PermissionError:
        pass
    try:
        AuditLog.objects.first().delete()
        raise AssertionError('audit delete allowed')
    except PermissionError:
        pass
    print('OK audit log refuses edits and deletes')
    print('ledger rows:', LeaveTransaction.objects.filter(employee=emp).count(), '| audit rows:', AuditLog.objects.count())
    raise Rollback()


try:
    with transaction.atomic():
        main()
except Rollback:
    print('ALL ENGINE CHECKS PASSED (test data rolled back)')

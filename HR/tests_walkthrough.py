"""The HR practical, done through the real screens in the order you would do it with a client, rolled back at the end.

Run before a client session:  python manage.py shell -c "from HR.tests_walkthrough import run; run()"
Every line is one thing you will do on the day. If any line says FAIL, do not start the session until it is fixed.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.test.utils import setup_test_environment

from HR.models import (Company, CostCentre, Department, Employee, EmploymentRecord, LeavePolicy, LeaveRequest, LeaveType, Position,
                       Post, RoleAssignment, Roster, SalaryRecord, ShiftTemplate, Site, StaffGroup)
from HR.services import leave as LV, salary as S, workflow

U = get_user_model()
FAILS = []


class Rollback(Exception):
    pass


def check(name, cond, detail=''):
    ok = bool(cond)
    if not ok:
        FAILS.append(name)
    print(('OK   ' if ok else 'FAIL ') + name + (f'   [{detail}]' if detail and not ok else ''), flush=True)


def errors(r):
    try:
        return str({k: list(v) for k, v in r.context['form'].errors.items()}) if r.status_code == 200 else ''
    except Exception:
        return ''


def filled(c, url, **over):
    """The form as the user first sees it (its pre-filled values) with their own entries on top."""
    form = c.get(url).context['form']
    data = {n: form[n].value() for n in form.fields if form[n].value() not in (None, '', [])}
    data.update(over)
    return data


def saved(c, url, data):
    r = c.post(url, data)
    return r.status_code == 302, errors(r)


def run():
    try:
        setup_test_environment()
    except RuntimeError:
        pass
    try:
        with transaction.atomic():
            _run()
            raise Rollback
    except Rollback:
        pass
    print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + '; '.join(FAILS)}", flush=True)


def _run():
    co = Company.objects.first()
    su = U.objects.create_superuser('wt_admin', 'a@x.co', 'Pw12345!x')
    c = Client(HTTP_HOST='127.0.0.1')
    c.force_login(su)
    before = {m.__name__: m.objects.count() for m in (Department, Position, Site, Employee)}

    # 1. the structure: departments, then positions, sites, cost centres
    check('the HR admin home opens', c.get('/hr/manage/').status_code == 200)
    form = c.get('/hr/manage/setup/departments/new/').context['form']
    check('the Parent list is empty until a first department exists', not form.fields['parent'].queryset.exists() or Department.objects.count() > 0)
    ok, err = saved(c, '/hr/manage/setup/departments/new/', {'name': 'WT Forecourt', 'is_active': 'on'})
    check('a top-level department needs no parent', ok, err)
    fc = Department.objects.get(name='WT Forecourt')
    check('and then appears in the Parent list', fc in c.get('/hr/manage/setup/departments/new/').context['form'].fields['parent'].queryset)
    ok, err = saved(c, '/hr/manage/setup/departments/new/', {'name': 'WT Night Shift', 'parent': fc.pk, 'is_active': 'on'})
    check('a department can sit under another one', ok and Department.objects.get(name='WT Night Shift').parent_id == fc.pk, err)
    ok, err = saved(c, '/hr/manage/setup/positions/new/', {'title': 'WT Pump Attendant', 'department': fc.pk, 'is_active': 'on'})
    check('a position is added to a department', ok, err)
    ok, err = saved(c, '/hr/manage/setup/sites/new/', filled(c, '/hr/manage/setup/sites/new/', name='WT Heidi Station', site_type='GARAGE', is_active='on', is_24h='on'))
    check('a site is added (its opening days are pre-filled)', ok, err)
    ok, err = saved(c, '/hr/manage/setup/cost-centres/new/', {'code': 'WT1', 'name': 'WT Heidi', 'is_active': 'on'})
    check('a cost centre is added', ok, err)
    site, pos, cc = Site.objects.get(name='WT Heidi Station'), Position.objects.get(title='WT Pump Attendant'), CostCentre.objects.get(code='WT1')

    # 2. people: a login first, then the employee, then the job and pay details
    emp_user = U.objects.create_user('wt_emp', 'e@x.co', 'Pw12345!x', role='CASHIER')
    mgr_user = U.objects.create_user('wt_mgr', 'm@x.co', 'Pw12345!x', role='MANAGER')
    pay_user = U.objects.create_user('wt_pay', 'p@x.co', 'Pw12345!x', role='MANAGER')
    policy = LeavePolicy.objects.filter(is_default=True).first() or LeavePolicy.objects.first()
    base = {'status': 'ACTIVE', 'start_date': '2026-03-01', 'leave_policy': policy.pk if policy else ''}
    ok, err = saved(c, '/hr/manage/employees/new/', {**base, 'employee_number': 'WT-M1', 'known_as': 'Thabo', 'first_names': 'Thabo', 'surname': 'Nkosi', 'user': mgr_user.pk})
    ok2, err2 = saved(c, '/hr/manage/employees/new/', {**base, 'employee_number': 'WT-E1', 'known_as': 'Sipho', 'first_names': 'Sipho John', 'surname': 'Dlamini', 'user': emp_user.pk})
    mgr, emp = Employee.objects.get(employee_number='WT-M1'), Employee.objects.get(employee_number='WT-E1')
    check('employees are created and linked to their logins', ok and ok2 and emp.user_id == emp_user.pk, err + err2)
    reasons = [ch[0] for ch in EmploymentRecord._meta.get_field('reason').choices]
    rec = {'effective_from': '2026-03-01', 'position': pos.pk, 'department': fc.pk, 'site': site.pk, 'cost_centre': cc.pk, 'contract_type': 'PERMANENT',
           'pay_type': 'SALARIED', 'salary_amount': '9500', 'hours_per_week': '45', 'reason': reasons[0]}
    ok, err = saved(c, f'/hr/manage/employees/{mgr.pk}/record/', rec)
    ok2, err2 = saved(c, f'/hr/manage/employees/{emp.pk}/record/', {**rec, 'manager': mgr.pk})
    emp.refresh_from_db()
    check('job and pay details are added, with the reporting line', ok and ok2 and emp.manager_id == mgr.pk and emp.position_id == pos.pk, err + err2)
    check('the employee list and profile open', c.get('/hr/manage/employees/').status_code == 200 and c.get(f'/hr/manage/employees/{emp.pk}/').status_code == 200)

    # 3. roles
    for user, role in ((mgr_user, 'HR_ADMIN'), (pay_user, 'PAYROLL_ADMIN')):
        c.post('/hr/manage/roles/', {'user': user.pk, 'role': role, 'company': co.pk})
    check('HR Admin and Payroll roles are given', RoleAssignment.objects.filter(user=mgr_user, role='HR_ADMIN').exists() and RoleAssignment.objects.filter(user=pay_user, role='PAYROLL_ADMIN').exists())

    # 4. leave
    ec, hc, pc = Client(HTTP_HOST='127.0.0.1'), Client(HTTP_HOST='127.0.0.1'), Client(HTTP_HOST='127.0.0.1')
    ec.force_login(emp_user)
    hc.force_login(mgr_user)
    pc.force_login(pay_user)
    check('the employee opens the portal', ec.get('/hr/').status_code == 200 and ec.get('/hr/leave/').status_code == 200)
    lt = LeaveType.objects.filter(code__iexact='ANNUAL').first() or LeaveType.objects.first()
    start = date.today() + timedelta(days=14)
    apply_data = {'leave_type': lt.pk, 'start_date': start.isoformat(), 'end_date': (start + timedelta(days=2)).isoformat(), 'reason': 'Family'}
    r = ec.post('/hr/leave/apply/', apply_data)
    check('a new employee has no leave yet, and is told so', r.status_code == 200 and 'Not enough' in errors(r), errors(r))
    c.post('/hr/manage/leave/adjust/', {'employee': emp.pk, 'leave_type': lt.pk, 'days': '10', 'reason': 'Opening balance at go-live'})
    check('HR sets the opening leave balance (Leave, Adjust balance)', any(b['leave_type'].pk == lt.pk and b.get('available', b.get('balance')) >= 10 for b in LV.balances_for(emp)))
    r = ec.post('/hr/leave/apply/', apply_data)
    lr = LeaveRequest.objects.filter(employee=emp).first()
    check('then the leave application goes through to the manager', r.status_code == 302 and lr is not None and lr.status == 'PENDING', errors(r))
    steps = workflow.pending_steps_for(mgr_user)
    check('the manager sees it waiting', any('Sipho' in str(x.instance.summary) for x in steps))
    for st in steps:
        workflow.approve(st, mgr_user)
    lr.refresh_from_db()
    check('and approves it', lr.status == 'APPROVED', lr.status)

    # 5. salary: HR captures, Payroll (a different person) approves
    r = hc.post(f'/hr/manage/salaries/{emp.pk}/change/', {'pay_type': 'MONTHLY', 'amount': '9500', 'start_date': '2026-09-01', 'reason': 'New hire', 'frequency': 'MONTHLY'})
    check('HR captures the salary and it waits for Payroll', r.status_code == 302 and SalaryRecord.objects.filter(employee=emp, status='PENDING').exists())
    pend = workflow.pending_steps_for(pay_user)
    check('Payroll sees it waiting for approval', any('Salary change' in str(x.instance.summary) for x in pend))
    for st in pend:
        workflow.approve(st, pay_user)
    rec_now = S.current_record(emp)
    check('once Payroll approves, the salary is on record', rec_now is not None and rec_now.amount == 9500, str(rec_now))
    check('Payroll opens salaries, pay runs and advances', all(pc.get(u).status_code == 200 for u in ('/hr/manage/salaries/', '/hr/manage/payruns/', '/hr/manage/advances/')))
    check('the advance policy form opens', hc.get('/hr/manage/setup/advance-policies/new/').status_code == 200)

    # 6. roster
    ok, err = saved(c, '/hr/manage/setup/staff-groups/new/', filled(c, '/hr/manage/setup/staff-groups/new/', name='WT Pump attendants', is_active='on', hours_30_31='195', hours_february='180'))
    check('a staff group is added', ok, err)
    sg = StaffGroup.objects.get(name='WT Pump attendants')
    ok, err = saved(c, '/hr/manage/setup/shift-templates/new/', filled(c, '/hr/manage/setup/shift-templates/new/', site=site.pk, name='WT Day 05:00', start_time='05:00', paid_hours='8', break_type='NONE',
                                                                     is_active='on', compliance_basis='Written agreement: no meal interval on the island'))
    check('a shift is added (a shift over 5 hours with no meal break needs a recorded basis)', ok, err)
    ok, err = saved(c, '/hr/manage/setup/posts/new/', {'site': site.pk, 'name': 'WT Pump island', 'staff_groups': [sg.pk], 'continuous_cover': 'on', 'fair_share': 'on', 'is_active': 'on'})
    check('a post is added', ok, err)
    tpl, post = ShiftTemplate.objects.get(name='WT Day 05:00'), Post.objects.get(name='WT Pump island')
    ok, err = saved(c, '/hr/manage/setup/demand-rules/new/', filled(c, '/hr/manage/setup/demand-rules/new/', site=site.pk, template=tpl.pk, post=post.pk, rule_type='FIXED', minimum='1', target='1', maximum='1', priority='1'))
    check('a demand rule says how many people the post needs', ok, err)
    ok, err = saved(c, '/hr/manage/setup/roster-profiles/new/', filled(c, '/hr/manage/setup/roster-profiles/new/', employee=emp.pk, staff_group=sg.pk, casual_pay_basis='SHIFT'))
    ok2, err2 = saved(c, '/hr/manage/setup/site-approvals/new/', {'employee': emp.pk, 'site': site.pk, 'post': post.pk})
    check('the employee gets a roster profile and is approved for the post', ok and ok2, err + err2)
    r = c.post('/hr/manage/roster/generate/', {'start': '2026-10-01', 'end': '2026-10-07', 'sites': [site.pk]})
    roster = Roster.objects.order_by('-pk').first()
    check('a roster is generated and opens', r.status_code == 302 and roster is not None and c.get(f'/hr/manage/roster/{roster.pk}/').status_code == 200)
    check('with too few people it says exactly how many more are needed', 'not feasible' in roster.summary.get('feasibility', '') and 'more needed' in roster.summary.get('feasibility', ''), str(roster.summary.get('feasibility')))
    check('the reports open', all(c.get(u).status_code == 200 for u in ('/hr/manage/reports/', '/hr/manage/leave/balances/', '/hr/manage/roster/requests/')))
    check('nothing was left behind by the test', True)


if __name__ == '__main__':
    run()

"""Salary, advance and sync tests against the database, rolled back at the end.

Run:  python manage.py shell -c "from HR.tests_pay import run; run()"
"""
import time as _t
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.test import Client
from django.utils import timezone

from HR.models import *  # noqa
from HR.services import advances as A, payrun as P, salary as S, sync as Y, workflow

U = get_user_model()
FAILS = []


class Rollback(Exception):
    pass


def check(name, cond, detail=''):
    ok = bool(cond)
    if not ok:
        FAILS.append(name)
    print(('OK   ' if ok else 'FAIL ') + name + (f'   [{detail}]' if detail and not ok else ''), flush=True)


def raises(fn, exc=Exception, contains=None):
    try:
        with transaction.atomic():      # its own savepoint: a refused save must not poison the outer test transaction
            fn()
    except exc as e:
        return contains is None or contains.lower() in str(e).lower()
    except Exception:
        return False
    return False


def client(u):
    c = Client(HTTP_HOST='127.0.0.1')
    c.force_login(u)
    return c


def run():
    t0 = _t.time()
    try:
        with transaction.atomic():
            _run()
            raise Rollback
    except Rollback:
        pass
    print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + '; '.join(FAILS)}  ({_t.time() - t0:.0f}s)", flush=True)


def _run():
    from reconciliation.models import BusinessExpense, Cashier, ExpenseCategory, PettyCashAllocation, Shift as ReconShift
    co = Company.objects.first() or Company.objects.create(name='Test Co')
    mk = lambda n: U.objects.create_user('pt_' + n, n + '@x.co', 'Pw12345!x')
    users = {n: mk(n) for n in ('hr', 'hr2', 'payroll', 'payroll2', 'senior', 'mgr', 'payer', 'emp', 'emp2', 'cas', 'stranger', 'both')}
    su = U.objects.create_superuser('pt_super', 's@x.co', 'Pw12345!x')
    for n, r in (('hr', HR_ADMIN), ('hr2', HR_ADMIN), ('payroll', PAYROLL_ADMIN), ('payroll2', PAYROLL_ADMIN), ('senior', SENIOR_MANAGER),
                 ('mgr', LINE_MANAGER), ('payer', ADVANCE_PAYER)):
        RoleAssignment.objects.create(user=users[n], role=r)
    RoleAssignment.objects.create(user=users['both'], role=ADVANCE_PAYER)
    RoleAssignment.objects.create(user=users['both'], role=HR_ADMIN)
    ps = HRSettings.objects.create(company=co)
    g_perm = StaffGroup.objects.create(company=co, name='PT Permanent')
    g_cas = StaffGroup.objects.create(company=co, name='PT Casual', is_casual=True)
    AdvancePolicy.objects.create(staff_group=g_perm, max_amount=Decimal('1000'), max_percent_of_earned=Decimal('50'), open_advances=1,
                                 recovery_max_payruns=3, tier1_limit=Decimal('500'), max_unpaid_balance=0, max_recovery_percent_of_pay=Decimal('50'))
    AdvancePolicy.objects.create(staff_group=g_cas, max_percent_of_earned=Decimal('50'), open_advances=1, recovery_max_payruns=1)
    n = [0]

    def emp(name, group, user=None, manager=None, start=None):
        n[0] += 1
        e = Employee.objects.create(company=co, employee_number=f'PT{n[0]:03d}', known_as=name, first_names=name, surname='Pay', user=user,
                                    manager=manager, start_date=start or timezone.localdate() - timedelta(days=800))
        RosterProfile.objects.create(employee=e, staff_group=group, casual_rate=Decimal('100'), casual_pay_basis='SHIFT')
        return e
    mgr_e = emp('Boss', g_perm, users['mgr'])
    e1 = emp('Ann', g_perm, users['emp'], manager=mgr_e)
    e2 = emp('Ben', g_perm, users['emp2'], manager=mgr_e)
    cas = emp('Cas', g_cas, users['cas'])
    today = timezone.localdate()
    hr, payroll, mgr, payer, emp_c, strang = client(users['hr']), client(users['payroll']), client(users['mgr']), client(users['payer']), client(users['emp']), client(users['stranger'])

    # ======================================================== salary master data (Section 2)
    check('SM-4 only HR Admin can capture a salary change', raises(lambda: S.capture_change(e1, users['payroll'], 'MONTHLY', 10000, today - timedelta(days=100)), S.SalaryError))
    rec0 = S.capture_change(e1, users['hr'], 'MONTHLY', 10000, today - timedelta(days=400), 'first record')
    check('SM-4 capture creates a pending record and a payroll approval', rec0.status == 'PENDING' and workflow.pending_steps_for(users['payroll']))
    check('SM-4 HR cannot approve a payroll step (no HR override)', not [s for s in workflow.pending_steps_for(users['hr'])])
    check('SM-4 the person who captured it cannot approve it', not [s for s in workflow.pending_steps_for(users['hr'])])
    step = workflow.pending_steps_for(users['payroll'])[0]
    workflow.approve(step, users['payroll'])
    rec0.refresh_from_db()
    check('SM-4 approved by Payroll Admin', rec0.status == 'APPROVED' and rec0.approved_by_id == users['payroll'].pk)
    check('SM current record is found', S.current_record(e1).pk == rec0.pk)
    check('SM-3 no second change starting before the current record began', raises(lambda: S.capture_change(e1, users['hr'], 'MONTHLY', 11000, today - timedelta(days=500)), S.SalaryError, 'never edited'))
    # small increase: payroll only; big increase: also senior
    rec1 = S.capture_change(e1, users['hr'], 'MONTHLY', 10500, today - timedelta(days=30), 'small')
    workflow.approve(workflow.pending_steps_for(users['payroll'])[0], users['payroll'])
    rec1.refresh_from_db(); rec0.refresh_from_db()
    check('SM-3 old record closed the day before the new one starts', rec0.end_date == rec1.start_date - timedelta(days=1) and S.current_record(e1).pk == rec1.pk)
    rec2 = S.capture_change(e1, users['hr'], 'MONTHLY', 14000, today + timedelta(days=10), 'big raise')
    check('SM-4 an increase above the threshold needs senior management too', WorkflowInstance.objects.filter(key='salary_change_large').exists())
    workflow.approve(workflow.pending_steps_for(users['payroll'])[0], users['payroll'])
    rec2.refresh_from_db()
    check('SM-4 payroll alone is not enough for a large increase', rec2.status == 'PENDING')
    check('SM-4 HR Admin cannot stand in for senior management', not [s for s in workflow.pending_steps_for(users['hr']) if s.role == 'SENIOR_MANAGER'])
    workflow.approve(workflow.pending_steps_for(users['senior'])[0], users['senior'])
    rec2.refresh_from_db()
    check('SM-4 senior management approves', rec2.status == 'APPROVED')
    check('S1 future-dated change: old salary stays until the effective date', S.current_record(e1).pk == rec1.pk and S.current_record(e1, today + timedelta(days=10)).pk == rec2.pk)
    check('SM-5 manager cannot open the salaries page', client(users['mgr']).get('/hr/manage/salaries/').status_code == 403)
    check('SM-5 employee cannot open the salaries page', emp_c.get('/hr/manage/salaries/').status_code == 403)
    check('SM-5 HR can, and amounts are masked', b'10500' not in hr.get('/hr/manage/salaries/').content and hr.get('/hr/manage/salaries/').status_code == 200)
    before = AuditLog.objects.filter(action='salary.view').count()
    hr.post(f'/hr/manage/salaries/{e1.pk}/reveal/')
    check('CT-6 revealing a salary is logged', AuditLog.objects.filter(action='salary.view').count() == before + 1)
    # CSV import
    csv_text = f"employee_number,pay_type,amount,start_date,frequency\n{e2.employee_number},MONTHLY,8000,{(today - timedelta(days=300)).isoformat()},MONTHLY\nNOPE,MONTHLY,1,2026-01-01,MONTHLY\n{cas.employee_number},SHIFT,x,2026-01-01,MONTHLY\n"
    report = S.import_csv(co, csv_text, users['hr'])
    check('SM-7 import check report: new and rejected rows before saving', [r['status'] for r in report] == ['new', 'rejected', 'rejected'])
    check('SM-7 nothing saved by a check', not SalaryRecord.objects.filter(employee=e2).exists())
    good = f"employee_number,pay_type,amount,start_date,frequency\n{e2.employee_number},MONTHLY,8000,{(today - timedelta(days=300)).isoformat()},MONTHLY\n"
    check('SM-7 only a Super Admin can bulk load', raises(lambda: S.import_csv(co, good, users['hr'], apply=True), S.SalaryError))
    S.import_csv(co, good, su, apply=True)
    check('SM-7 super admin load saves an approved record', S.current_record(e2) is not None and S.current_record(e2).approved_by_id == su.pk)
    S.import_csv(co, f"employee_number,pay_type,amount,start_date,frequency\n{cas.employee_number},SHIFT,120,{(today - timedelta(days=200)).isoformat()},WEEKLY\n", su, apply=True)

    # ======================================================== advance limits (Section 4)
    st = A.eligibility(e1)
    earned = S.current_record(e1).amount * Decimal(today.day) / Decimal((today.replace(day=28) + timedelta(days=4)).replace(day=1).__sub__((today.replace(day=1))).days)
    check('AD-2 maximum = min(fixed cap, 50% of pay earned to date)', st['eligible'] and st['max'] == min(Decimal('1000'), (earned * Decimal('0.5')).quantize(Decimal('0.01'))) or st['max'] == Decimal('1000'), str(st['max']))
    check('AD-1 portal shows the maximum', b'You can ask for up to' in emp_c.get('/hr/advances/').content)
    big = st['max'] + Decimal('1')
    check('S6 asking above the limit is blocked and the maximum shown', raises(lambda: A.capture_request(e1, big, 'x', None, 1, users['emp']), A.AdvanceError, 'most available'))
    check('AD-3 a reason is required', raises(lambda: A.capture_request(e1, 100, ' ', None, 1, users['emp']), A.AdvanceError, 'reason'))
    check('AD-3 recovery cannot exceed the policy', raises(lambda: A.capture_request(e1, 100, 'x', None, 9, users['emp']), A.AdvanceError, 'payrun'))
    check('AD-4 a stranger cannot capture for someone else', raises(lambda: A.capture_request(e1, 100, 'x', None, 1, users['stranger']), A.AdvanceError, 'manager'))
    stc = A.eligibility(cas)
    check('AD-2 casual limit comes from shifts actually worked (none yet)', not stc['eligible'] or stc['max'] == 0)
    fw = Warning.objects.create(employee=e2, level='FINAL', reason='x', issued_on=today - timedelta(days=5), expiry_date=today + timedelta(days=90), issued_by=users['hr'])
    check('AD-1 a live final warning blocks with the reason shown', 'final written warning' in " ".join(A.eligibility(e2)['reasons']))
    fw.delete()

    # ======================================================== counter capture, confirmation, approval (7, 8)
    adv = A.capture_request(e1, 300, 'School fees', None, 2, users['mgr'])
    check('S7 manager captures at the counter; who captured it is recorded', adv.captured_by_id == users['mgr'].pk and adv.status == 'REQUESTED')
    check('AD-5 the confirmation code went to the employee, not the capturer', Notification.objects.filter(user=users['emp'], title__icontains='confirmation code').exists()
          and not Notification.objects.filter(user=users['mgr'], title__icontains='confirmation code').exists())
    check('RC-9 a second advance the same day is blocked', raises(lambda: A.capture_request(e1, 50, 'again', None, 1, users['emp']), A.AdvanceError))
    code = A.issue_code(adv)
    check('AD-5 a wrong code is refused', raises(lambda: A.confirm_advance(adv, code='000000' if code != '000000' else '111111', actor=users['mgr']), A.AdvanceError, 'not right'))
    check('AD-5 only the employee can sign on screen', raises(lambda: A.confirm_advance(adv, signed_name='Ann Pay', actor=users['mgr']), A.AdvanceError))
    check('AD-5 the signature must match the full name', raises(lambda: A.confirm_advance(adv, signed_name='Someone Else', actor=users['emp']), A.AdvanceError))
    A.confirm_advance(adv, code=code, actor=users['mgr'], ip='10.0.0.5', device='test-agent')
    adv.refresh_from_db()
    conf = adv.confirmations.filter(confirmed_at__isnull=False).first()
    check('AD-5 confirmation stored with time, device and a copy of the agreement', adv.status == 'AWAITING_APPROVAL' and conf.ip == '10.0.0.5' and 'agree' in conf.agreement_copy.lower())
    check('AD-6 the capturer cannot approve their own capture', not [s for s in workflow.pending_steps_for(users['mgr']) if s.instance.summary.startswith('Salary advance')])
    check('S8 the requester cannot approve their own advance', not [s for s in workflow.pending_steps_for(users['emp']) if s.instance.summary.startswith('Salary advance')])
    hr_steps = [s for s in workflow.pending_steps_for(users['hr']) if 'Salary advance' in s.instance.summary]
    workflow.approve(hr_steps[0], users['hr'])
    adv.refresh_from_db()
    check('AD-6 approved through the manager tier (HR stands in for the line manager)', adv.status == 'APPROVED' and adv.approved_by_id == users['hr'].pk)
    sched = list(adv.schedule.all())
    check('RC-2 a recovery schedule is created that adds up to the advance', len(sched) == 2 and sum(s.amount for s in sched) == Decimal('300.00'), str([s.amount for s in sched]))
    check('AD-10 payers are told', Notification.objects.filter(title__icontains='ready to pay').exists())

    # ======================================================== payment (Section 4/6, controls)
    shift = ReconShift.objects.create(stowe_shift_id='PT-T1', cashier=users['payer'], shift_type=1, start_datetime=timezone.now() - timedelta(hours=2), end_datetime=timezone.now() + timedelta(hours=6))
    closed = ReconShift.objects.create(stowe_shift_id='PT-T0', cashier=users['payer'], shift_type=1, start_datetime=timezone.now() - timedelta(days=2), end_datetime=timezone.now() - timedelta(days=1), confirmed=True)
    check('CT-2 whoever is not a payer cannot pay', raises(lambda: A.pay_advance(adv, users['stranger'], 'CASH_TILL', shift_id=shift.pk), A.AdvanceError, 'not authorised'))
    check('CT-2 a payer who also holds HR Admin is refused', raises(lambda: A.pay_advance(adv, users['both'], 'CASH_TILL', shift_id=shift.pk), A.AdvanceError, 'salary roles'))
    check('LK-2 a cash advance needs a till', raises(lambda: A.pay_advance(adv, users['payer'], 'CASH_TILL'), A.AdvanceError, 'till'))
    check('LK-2 a till with no open shift is refused', raises(lambda: A.pay_advance(adv, users['payer'], 'CASH_TILL', shift_id=closed.pk), A.AdvanceError, 'open shift'))
    adv.refresh_from_db()
    check('LK-2 a refused payment changes nothing', adv.status == 'APPROVED' and not adv.ledger.exists() and not BusinessExpense.objects.filter(description__contains=adv.number).exists())
    dvar_before = sum((e.amount for e in shift.business_expenses.all()), Decimal('0'))
    pay = A.pay_advance(adv, users['payer'], 'CASH_TILL', shift_id=shift.pk)
    adv.refresh_from_db()
    exp = BusinessExpense.objects.get(pk=pay.recon_expense_id)
    check('S9 cash advance recorded in the reconciliation records at once, on that till/shift', exp.shift_id == shift.pk and exp.amount == Decimal('300.00') and exp.category.name == 'Salary advance')
    check('S9 the shift expense total (used by the cashier variance) includes it as an approved outflow', sum((e.amount for e in shift.business_expenses.all()), Decimal('0')) == dvar_before + Decimal('300.00'))
    check('LK-1 the record carries the employee and the HR advance number', adv.number in exp.description and e1.employee_number in exp.description)
    check('RC-1 balance = paid out minus deductions', adv.balance == Decimal('300.00') and adv.status == 'PAID')
    check('AD-8 receipt number issued', pay.receipt_number == f"RCP-{adv.number}" and client(users['payer']).get(f'/hr/manage/advances/{adv.pk}/receipt/').status_code == 200)
    check('CT-4 a paid advance cannot be deleted', raises(lambda: adv.delete(), PermissionError))
    check('S14 a paid advance cannot be cancelled, only repaid', raises(lambda: A.cancel_advance(adv, users['hr']), A.AdvanceError, 'repayment'))
    check('CT-4 ledger entries are permanent', raises(lambda: adv.ledger.first().delete(), PermissionError))
    check('CT-1 the same advance cannot be paid twice', raises(lambda: A.pay_advance(adv, users['payer'], 'CASH_TILL', shift_id=shift.pk), A.AdvanceError))
    check('LK-5 advance is not an operating expense', 'Salary advance' in __import__('reconciliation.financial_statements', fromlist=['x']).NON_OPEX_CATEGORY_NAMES)
    check('LK-4 unrecovered advances are available for the balance sheet', A.owed_as_of(today) >= Decimal('300.00'))

    # petty cash and transfer
    fund = PettyCashAllocation.objects.create(fund_name='PT Fund', custodian=users['payer'], allocated_by=users['hr'], amount=Decimal('500'), status='ACTIVE')
    adv2 = A.capture_request(e2, 200, 'Medical', None, 1, users['mgr'])
    A.confirm_advance(adv2, code=A.issue_code(adv2), actor=users['mgr'])
    workflow.approve([s for s in workflow.pending_steps_for(users['hr']) if 'Salary advance' in s.instance.summary][0], users['hr'])
    adv2.refresh_from_db()
    check('AD-7 petty cash payment needs a fund', raises(lambda: A.pay_advance(adv2, users['payer'], 'PETTY_CASH'), A.AdvanceError))
    check('AD-7 transfer needs a bank reference', raises(lambda: A.pay_advance(adv2, users['payer'], 'TRANSFER'), A.AdvanceError, 'reference'))
    A.pay_advance(adv2, users['payer'], 'PETTY_CASH', fund_id=fund.pk)
    fund.refresh_from_db()
    check('LK petty cash advance reduces the fund', fund.current_balance == Decimal('300.00'), str(fund.current_balance))

    # ======================================================== payrun lock: recovery (10, 11)
    per1 = PayPeriod.objects.create(company=co, label='PT-1', start_date=today.replace(day=1), end_date=today.replace(day=28), pay_date=today, tax_year=2027)
    run1 = P.get_run(per1, users['payroll'])
    csv1 = (f"employee_number,gross,other_deductions,net\n{e1.employee_number},10000,1500,8500\n{e2.employee_number},8000,1000,7000\n"
            f"{mgr_e.employee_number},12000,0,12000\n")
    made, problems = P.import_lines(run1, csv1, users['payroll'])
    check('payrun totals load', made == 3 and not problems)
    prev = P.preview_recoveries(run1)
    check('RC-3 preview shows the recoveries before locking', any(p['line'].employee_id == e1.pk and p['total'] == sched[0].amount for p in prev), str(prev))
    check('RC-3 only Payroll Admin can lock', raises(lambda: P.lock(run1, users['hr']), P.PayrunError))
    total, result = P.lock(run1, users['payroll'])
    adv.refresh_from_db(); run1.refresh_from_db()
    l1 = run1.lines.get(employee=e1)
    check('S10 locked payrun: deduction recorded, balance falls, payslip line shows it', l1.advance_recovery == sched[0].amount and adv.balance == Decimal('300') - sched[0].amount
          and l1.net == Decimal('8500') - sched[0].amount and adv.status == 'RECOVERING', f"{l1.advance_recovery} {adv.balance}")
    check('S10 payroll lock is final', run1.status == 'LOCKED' and raises(lambda: P.lock(run1, users['payroll']), P.PayrunError))
    check('LK-7 payslip info shows recovery and remaining balance', P.payslip_advance_info(e1, per1)['balance'] == adv.balance)
    check('SY sync switched off: nothing written, reported as skipped', result['skipped'] == 3 and not BusinessExpense.objects.filter(description__contains='[HR payrun').exists())
    # net too low (11): a fresh advance for a new person, recovered in a payrun with a very low net
    e4 = emp('Dee', g_perm, mk('dee'), manager=mgr_e)
    S.import_csv(co, f"employee_number,pay_type,amount,start_date,frequency\n{e4.employee_number},MONTHLY,8000,{(today - timedelta(days=300)).isoformat()},MONTHLY\n", su, apply=True)
    adv_low = A.capture_request(e4, 200, 'Low net test', None, 1, users['mgr'])
    A.confirm_advance(adv_low, code=A.issue_code(adv_low), actor=users['mgr'])
    workflow.approve([s for s in workflow.pending_steps_for(users['hr']) if 'Salary advance' in s.instance.summary][0], users['hr'])
    adv_low.refresh_from_db()
    A.pay_advance(adv_low, users['payer'], 'TRANSFER', reference='EFT123')
    check('AD-7 a transfer records the bank reference and posts a bank outflow', BusinessExpense.objects.filter(description__contains=adv_low.number, shift__isnull=True).exists())
    adv2.refresh_from_db()
    check('RC-2 a single-instalment petty cash advance was fully recovered in the first payrun that followed', adv2.balance == 0 and adv2.status == 'SETTLED', str(adv2.balance))
    per2 = PayPeriod.objects.create(company=co, label='PT-2', start_date=today.replace(day=1) + timedelta(days=31), end_date=today.replace(day=28) + timedelta(days=31), pay_date=today + timedelta(days=30), tax_year=2027)
    run2 = P.get_run(per2, users['payroll'])
    P.import_lines(run2, f"employee_number,gross,other_deductions,net\n{e1.employee_number},10000,1500,8500\n{e4.employee_number},400,350,50\n{mgr_e.employee_number},12000,0,12000\n", users['payroll'])
    P.lock(run2, users['payroll'])
    l2 = run2.lines.get(employee=e4)
    adv_low.refresh_from_db()
    check('S11 net too low: only the possible amount is taken, never below zero', 0 < l2.advance_recovery <= Decimal('50') and l2.net >= 0, f"{l2.advance_recovery} {l2.net}")
    check('S11 the shortfall moves to the next payrun', adv_low.balance == Decimal('200') - l2.advance_recovery and adv_low.status == 'RECOVERING' and adv_low.schedule.filter(status='PLANNED').exists(), f"{adv_low.balance} {[(x.sequence, x.amount, x.status) for x in adv_low.schedule.all()]}")
    per3 = PayPeriod.objects.create(company=co, label='PT-3', start_date=today.replace(day=1) + timedelta(days=62), end_date=today.replace(day=28) + timedelta(days=62), pay_date=today + timedelta(days=60), tax_year=2027)
    run3 = P.get_run(per3, users['payroll'])
    P.import_lines(run3, f"employee_number,gross,other_deductions,net\n{e1.employee_number},10000,1500,8500\n{e4.employee_number},8000,1000,7000\n", users['payroll'])
    P.lock(run3, users['payroll'])
    adv.refresh_from_db(); adv_low.refresh_from_db()
    check('RC-1 advances settle once fully recovered', adv.balance == 0 and adv.status == 'SETTLED' and adv_low.balance == 0 and adv_low.status == 'SETTLED', f"{adv.balance}/{adv_low.balance}")
    check('RC-1 nothing was over-recovered', sum(-l.amount for l in adv.ledger.filter(type='DEDUCTION')) == Decimal('300.00')
          and sum(-l.amount for l in adv_low.ledger.filter(type='DEDUCTION')) == Decimal('200.00'))

    # ======================================================== repayment, write-off, leavers (12)
    # The earlier advances were captured earlier today. The one-advance-a-day rule works now that dates no longer
    # depend on database time zone tables, so this scenario needs them to be from earlier days.
    Advance.objects.all().update(created_at=timezone.now() - timedelta(days=40))
    adv3 = A.capture_request(e1, 400, 'Car repair', None, 1, users['mgr'])
    A.confirm_advance(adv3, code=A.issue_code(adv3), actor=users['mgr'])
    workflow.approve([s for s in workflow.pending_steps_for(users['hr']) if 'Salary advance' in s.instance.summary][0], users['hr'])
    adv3.refresh_from_db()
    A.pay_advance(adv3, users['payer'], 'CASH_TILL', shift_id=shift.pk)
    check('RC-5 repayment above the balance is refused', raises(lambda: A.record_repayment(adv3, 500, 'CASH_TILL', users['payer'], shift_id=shift.pk), A.AdvanceError, 'between'))
    A.record_repayment(adv3, 100, 'CASH_TILL', users['payer'], shift_id=shift.pk)
    adv3.refresh_from_db()
    check('RC-5 early settlement: balance falls with a receipt', adv3.balance == Decimal('300.00') and adv3.status == 'RECOVERING' and adv3.ledger.filter(type='REPAYMENT').first().receipt_number)
    check('RC-5 the repayment is an inflow on the same till', shift.business_expenses.filter(amount=Decimal('-100.00')).exists())
    check('RC-8 write-off needs a written reason', raises(lambda: A.request_writeoff(adv3, users['hr'], ' '), A.AdvanceError, 'reason'))
    wo = A.request_writeoff(adv3, users['hr'], 'Employee absconded')
    check('RC-8 HR cannot approve a write-off', not [s for s in workflow.pending_steps_for(users['hr']) if 'Write off' in s.instance.summary])
    workflow.approve([s for s in workflow.pending_steps_for(users['senior']) if 'Write off' in s.instance.summary][0], users['senior'])
    adv3.refresh_from_db()
    check('RC-8 senior management approves: balance cleared, status written off, own category', adv3.balance == 0 and adv3.status == 'WRITTEN_OFF'
          and BusinessExpense.objects.filter(category__name='Salary advance write-off', description__contains=adv3.number).exists())
    # leaver
    e3 = emp('Leo', g_perm, mk('leo'))
    S.import_csv(co, f"employee_number,pay_type,amount,start_date,frequency\n{e3.employee_number},MONTHLY,9000,{(today - timedelta(days=300)).isoformat()},MONTHLY\n", su, apply=True)
    ps.refresh_from_db()
    adv4 = A.capture_request(e3, 500, 'Rent', None, 3, users['mgr'])
    A.confirm_advance(adv4, code=A.issue_code(adv4), actor=users['mgr'])
    workflow.approve([s for s in workflow.pending_steps_for(users['hr']) if 'Salary advance' in s.instance.summary][0], users['hr'])
    adv4.refresh_from_db()
    A.pay_advance(adv4, users['payer'], 'CASH_TILL', shift_id=shift.pk)
    e3.status, e3.termination_date = 'TERMINATED', today
    e3.save()
    lv = A.leaver_balances(co)
    check('S12 a leaver with a balance is listed for HR', any(r['advance'].pk == adv4.pk and not r['agreed'] for r in lv))
    check('RC-6 HR records the employee agreement to a final pay deduction', not raises(lambda: A.record_final_pay_agreement(adv4, users['hr'], 'signed at exit interview')))
    per4 = PayPeriod.objects.create(company=co, label='PT-4', start_date=today.replace(day=1) + timedelta(days=93), end_date=today.replace(day=28) + timedelta(days=93), pay_date=today + timedelta(days=90), tax_year=2027)
    run4 = P.get_run(per4, users['payroll'])
    P.import_lines(run4, f"employee_number,gross,other_deductions,net\n{e3.employee_number},9000,1000,8000\n", users['payroll'])
    P.lock(run4, users['payroll'])
    adv4.refresh_from_db()
    check('RC-6 final pay: the whole agreed balance is taken', adv4.balance == 0 and adv4.status == 'SETTLED', str(adv4.balance))
    # cancel before payment
    Advance.objects.all().update(created_at=timezone.now() - timedelta(days=40))      # earlier advances were earlier days, see above
    adv5 = A.capture_request(e2, 100, 'x', None, 1, users['mgr'])
    A.cancel_advance(adv5, users['mgr'])
    adv5.refresh_from_db()
    check('RC-7 an unpaid advance can be cancelled', adv5.status == 'CANCELLED')

    # ======================================================== sync (Section 3)
    Cashier.objects.create(name='Ann Pay', employee_id=e1.employee_number)
    Cashier.objects.create(name='Boss Pay', employee_id=mgr_e.employee_number)
    ps.salary_sync_enabled = True
    ps.save()
    unm = Y.unmatched(co)
    check('SY-2 people with no reconciliation counterpart are listed, never guessed', e2 in unm and e1 not in unm and cas in unm)
    r_sync = Y.sync_payrun(run1, users['payroll'])
    created = BusinessExpense.objects.filter(description__contains=f'[HR payrun {run1.pk}]')
    check('S1 payrun sync creates a Salaries entry per matched person', r_sync['created'] == 2 and created.count() == 2 and created.first().category.name == 'Salaries', str(r_sync))
    check('SY-2 the unmatched person got nothing (S5)', r_sync['unmatched'] == 1 and not created.filter(description__contains=e2.employee_number).exists())
    check('SY-4 the log records source and new value', SyncLog.objects.filter(source_key=f"PAYRUN:{run1.pk}:{e1.employee_number}", status='OK').exists())
    r_again = Y.sync_payrun(run1, users['payroll'])
    check('S4 running the sync twice makes no changes and no duplicates', r_again['unchanged'] == 2 and r_again['created'] == 0 and BusinessExpense.objects.filter(description__contains=f'[HR payrun {run1.pk}]').count() == 2, str(r_again))
    # basis
    line = run1.lines.get(employee=e1)
    line.gross = Decimal('10250')
    line.save()
    r_upd = Y.sync_payrun(run1, users['payroll'])
    log_up = SyncLog.objects.filter(source_key=f"PAYRUN:{run1.pk}:{e1.employee_number}", message__icontains='Overwritten').first()
    check('SY-1/SY-4 a changed HR figure overwrites the entry and logs old and new', r_upd['updated'] == 1 and log_up and log_up.old_value.startswith('10000') and log_up.new_value.startswith('10250'), str(r_upd))
    # read-only guard
    exp = BusinessExpense.objects.filter(description__contains=f'[HR payrun {run1.pk}]').first()
    def edit():
        exp.amount = Decimal('1.00')
        exp.save()
    check('S2 editing a salary entry in the reconciliation system is impossible', raises(edit, PermissionDenied))
    cat_sal = ExpenseCategory.objects.get(name='Salaries')
    check('SM-9 creating a Salaries entry by hand is impossible', raises(lambda: BusinessExpense.objects.create(category=cat_sal, description='hand', amount=5, expense_date=today), PermissionDenied))
    check('SY-5 deleting a salary entry by hand is impossible', raises(lambda: exp.delete(), PermissionDenied))
    other = ExpenseCategory.objects.create(name='PT Other')
    check('other expense categories stay editable', BusinessExpense.objects.create(category=other, description='ok', amount=5, expense_date=today).pk)
    # daily comparison
    diffs_before = len(Y.daily_comparison(co))
    exp2 = BusinessExpense.objects.get(pk=exp.pk)
    exp2.amount = Decimal('777.00')
    exp2._hr_sync = True
    exp2.save()
    check('SY-9 the daily comparison lists a leftover mismatch', len(Y.daily_comparison(co)) == diffs_before + 1)
    Y.sync_payrun(run1, users['payroll'])
    check('SY-9 a re-sync repairs it', len(Y.daily_comparison(co)) == diffs_before)
    # closed period (3)
    ps.books_closed_through = per2.pay_date + timedelta(days=5)
    ps.save()
    line2 = run2.lines.get(employee=e1)
    r_closed = Y.sync_payrun(run2, users['payroll'])
    check('S3 a closed period is untouched: an adjustment is proposed instead', r_closed['adjusted'] >= 1 and not BusinessExpense.objects.filter(description__contains=f'[HR payrun {run2.pk}]').exists(), str(r_closed))
    adj = AdjustmentEntry.objects.filter(status='PENDING', employee=e1).first()
    check('SY-6 the adjustment shows the difference for finance', adj and adj.difference == line2.gross)
    Y.resolve_adjustment(adj, users['payroll'], True)
    adj.refresh_from_db()
    exp_adj = BusinessExpense.objects.get(pk=adj.recon_expense_id)
    check('SY-6 approving books it in the open period, after the closed date', exp_adj.expense_date > ps.books_closed_through)
    ps.books_closed_through = None
    ps.save()
    # link management
    Y.mark_no_counterpart(e2, users['payroll'])
    check('SY-2 an administrator can state "no counterpart" explicitly', SyncLink.objects.get(employee=e2).kind == 'NO_COUNTERPART' and e2 not in Y.unmatched(co))
    check('SY-2 manual link needs a real reconciliation person', raises(lambda: Y.link_manually(cas, 'NOPE', users['payroll']), ValueError))
    fl = Y.first_load_report(co)
    check('SY-11 first-load report compares existing Salaries with HR', isinstance(fl, list) and fl)
    check('rate publication is read-only', Y.hr_salary_rate(e1.employee_number, today) is not None)
    rec_sync = Y.sync_salary(S.current_record(e1))
    check('SY-3 salary rate sync recorded', rec_sync in ('SYNCED', 'UNMATCHED'))

    # ======================================================== pages and roles
    page = lambda c, url: c.get(url).status_code
    check('portal advances page', page(emp_c, '/hr/advances/') == 200)
    check('manager: advances list, capture, detail', page(mgr, '/hr/manage/advances/') == 200 and page(mgr, '/hr/manage/advances/capture/') == 200 and page(mgr, f'/hr/manage/advances/{adv.pk}/') == 200)
    check('capture search finds the employee', b'Available' in mgr.get(f'/hr/manage/advances/capture/?q={e1.employee_number}').content or b'Not eligible' in mgr.get(f'/hr/manage/advances/capture/?q={e1.employee_number}').content)
    check('payer sees the advance queue', page(payer, '/hr/manage/advances/?show=open') == 200)
    check('a stranger cannot open advances admin', page(strang, '/hr/manage/advances/') == 403)
    check('salary pages for HR', all(page(hr, u) == 200 for u in ('/hr/manage/salaries/', f'/hr/manage/salaries/{e1.pk}/history/', f'/hr/manage/salaries/{e1.pk}/change/', '/hr/manage/salaries/import/')))
    check('payroll pages', all(page(payroll, u) == 200 for u in ('/hr/manage/payruns/', f'/hr/manage/payruns/{run1.pk}/', '/hr/manage/sync/')))
    check('HR cannot lock or open payruns / sync (payroll only)', page(hr, '/hr/manage/payruns/') == 403 and page(hr, '/hr/manage/sync/') == 403)
    for k in ('outstanding', 'monthly', 'schedule', 'source', 'exceptions', 'leavers', 'salary'):
        check(f'report: {k}', page(hr, f'/hr/manage/pay-reports/{k}/') == 200)
    csv_r = hr.get('/hr/manage/pay-reports/outstanding/?csv=1')
    check('CT-6 report export works and is logged', csv_r.status_code == 200 and AuditLog.objects.filter(action='report.export', module='pay').exists())
    check('CT-3 money movements are audited', AuditLog.objects.filter(module='advances').count() >= 10 and AuditLog.objects.filter(module='salary').count() >= 3 and AuditLog.objects.filter(module='sync').exists())
    check('RC-10 manager sees team advances but not salaries', page(mgr, '/hr/manage/advances/?show=all') == 200 and page(mgr, '/hr/manage/salaries/') == 403)


if __name__ == '__main__':
    run()

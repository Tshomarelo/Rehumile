from decimal import Decimal
from types import SimpleNamespace

from ims import payroll


def emp(**kw):
    base = dict(employment_type='full_time', gross_monthly_salary=Decimal('0'), hourly_rate=Decimal('0'),
                scheduled_hours_per_week=Decimal('40'), monthly_allowance=Decimal('0'),
                monthly_other_deduction=Decimal('0'), id_number='')
    base.update(kw)
    return SimpleNamespace(**base)


def test_uif_is_capped_at_ceiling():
    # UIF applies only to the first R17,712 a month -> max R177.12 (old code capped at R1,476)
    assert payroll.uif_employee_monthly(Decimal('30000')) == Decimal('177.12')
    assert payroll.uif_employee_monthly(Decimal('5000')) == Decimal('50.00')


def test_paye_below_threshold_is_zero():
    assert payroll.paye_monthly(Decimal('7000')) == Decimal('0.00')   # R84k a year < R95,750


def test_paye_known_value():
    # R30,000/m = R360,000/yr: 42,678 + 26% of (360,000 - 237,100) = 74,632; less 17,235 rebate; /12
    assert payroll.paye_monthly(Decimal('30000')) == Decimal('4783.08')


def test_age_rebate_reduces_tax():
    assert payroll.paye_monthly(Decimal('30000'), age=66) < payroll.paye_monthly(Decimal('30000'), age=40)


def test_age_from_sa_id():
    assert payroll.age_from_id_number('8001015009087', on=__import__('datetime').date(2026, 9, 30)) == 46


def test_salaried_with_overtime_allowance_and_deduction():
    e = emp(gross_monthly_salary=Decimal('20000'), monthly_allowance=Decimal('500'), monthly_other_deduction=Decimal('300'))
    c = payroll.calculate(e, overtime_hours=10)
    hourly = Decimal('20000') / (Decimal('40') * Decimal('52') / Decimal('12'))
    assert c['overtime'] == (Decimal('10') * Decimal('1.5') * hourly).quantize(Decimal('0.01'))
    assert c['gross'] == c['basic'] + c['overtime'] + Decimal('500')
    assert c['net'] == c['gross'] - c['paye'] - c['uif_employee'] - Decimal('300')
    assert c['employer_cost'] == c['gross'] + c['uif_employer']


def test_hourly_employee_paid_for_hours_worked():
    e = emp(employment_type='hourly', hourly_rate=Decimal('50'))
    c = payroll.calculate(e, hours_worked=100)
    assert c['basic'] == Decimal('5000.00')


def test_sdl_only_when_enabled():
    e = emp(gross_monthly_salary=Decimal('10000'))
    assert payroll.calculate(e)['sdl'] == Decimal('0.00')
    assert payroll.calculate(e, sdl_enabled=True)['sdl'] == Decimal('100.00')


def test_negative_net_is_flagged():
    e = emp(gross_monthly_salary=Decimal('1000'), monthly_other_deduction=Decimal('5000'))
    assert payroll.calculate(e)['warnings']

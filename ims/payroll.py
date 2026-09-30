"""
South African payroll calculation — pure functions, no database access, so the
rules are easy to read and test.

All rates live in this one table. When SARS publishes a new tax year, update
TAX_YEAR / BRACKETS / REBATES / UIF_* here and nowhere else.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

TAX_YEAR = '2025/26'

# (upper bound of band, lower bound, tax on everything below the band, marginal rate)
BRACKETS = [
    (Decimal('237100'), Decimal('0'), Decimal('0'), Decimal('0.18')),
    (Decimal('370500'), Decimal('237100'), Decimal('42678'), Decimal('0.26')),
    (Decimal('512800'), Decimal('370500'), Decimal('77362'), Decimal('0.31')),
    (Decimal('673000'), Decimal('512800'), Decimal('121475'), Decimal('0.36')),
    (Decimal('857900'), Decimal('673000'), Decimal('179147'), Decimal('0.39')),
    (Decimal('1817000'), Decimal('857900'), Decimal('251258'), Decimal('0.41')),
    (None, Decimal('1817000'), Decimal('644489'), Decimal('0.45')),
]
REBATE_PRIMARY = Decimal('17235')      # everyone
REBATE_SECONDARY = Decimal('9444')     # additional, age 65+
REBATE_TERTIARY = Decimal('3145')      # additional, age 75+

UIF_RATE = Decimal('0.01')             # employee 1% + employer 1%
UIF_MONTHLY_EARNINGS_CEILING = Decimal('17712')   # UIF only applies to the first R17,712 of pay a month
SDL_RATE = Decimal('0.01')             # employer only, when payroll is above R500k a year
OVERTIME_MULTIPLIER = Decimal('1.5')   # BCEA minimum for ordinary overtime
WEEKS_PER_MONTH = Decimal('52') / Decimal('12')

CENT = Decimal('0.01')


def money(value):
    return Decimal(value or 0).quantize(CENT, ROUND_HALF_UP)


def age_from_id_number(id_number, on=None):
    """SA ID numbers start YYMMDD. Returns None if it can't be read."""
    on = on or date.today()
    digits = ''.join(c for c in (id_number or '') if c.isdigit())
    if len(digits) < 6:
        return None
    try:
        yy, mm, dd = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
        year = 2000 + yy if yy <= on.year % 100 else 1900 + yy
        born = date(year, mm, dd)
    except ValueError:
        return None
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def annual_tax(annual_income, age=None):
    """Annual income tax after rebates (never below zero)."""
    annual_income = Decimal(annual_income)
    tax = Decimal('0')
    for upper, lower, base, rate in BRACKETS:
        if upper is None or annual_income <= upper:
            tax = base + (annual_income - lower) * rate
            break
    rebate = REBATE_PRIMARY
    if age is not None and age >= 65:
        rebate += REBATE_SECONDARY
    if age is not None and age >= 75:
        rebate += REBATE_TERTIARY
    return max(tax - rebate, Decimal('0'))


def paye_monthly(gross_monthly, age=None):
    return money(annual_tax(Decimal(gross_monthly) * 12, age) / 12)


def uif_employee_monthly(gross_monthly):
    return money(min(Decimal(gross_monthly), UIF_MONTHLY_EARNINGS_CEILING) * UIF_RATE)


def sdl_monthly(gross_monthly):
    return money(Decimal(gross_monthly) * SDL_RATE)


def monthly_hours(employee):
    return Decimal(employee.scheduled_hours_per_week or 0) * WEEKS_PER_MONTH


def hourly_equivalent(employee):
    """Hourly rate used for overtime: the stated rate, or salary spread over contracted hours."""
    if employee.employment_type == 'hourly' or (Decimal(employee.hourly_rate or 0) > 0 and Decimal(employee.gross_monthly_salary or 0) == 0):
        return Decimal(employee.hourly_rate or 0)
    hours = monthly_hours(employee)
    return Decimal(employee.gross_monthly_salary or 0) / hours if hours else Decimal('0')


def calculate(employee, *, overtime_hours=0, hours_worked=None, extra_allowance=0,
              extra_deduction=0, sdl_enabled=False, on=None):
    """
    Work out one month's payslip for `employee`. Returns a dict of Decimals:

      basic          salary, or hourly_rate x hours for hourly/casual staff
      overtime       overtime_hours x 1.5 x hourly rate
      allowances     the employee's fixed monthly allowance + any extra this month
      gross          basic + overtime + allowances   (PAYE and UIF are worked out on this)
      paye, uif_employee, uif_employer, sdl
      other_deductions  fixed monthly deduction + any extra this month (after tax)
      net            gross - paye - uif_employee - other_deductions
      employer_cost  gross + uif_employer + sdl
      warnings       list of human-readable problems (e.g. net pay below zero)
    """
    overtime_hours = Decimal(str(overtime_hours or 0))
    warnings = []

    if employee.employment_type == 'hourly':
        hours = Decimal(str(hours_worked)) if hours_worked not in (None, '') else monthly_hours(employee)
        basic = money(Decimal(employee.hourly_rate or 0) * hours)
        if not Decimal(employee.hourly_rate or 0):
            warnings.append('Hourly employee has no hourly rate set.')
    else:
        basic = money(employee.gross_monthly_salary)
        if not basic:
            warnings.append('Employee has no monthly salary set.')

    overtime = money(overtime_hours * OVERTIME_MULTIPLIER * hourly_equivalent(employee))
    allowances = money(Decimal(employee.monthly_allowance or 0) + Decimal(str(extra_allowance or 0)))
    gross = basic + overtime + allowances

    age = age_from_id_number(employee.id_number, on)
    paye = paye_monthly(gross, age)
    uif_e = uif_employee_monthly(gross)
    uif_er = uif_e
    sdl = sdl_monthly(gross) if sdl_enabled else Decimal('0.00')
    other = money(Decimal(employee.monthly_other_deduction or 0) + Decimal(str(extra_deduction or 0)))
    net = gross - paye - uif_e - other
    if net < 0:
        warnings.append('Deductions exceed pay — net pay is negative. Check the employee\'s monthly deduction.')

    return {
        'basic': basic, 'overtime_hours': overtime_hours, 'overtime': overtime, 'allowances': allowances,
        'gross': gross, 'paye': paye, 'uif_employee': uif_e, 'uif_employer': uif_er, 'sdl': sdl,
        'other_deductions': other, 'net': net, 'employer_cost': gross + uif_er + sdl,
        'age': age, 'warnings': warnings,
    }

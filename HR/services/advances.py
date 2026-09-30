"""Salary advances (Sections 4 to 6): policy and limits, request and confirmation, approval tiers, payment,
recovery schedule, repayment, write-off and the reports."""
import hashlib
import secrets
from ..timeutils import on_day, local_date
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from django.conf import settings as dj_settings
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from ..models import (
    ADVANCE_PAYER, HR_ADMIN, LINE_MANAGER, PAYROLL_ADMIN, SUPER_ADMIN, Advance, AdvanceConfirmation, AdvanceLedger,
    AdvancePayment, AdvancePolicy, AdvanceWriteOff, Employee, RecoverySchedule, Shift, WorkflowInstance,
)
from ..models.roster import RosterProfile
from . import audit, recon_bridge, salary, workflow
from .access import has_role, roles_for
from .notify import notify

CENT = Decimal('0.01')
OPEN_STATUSES = ('REQUESTED', 'AWAITING_APPROVAL', 'APPROVED', 'PAID', 'RECOVERING')


class AdvanceError(Exception):
    pass


def q(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def policy_for(employee):
    prof = RosterProfile.objects.filter(employee=employee).select_related('staff_group').first()
    if prof is None or prof.staff_group is None:
        return None, None
    return AdvancePolicy.objects.filter(staff_group=prof.staff_group).first(), prof.staff_group


# ------------------------------------------------------------------ limits and eligibility (AD-1, AD-2)
def earned_to_date(employee, on=None):
    """Pay earned so far this month, from the salary record, or from shifts actually worked for casuals and
    hourly / per-shift workers (AD-2). Returns (amount, note)."""
    on = on or timezone.localdate()
    first = on.replace(day=1)
    pol, grp = policy_for(employee)
    rec = salary.current_record(employee, on)
    prof = RosterProfile.objects.filter(employee=employee).first()
    casual = bool(grp and grp.is_casual)
    rate_type, rate = None, None
    if rec is not None and rec.pay_type in ('HOURLY', 'SHIFT'):
        rate_type, rate = rec.pay_type, rec.amount
    elif casual and prof and prof.casual_rate:
        rate_type, rate = ('HOURLY' if prof.casual_pay_basis == 'HOUR' else 'SHIFT'), prof.casual_rate
    if rate_type:
        now = datetime.now()
        worked = [s for s in Shift.objects.filter(employee=employee, date__range=(first, on), status='PUBLISHED') if s.end_at <= now]
        if rate_type == 'HOURLY':
            return q(sum((Decimal(s.paid_hours) for s in worked), Decimal('0')) * rate), f"{len(worked)} shift(s) worked this month"
        return q(Decimal(len(worked)) * rate), f"{len(worked)} shift(s) worked this month"
    if rec is None:
        return Decimal('0'), "no approved salary record"
    if casual and pol and pol.casual_only_against_shifts_worked:
        return Decimal('0'), "casual workers can only draw against shifts already worked"
    dim = (first.replace(month=first.month % 12 + 1, year=first.year + (first.month == 12)) - first).days
    if rec.pay_type == 'MONTHLY':
        return q(rec.amount * Decimal(on.day) / Decimal(dim)), "monthly salary accrued to date"
    return q(rec.amount * Decimal(on.day) / Decimal(7)), "weekly wage accrued to date"


def outstanding_balance(employee):
    total = AdvanceLedger.objects.filter(advance__employee=employee).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    return q(total)


def eligibility(employee, on=None):
    """Whether they may ask, the most they can ask for, and plain reasons if not (AD-1)."""
    on = on or timezone.localdate()
    pol, grp = policy_for(employee)
    out = {'eligible': False, 'reasons': [], 'max': Decimal('0'), 'earned': Decimal('0'), 'outstanding': Decimal('0'), 'policy': pol,
           'fee_percent': pol.fee_percent if pol else Decimal('0'), 'recovery_max': pol.recovery_max_payruns if pol else 1, 'note': ''}
    if pol is None:
        out['reasons'].append("You are not in a staff group with an advance policy. Ask HR.")
        return out
    if not pol.allowed:
        out['reasons'].append("Advances are not available for your staff group.")
        return out
    if pol.min_months_service and employee.start_date:
        months = (on - employee.start_date).days / 30.44
        if months < pol.min_months_service:
            out['reasons'].append(f"You need {pol.min_months_service} months of service (you have {int(months)}).")
    open_n = Advance.objects.filter(employee=employee, status__in=OPEN_STATUSES).count()
    if open_n >= pol.open_advances:
        out['reasons'].append(f"You already have {open_n} open advance(s); the limit is {pol.open_advances}.")
    last = Advance.objects.filter(employee=employee).exclude(status__in=('CANCELLED', 'DECLINED')).order_by('-created_at').first()
    if last and pol.min_days_between and (on - local_date(last.created_at)).days < pol.min_days_between:
        out['reasons'].append(f"At least {pol.min_days_between} days must pass between advances.")
    if Advance.objects.filter(employee=employee, **on_day('created_at', on)).exclude(status__in=('CANCELLED', 'DECLINED')).exists():
        out['reasons'].append("An advance was already captured for you today. Only one can be made per day.")
    bal = outstanding_balance(employee)
    out['outstanding'] = bal
    if bal > pol.max_unpaid_balance:
        out['reasons'].append(f"You still owe R{bal}, which is above the allowed unpaid balance of R{pol.max_unpaid_balance}.")
    if pol.block_on_final_warning:
        from ..models import Warning
        if any(w.is_live for w in Warning.objects.filter(employee=employee, level='FINAL', withdrawn=False)):
            out['reasons'].append("You have a live final written warning.")
    earned, note = earned_to_date(employee, on)
    out['earned'], out['note'] = earned, note
    cap = earned * pol.max_percent_of_earned / Decimal(100)
    if pol.max_amount is not None:
        cap = min(cap, pol.max_amount)
    avail = q(cap - bal) if cap > bal else Decimal('0')
    out['max'] = max(avail, Decimal('0'))
    if out['max'] <= 0 and not out['reasons']:
        out['reasons'].append(f"Nothing is available: pay earned so far is R{earned} ({note}).")
    out['eligible'] = not out['reasons']
    return out


# ------------------------------------------------------------------ request, confirmation, approval
def _can_capture_for_others(user):
    return has_role(user, LINE_MANAGER, HR_ADMIN, SUPER_ADMIN, ADVANCE_PAYER)


def _digest(advance, code):
    return hashlib.sha256(f"{dj_settings.SECRET_KEY}:{advance.pk}:{code}".encode()).hexdigest()


def issue_code(advance):
    """AD-5: a one-time code goes to the employee's own phone/email. The person capturing never sees it."""
    ps = salary.get_pay_settings(advance.employee.company)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    AdvanceConfirmation.objects.create(advance=advance, method='CODE', code_hash=_digest(advance, code),
                                       code_expires=timezone.now() + timedelta(minutes=ps.code_valid_minutes))
    emp = advance.employee
    if emp.user:
        notify([emp.user], 'advance', "Your advance confirmation code",
               f"Code {code} confirms advance {advance.number} of R{advance.amount}. It is valid for {ps.code_valid_minutes} minutes. "
               "Only give it to the person capturing your request if you asked for the advance.", reverse('hr:advances'))
    return code


@transaction.atomic
def capture_request(employee, amount, reason, needed_by, recovery_payruns, by_user, emergency=False, emergency_reason=''):
    """AD-3/AD-4: the employee asks in the portal, or a manager, HR or supervisor captures it at the counter."""
    try:
        amount = q(Decimal(str(amount)))
    except Exception:
        raise AdvanceError("Enter the amount as a number.")
    if amount <= 0:
        raise AdvanceError("The amount must be more than zero.")
    if not reason.strip():
        raise AdvanceError("Give a reason.")
    own = employee.user_id == by_user.pk
    if not own and not _can_capture_for_others(by_user):
        raise AdvanceError("Only a manager, HR or an authorised supervisor can capture an advance for someone else.")
    st = eligibility(employee)
    pol = st['policy']
    if emergency:
        if own or not has_role(by_user, LINE_MANAGER, HR_ADMIN, SUPER_ADMIN):
            raise AdvanceError("Only a manager can raise an emergency advance for someone.")
        if not emergency_reason.strip():
            raise AdvanceError("An emergency advance needs a written reason.")
        if pol is None or not pol.allowed:
            raise AdvanceError("This staff group cannot take advances, even in an emergency.")
    else:
        if not st['eligible']:
            raise AdvanceError(" ".join(st['reasons']))
        if amount > st['max']:
            raise AdvanceError(f"The most available is R{st['max']}.")
        if recovery_payruns > pol.recovery_max_payruns:
            raise AdvanceError(f"Recovery can take at most {pol.recovery_max_payruns} payrun(s).")
    if Advance.objects.filter(employee=employee, **on_day('created_at', timezone.localdate())).exclude(status__in=('CANCELLED', 'DECLINED')).exists() and not emergency:
        raise AdvanceError("An advance was already captured for this person today, possibly at another place.")
    fee = q(amount * pol.fee_percent / Decimal(100)) if pol else Decimal('0')
    adv = Advance.objects.create(employee=employee, amount=amount, fee=fee, reason=reason[:250], needed_by=needed_by,
                                 recovery_payruns=max(1, int(recovery_payruns or 1)), captured_by=None if own else by_user,
                                 emergency=emergency, emergency_reason=emergency_reason[:300])
    issue_code(adv)
    audit.log('advance.request', 'advances', user=by_user, obj=adv, employee=employee, sensitive=True,
              new={'amount': str(amount), 'captured_by': None if own else by_user.get_username(), 'emergency': emergency})
    return adv


@transaction.atomic
def confirm_advance(advance, code=None, signed_name=None, actor=None, ip=None, device=''):
    """AD-5: the employee confirms it themselves; that confirmation is stored as their written agreement."""
    if advance.status != 'REQUESTED':
        raise AdvanceError("This advance is not waiting for confirmation.")
    ps = salary.get_pay_settings(advance.employee.company)
    emp = advance.employee
    if code:
        conf = advance.confirmations.filter(method='CODE', confirmed_at__isnull=True, code_expires__gte=timezone.now()).order_by('-created_at').first()
        if conf is None:
            raise AdvanceError("The code has expired. Ask for a new one.")
        if not secrets.compare_digest(conf.code_hash, _digest(advance, code.strip())):
            audit.log('advance.confirm_failed', 'advances', user=actor, obj=advance, employee=emp)
            raise AdvanceError("That code is not right.")
    elif signed_name:
        if actor is None or emp.user_id != actor.pk:
            raise AdvanceError("Only the employee can sign for their own advance.")
        if signed_name.strip().lower() not in (emp.full_name.lower(), emp.display_name.lower()):
            raise AdvanceError("Type your full name exactly to sign.")
        conf = AdvanceConfirmation.objects.create(advance=advance, method='SIGNATURE', signed_name=signed_name.strip())
    else:
        raise AdvanceError("Enter the code or sign with your name.")
    conf.confirmed_at = timezone.now()
    conf.ip, conf.device = ip, device[:250]
    conf.agreement_copy = (f"{ps.agreement_text}\n\nAdvance {advance.number}: R{advance.amount}"
                           + (f" plus fee R{advance.fee}" if advance.fee else '')
                           + f", recovered over {advance.recovery_payruns} payrun(s). Employee: {emp.full_name} ({emp.employee_number}).")
    conf.save()
    advance.confirmed_at, advance.status = timezone.now(), 'AWAITING_APPROVAL'
    advance.save(update_fields=['confirmed_at', 'status'])
    pol, _ = policy_for(emp)
    if advance.emergency:
        key = 'advance_emergency'
    elif pol and pol.tier1_limit is not None and advance.amount > pol.tier1_limit:
        key = 'advance_large'
    else:
        key = 'advance_small'
    submitter = advance.captured_by or emp.user or actor
    workflow.start(advance, key, submitter, emp, f"Salary advance {advance.number} for {emp.display_name}: R{advance.amount}"
                   + (" (EMERGENCY: " + advance.emergency_reason + ")" if advance.emergency else ''))
    audit.log('advance.confirmed', 'advances', user=actor, obj=advance, employee=emp, sensitive=True, new={'method': conf.method})
    return advance


def _split(total, n):
    total, n = q(total), max(1, n)
    base = (total / n).quantize(CENT, rounding=ROUND_HALF_UP)
    parts = [base] * (n - 1)
    parts.append(q(total - sum(parts, Decimal('0'))))
    return parts


@transaction.atomic
def finalise_approved(advance, instance):
    """AD-6/RC-2: approved, with a recovery schedule the employee can see."""
    last = instance.steps.filter(status='APPROVED').order_by('-acted_at').first()
    advance.status = 'APPROVED'
    advance.approved_by = last.acted_by if last else None
    advance.save(update_fields=['status', 'approved_by'])
    pol, _ = policy_for(advance.employee)
    total = advance.amount + advance.fee
    n = advance.recovery_payruns
    rec = salary.current_record(advance.employee)
    if pol and rec and rec.pay_type == 'MONTHLY' and not advance.emergency:
        cap = rec.amount * pol.max_recovery_percent_of_pay / Decimal(100)
        if cap > 0 and total / n > cap:
            n = int((total / cap).to_integral_value(rounding=ROUND_CEILING))       # never more than the allowed share of pay
    for i, part in enumerate(_split(total, n), start=1):
        RecoverySchedule.objects.create(advance=advance, sequence=i, amount=part)
    audit.log('advance.approved', 'advances', obj=advance, employee=advance.employee, sensitive=True, new={'instalments': n})
    if advance.employee.user:
        notify([advance.employee.user], 'advance', "Advance approved", f"{advance.number} is approved and will be paid out.", reverse('hr:advances'))
    from .workflow import _role_holders
    notify(list(_role_holders(ADVANCE_PAYER)), 'advance', "Advance ready to pay",
           f"{advance.number} for {advance.employee.display_name}: R{advance.amount}", reverse('hr:manage_advances'))


# ------------------------------------------------------------------ payment (AD-7, AD-8, LK-1, LK-2, CT-1, CT-2)
def _holds(user, *roles):
    return has_role(user, *roles)


def _check_separation(advance, payer, ps):
    """CT-1/CT-2: capture, approval and payment are three different people, and payers hold no salary roles."""
    notes = []
    if _holds(payer, HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN):
        if not ps.allow_role_overlap:
            raise AdvanceError("Whoever pays advances cannot also hold salary roles (HR Admin, Payroll Admin, Super Admin).")
        notes.append("payer also holds salary roles")
    if payer.pk in {x for x in (advance.captured_by_id, advance.approved_by_id, advance.employee.user_id) if x}:
        if not ps.allow_role_overlap:
            raise AdvanceError("The person who captured, approved or asked for the advance cannot also pay it.")
        notes.append("payer also captured/approved/requested")
    if advance.captured_by_id and advance.captured_by_id == advance.approved_by_id:
        if not ps.allow_role_overlap:
            raise AdvanceError("The person who captured the advance cannot also approve it.")
        notes.append("captured and approved by the same person")
    return "; ".join(notes)


@transaction.atomic
def pay_advance(advance, payer, method, shift_id=None, fund_id=None, reference=''):
    if advance.status != 'APPROVED':
        raise AdvanceError("Only an approved advance can be paid.")
    ps = salary.get_pay_settings(advance.employee.company)
    if not _holds(payer, ADVANCE_PAYER, SUPER_ADMIN):
        raise AdvanceError("You are not authorised to pay advances.")
    overlap = _check_separation(advance, payer, ps)
    emp = advance.employee
    desc = f"{advance.number} salary advance: {emp.display_name} ({emp.employee_number})"
    recon_id = None
    if method == 'CASH_TILL':
        if not shift_id:
            raise AdvanceError("Choose the till (open shift) the cash comes from.")
    elif method == 'PETTY_CASH':
        if not fund_id:
            raise AdvanceError("Choose the petty cash fund.")
    elif method == 'TRANSFER':
        if not reference.strip():
            raise AdvanceError("Enter the bank reference.")
    elif method != 'WITH_PAYRUN':
        raise AdvanceError("Choose how it is paid.")
    if ps.post_advances_to_reconciliation and method != 'WITH_PAYRUN':
        try:
            if method == 'CASH_TILL':
                recon_id = recon_bridge.post_till_outflow(shift_id, advance.amount, desc, payer, ps.advance_category)
            elif method == 'PETTY_CASH':
                recon_id = recon_bridge.post_petty_outflow(fund_id, advance.amount, desc, payer)
            else:
                recon_id = recon_bridge.post_bank_outflow(advance.amount, desc + f" ref {reference}", payer, ps.advance_category)
        except recon_bridge.ReconError as e:
            raise AdvanceError(str(e))
    pay = AdvancePayment.objects.create(advance=advance, method=method, shift_id=shift_id, petty_cash_id=fund_id, amount=advance.amount,
                                        reference=reference[:100], receipt_number=f"RCP-{advance.number}", paid_by=payer,
                                        recon_expense_id=recon_id, overlap_note=overlap[:200])
    AdvanceLedger.objects.create(advance=advance, type='PAYMENT', amount=advance.amount, source=f"{pay.get_method_display()}", created_by=payer,
                                 receipt_number=pay.receipt_number)
    if advance.fee:
        AdvanceLedger.objects.create(advance=advance, type='FEE', amount=advance.fee, source='Advance fee', created_by=payer)
    advance.status, advance.paid_at = 'PAID', timezone.now()
    advance.save(update_fields=['status', 'paid_at'])
    audit.log('advance.paid', 'advances', user=payer, obj=advance, employee=emp, sensitive=True,
              new={'method': method, 'amount': str(advance.amount), 'overlap': overlap})
    if emp.user:
        notify([emp.user], 'advance', "Advance paid", f"{advance.number}: R{advance.amount} paid. Receipt {pay.receipt_number}.", reverse('hr:advances'))
    return pay


@transaction.atomic
def record_repayment(advance, amount, method, payer, shift_id=None, fund_id=None, reference=''):
    """RC-5: early settlement in cash or by transfer, with a receipt; updates the balance and the reconciliation records."""
    if advance.status not in ('PAID', 'RECOVERING'):
        raise AdvanceError("Only a paid advance can be repaid.")
    amount = q(Decimal(str(amount)))
    bal = advance.balance
    if amount <= 0 or amount > bal:
        raise AdvanceError(f"The repayment must be between R0.01 and the balance of R{bal}.")
    if not _holds(payer, ADVANCE_PAYER, SUPER_ADMIN, HR_ADMIN, PAYROLL_ADMIN):
        raise AdvanceError("You are not authorised to receive repayments.")
    ps = salary.get_pay_settings(advance.employee.company)
    desc = f"{advance.number} advance repayment: {advance.employee.display_name}"
    n = advance.ledger.filter(type='REPAYMENT').count() + 1
    if ps.post_advances_to_reconciliation:
        try:
            if method == 'CASH_TILL':
                if not shift_id:
                    raise AdvanceError("Choose the till the cash goes into.")
                recon_bridge.post_till_inflow(shift_id, amount, desc, payer, ps.advance_category)
            elif method == 'PETTY_CASH':
                if not fund_id:
                    raise AdvanceError("Choose the petty cash fund.")
                recon_bridge.post_petty_inflow(fund_id, amount, desc, payer)
            elif method == 'TRANSFER':
                recon_bridge.post_bank_outflow(-amount, desc + f" ref {reference}", payer, ps.advance_category)
        except recon_bridge.ReconError as e:
            raise AdvanceError(str(e))
    AdvanceLedger.objects.create(advance=advance, type='REPAYMENT', amount=-amount, source=method, created_by=payer,
                                 receipt_number=f"RCP-{advance.number}-R{n}")
    _refresh_status(advance)
    audit.log('advance.repaid', 'advances', user=payer, obj=advance, employee=advance.employee, sensitive=True, new={'amount': str(amount)})
    return advance


def _refresh_status(advance):
    advance.refresh_from_db()
    if advance.status in ('PAID', 'RECOVERING'):
        advance.status = 'SETTLED' if advance.balance <= 0 else 'RECOVERING'
        advance.save(update_fields=['status'])


def cancel_advance(advance, user):
    """RC-7: cancel before payment; afterwards only a repayment or write-off changes the balance."""
    if advance.status not in ('REQUESTED', 'AWAITING_APPROVAL', 'APPROVED'):
        raise AdvanceError("A paid advance cannot be cancelled. Record a repayment instead.")
    from django.contrib.contenttypes.models import ContentType
    inst = WorkflowInstance.objects.filter(content_type=ContentType.objects.get_for_model(advance), object_id=advance.pk, status='PENDING').first()
    if inst:
        workflow.withdraw(inst, user)
    advance.status = 'CANCELLED'
    advance.save(update_fields=['status'])
    advance.schedule.filter(status='PLANNED').delete()
    audit.log('advance.cancelled', 'advances', user=user, obj=advance, employee=advance.employee, sensitive=True)


# ------------------------------------------------------------------ write-off (RC-8), leavers (RC-6)
@transaction.atomic
def request_writeoff(advance, user, reason):
    if advance.status not in ('PAID', 'RECOVERING'):
        raise AdvanceError("Only an advance with an outstanding balance can be written off.")
    if advance.balance <= 0:
        raise AdvanceError("There is no balance to write off.")
    if not reason.strip():
        raise AdvanceError("A write-off needs a written reason.")
    if advance.writeoffs.filter(status='PENDING').exists():
        raise AdvanceError("A write-off is already waiting for approval.")
    wo = AdvanceWriteOff.objects.create(advance=advance, amount=advance.balance, reason=reason[:300], requested_by=user)
    workflow.start(wo, 'advance_writeoff', user, advance.employee, f"Write off R{wo.amount} of {advance.number} ({advance.employee.display_name}): {reason}")
    audit.log('advance.writeoff_requested', 'advances', user=user, obj=advance, employee=advance.employee, sensitive=True, new={'amount': str(wo.amount)})
    return wo


@transaction.atomic
def finalise_writeoff(wo, instance):
    adv = wo.advance
    amount = min(wo.amount, adv.balance)
    AdvanceLedger.objects.create(advance=adv, type='WRITE_OFF', amount=-amount, source=wo.reason[:150])
    wo.status = 'APPROVED'
    wo.save(update_fields=['status'])
    adv.status = 'WRITTEN_OFF'
    adv.save(update_fields=['status'])
    adv.schedule.filter(status='PLANNED').update(status='CARRIED')
    ps = salary.get_pay_settings(adv.employee.company)
    if ps.post_advances_to_reconciliation:
        recon_bridge.post_bank_outflow(amount, f"{adv.number} advance write-off: {adv.employee.display_name}", None, ps.writeoff_category)
    audit.log('advance.written_off', 'advances', obj=adv, employee=adv.employee, sensitive=True, new={'amount': str(amount)})


def leaver_balances(company):
    """RC-6: advances still owing after someone left, and whether the employee agreed to a final pay deduction."""
    out = []
    for adv in Advance.objects.filter(employee__company=company, status__in=('PAID', 'RECOVERING'), employee__status='TERMINATED').select_related('employee'):
        if adv.balance > 0:
            out.append({'advance': adv, 'balance': adv.balance, 'agreed': adv.final_pay_agreed})
    return out


@transaction.atomic
def record_final_pay_agreement(advance, user, note=''):
    """The employee's agreement to take the balance from final pay (RC-6). Recorded by HR when the employee agrees."""
    if not has_role(user, HR_ADMIN, SUPER_ADMIN):
        raise AdvanceError("HR records the final pay agreement.")
    ps = salary.get_pay_settings(advance.employee.company)
    AdvanceConfirmation.objects.create(advance=advance, method='FINAL_PAY', confirmed_at=timezone.now(), signed_name=advance.employee.full_name,
                                       agreement_copy=f"{ps.agreement_text}\nFinal pay deduction of R{advance.balance} agreed. {note}")
    advance.final_pay_agreed = True
    advance.save(update_fields=['final_pay_agreed'])
    audit.log('advance.final_pay_agreed', 'advances', user=user, obj=advance, employee=advance.employee, sensitive=True)


# ------------------------------------------------------------------ recovery at payrun lock (RC-3, RC-4)
def plan_recoveries(employee, gross, net_before, ps=None):
    """What would be deducted in this payrun. Returns [(advance, row_or_None, amount)]. Never takes net below zero (RC-4)
    and never more than the allowed share of pay (RC-2); any shortfall moves to the next payrun."""
    out = []
    remaining_net = q(net_before)
    pol, _ = policy_for(employee)
    pct = (pol.max_recovery_percent_of_pay if pol else Decimal(50)) / Decimal(100)
    cap = q(gross * pct) if gross else remaining_net
    for adv in Advance.objects.filter(employee=employee, status__in=('PAID', 'RECOVERING')).order_by('paid_at'):
        bal = adv.balance
        if bal <= 0:
            continue
        if employee.status == 'TERMINATED' and adv.final_pay_agreed:
            amount = min(bal, remaining_net)                          # final pay: agreed balance comes off in full
            out.append((adv, None, q(max(amount, Decimal('0')))))
            remaining_net -= amount
            continue
        row = adv.schedule.filter(status='PLANNED').order_by('sequence').first()
        due = row.amount if row else bal
        amount = min(due, bal, remaining_net, cap)
        amount = q(max(amount, Decimal('0')))
        out.append((adv, row, amount))
        remaining_net -= amount
        cap -= amount
    return out


@transaction.atomic
def apply_recoveries(line, run, user):
    """Called when a payrun is locked: takes the scheduled deduction, records it in the ledger, updates the payslip line."""
    total = Decimal('0')
    for adv, row, amount in plan_recoveries(line.employee, line.gross, line.net):
        if amount > 0:
            AdvanceLedger.objects.create(advance=adv, type='DEDUCTION', amount=-amount, pay_period=run.pay_period, created_by=user,
                                         date=run.pay_period.pay_date or run.pay_period.end_date, source=f"Payrun {run.pay_period.label}")
            total += amount
        if row is not None:
            row.pay_period, row.deducted = run.pay_period, amount
            shortfall = row.amount - amount
            row.status = 'DEDUCTED' if shortfall <= 0 else 'CARRIED'
            row.save()
            if shortfall > 0 and adv.balance > 0:
                nxt = adv.schedule.filter(status='PLANNED').order_by('sequence').first()
                if nxt:
                    nxt.amount += shortfall
                    nxt.save(update_fields=['amount'])
                else:
                    RecoverySchedule.objects.create(advance=adv, sequence=row.sequence + 1, amount=shortfall)
        _refresh_status(adv)
    return q(total)


# ------------------------------------------------------------------ reports (Section 7)
def report_by_person_month(company, start, end):
    rows = {}
    for p in AdvancePayment.objects.filter(advance__employee__company=company, paid_at__date__range=(start, end)).select_related('advance__employee'):
        k = (p.advance.employee, f"{p.paid_at.year}-{p.paid_at.month:02d}")
        r = rows.setdefault(k, {'employee': k[0], 'month': k[1], 'count': 0, 'total': Decimal('0')})
        r['count'] += 1
        r['total'] += p.amount
    return sorted(rows.values(), key=lambda r: (r['month'], r['employee'].surname))


def report_outstanding(company):
    today = timezone.localdate()
    out = []
    for adv in Advance.objects.filter(employee__company=company, status__in=('PAID', 'RECOVERING')).select_related('employee'):
        bal = adv.balance
        if bal > 0:
            out.append({'advance': adv, 'balance': bal, 'age_days': (today - (local_date(adv.paid_at) if adv.paid_at else today)).days})
    return sorted(out, key=lambda r: -r['age_days'])


def report_schedule(company):
    return RecoverySchedule.objects.filter(advance__employee__company=company, status='PLANNED').select_related('advance__employee').order_by('advance', 'sequence')


def report_by_source(company, start, end):
    rows = {}
    for p in AdvancePayment.objects.filter(advance__employee__company=company, paid_at__date__range=(start, end)):
        label = p.get_method_display()
        if p.method == 'CASH_TILL':
            label += f" (shift {p.shift_id})"
        elif p.method == 'PETTY_CASH':
            label += f" (fund {p.petty_cash_id})"
        rows.setdefault(label, {'source': label, 'count': 0, 'total': Decimal('0')})
        rows[label]['count'] += 1
        rows[label]['total'] += p.amount
    return list(rows.values())


def report_exceptions(company):
    return Advance.objects.filter(employee__company=company, emergency=True).select_related('employee', 'approved_by', 'captured_by')


def unpaid_flags(company):
    ps = salary.get_pay_settings(company)
    cutoff = timezone.now() - timedelta(days=ps.unpaid_approved_flag_days)
    return list(Advance.objects.filter(employee__company=company, status='APPROVED', created_at__lte=cutoff).select_related('employee'))


def owed_as_of(end):
    """LK-4: the unrecovered balance of all advances at a date, for the balance sheet (staff advances owed to the business)."""
    total = AdvanceLedger.objects.filter(date__lte=end).aggregate(t=Sum('amount'))['t']
    return q(total) if total else Decimal('0')

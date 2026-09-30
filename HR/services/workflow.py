"""The one approval engine every request uses (leave, profile changes,
payrun input, documents, shift changes).

A request has a submitter, an ordered chain of approval steps taken from its
WorkflowDefinition, a status, an escalation timer, notifications at each step
and an audit entry for each decision. The thing being approved (the "subject")
only has to provide three hooks:

    on_workflow_approved(instance)
    on_workflow_rejected(instance, reason)
    on_workflow_withdrawn(instance)
"""
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from ..models import (
    ApprovalStep, Delegation, WorkflowDefinition, WorkflowInstance, RoleAssignment,
    HR_ADMIN, LINE_MANAGER, PAYROLL_ADMIN, SUPER_ADMIN,
)
from . import audit
from .access import roles_for
from .notify import notify

DEFAULT_CHAINS = {
    'leave': [LINE_MANAGER],
    'change_standard': [HR_ADMIN],
    'change_banking': [HR_ADMIN, PAYROLL_ADMIN],
    'payrun_input': [LINE_MANAGER, PAYROLL_ADMIN],
    'document_request': [HR_ADMIN],
    'shift_change': [LINE_MANAGER],
    'salary_change': [PAYROLL_ADMIN],
    'salary_change_large': [PAYROLL_ADMIN, 'SENIOR_MANAGER'],
    'advance_small': [LINE_MANAGER],
    'advance_large': ['SENIOR_MANAGER'],
    'advance_emergency': [LINE_MANAGER, 'SENIOR_MANAGER'],
    'advance_writeoff': ['SENIOR_MANAGER'],
}


class WorkflowError(Exception):
    """A rule of the workflow was broken; the message is safe to show the user."""


def ensure_definition(company, key):
    definition, _ = WorkflowDefinition.objects.get_or_create(
        company=company, key=key,
        defaults={'name': dict(WorkflowDefinition.KEY_CHOICES).get(key, key), 'steps': DEFAULT_CHAINS.get(key, [HR_ADMIN])},
    )
    return definition


def add_working_days(start, days):
    """Skip weekends when setting a due date (public holidays are not known here)."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


# --------------------------------------------------------------- who approves
def _delegator_ids(user, day=None):
    day = day or timezone.localdate()
    return set(Delegation.objects.filter(delegate=user, start_date__lte=day, end_date__gte=day).values_list('delegator_id', flat=True))


def _line_manager_user(employee, submitter):
    """The nearest manager above the employee who has a login and is not the
    person asking (nobody approves their own request)."""
    if employee is None:
        return None
    for mgr in employee.reports_chain():
        if mgr.user_id and mgr.user_id != submitter.pk:
            return mgr.user
    return None


def _role_holders(role):
    users = [ra.user for ra in RoleAssignment.objects.filter(role=role).select_related('user')]
    if role == SUPER_ADMIN:
        from django.contrib.auth import get_user_model
        users += list(get_user_model().objects.filter(is_superuser=True, is_active=True))
    return users


def _approvers_to_notify(step):
    if step.assigned_to_id:
        delegates = Delegation.objects.filter(
            delegator_id=step.assigned_to_id, start_date__lte=timezone.localdate(), end_date__gte=timezone.localdate()
        ).select_related('delegate')
        return [step.assigned_to] + [d.delegate for d in delegates]
    holders = _role_holders(step.role)
    if not holders:
        holders = _role_holders(SUPER_ADMIN)
    return holders


def can_act(step, user):
    """Whether this person may decide this step right now."""
    if step.status != 'PENDING':
        return False
    inst = step.instance
    if user.pk == inst.submitter_id:
        return False
    if inst.employee_id and inst.employee.user_id == user.pk:
        return False
    # One person cannot be both approvers of the same request (banking needs two).
    if inst.steps.filter(acted_by=user, status='APPROVED').exists():
        return False
    roles = roles_for(user)
    if SUPER_ADMIN in roles:
        return True
    if step.role in (PAYROLL_ADMIN, 'SENIOR_MANAGER'):
        return step.role in roles      # no HR override on payroll or senior management steps
    if HR_ADMIN in roles:
        return True    # HR override
    if step.assigned_to_id:
        return step.assigned_to_id == user.pk or step.assigned_to_id in _delegator_ids(user)
    return step.role in roles


def pending_steps_for(user):
    """Approval steps waiting on this person (their own queue)."""
    roles = roles_for(user)
    q = Q(assigned_to=user) | Q(assigned_to_id__in=_delegator_ids(user))
    q |= Q(assigned_to__isnull=True, role__in=roles)
    if SUPER_ADMIN in roles:
        q = Q()
    elif HR_ADMIN in roles:
        q |= ~Q(role__in=(PAYROLL_ADMIN, 'SENIOR_MANAGER'))
    steps = ApprovalStep.objects.filter(q, status='PENDING', instance__status='PENDING').select_related(
        'instance', 'instance__employee', 'instance__submitter').order_by('due_at', 'id')
    return [s for s in steps if can_act(s, user)]


# ------------------------------------------------------------------- engine
@transaction.atomic
def start(subject, key, submitter, employee, summary, company=None):
    company = company or (employee.company if employee else None)
    definition = ensure_definition(company, key)
    inst = WorkflowInstance.objects.create(
        company=company, key=key, content_type=ContentType.objects.get_for_model(subject),
        object_id=subject.pk, submitter=submitter, employee=employee, summary=summary[:255],
    )
    for order, role in enumerate(definition.steps, start=1):
        ApprovalStep.objects.create(instance=inst, order=order, role=role)
    audit.log('workflow.submit', 'workflow', user=submitter, obj=inst, employee=employee, description=summary)
    _activate_next(inst, definition)
    return inst


def _activate_next(inst, definition=None):
    definition = definition or ensure_definition(inst.company, inst.key)
    step = inst.steps.filter(status='WAITING').order_by('order').first()
    if step is None:
        if not inst.steps.filter(status='PENDING').exists():
            _complete(inst, 'APPROVED')
        return
    if step.role == LINE_MANAGER:
        manager_user = _line_manager_user(inst.employee, inst.submitter)
        if manager_user is None:
            # No manager above the requester with a login: escalate straight to HR.
            step.role = HR_ADMIN
            step.escalated = True
            step.comment = "No line manager found - escalated to HR."
        else:
            step.assigned_to = manager_user
    step.status = 'PENDING'
    step.activated_at = timezone.now()
    step.due_at = add_working_days(step.activated_at, definition.escalation_days)
    step.save()
    notify(
        _approvers_to_notify(step), 'APPROVAL', f"Approval needed: {inst.summary}",
        f"{inst.submitter.get_full_name() or inst.submitter.get_username()} submitted a request: {inst.summary}.",
        reverse('hr:manage_approvals'),
    )


def _complete(inst, status, reason=''):
    inst.status = status
    inst.completed_at = timezone.now()
    inst.save(update_fields=['status', 'completed_at'])
    subject = inst.subject
    if subject is not None:
        if status == 'APPROVED' and hasattr(subject, 'on_workflow_approved'):
            subject.on_workflow_approved(inst)
        elif status == 'REJECTED' and hasattr(subject, 'on_workflow_rejected'):
            subject.on_workflow_rejected(inst, reason)
        elif status == 'WITHDRAWN' and hasattr(subject, 'on_workflow_withdrawn'):
            subject.on_workflow_withdrawn(inst)
    who = [inst.submitter] + ([inst.employee.user] if inst.employee_id and inst.employee.user_id else [])
    verb = {'APPROVED': 'approved', 'REJECTED': 'declined', 'WITHDRAWN': 'withdrawn'}[status]
    if status != 'WITHDRAWN':
        notify(who, 'DECISION', f"Request {verb}: {inst.summary}",
               (f"Reason: {reason}" if reason else f"Your request was {verb}."), reverse('hr:portal_notifications'))


@transaction.atomic
def approve(step, user, comment='', on_behalf=False):
    """on_behalf lets HR approve a request it captured for an employee (for
    example sick leave phoned in), where the person asking cannot approve it."""
    if on_behalf:
        if step.status != 'PENDING' or not (roles_for(user) & {HR_ADMIN, SUPER_ADMIN}):
            raise WorkflowError("You cannot approve this request.")
    elif not can_act(step, user):
        raise WorkflowError("You cannot approve this request.")
    step.status = 'APPROVED'
    step.acted_by = user
    step.acted_at = timezone.now()
    step.comment = comment or step.comment
    step.save()
    audit.log('workflow.approve', 'workflow', user=user, obj=step.instance, employee=step.instance.employee,
              description=step.instance.summary, new={'step': step.order, 'role': step.role, 'comment': comment})
    _activate_next(step.instance)


@transaction.atomic
def reject(step, user, comment):
    if not (comment or '').strip():
        raise WorkflowError("A reason is required when declining a request.")
    if not can_act(step, user):
        raise WorkflowError("You cannot decline this request.")
    step.status = 'REJECTED'
    step.acted_by = user
    step.acted_at = timezone.now()
    step.comment = comment
    step.save()
    inst = step.instance
    inst.steps.filter(status__in=['WAITING', 'PENDING']).update(status='CANCELLED')
    audit.log('workflow.reject', 'workflow', user=user, obj=inst, employee=inst.employee,
              description=inst.summary, new={'step': step.order, 'role': step.role, 'reason': comment})
    _complete(inst, 'REJECTED', comment)


@transaction.atomic
def withdraw(inst, user):
    """The requester can take a request back until it is finally approved."""
    if inst.status != 'PENDING':
        raise WorkflowError("This request has already been decided.")
    if user.pk != inst.submitter_id:
        raise WorkflowError("Only the person who submitted the request can withdraw it.")
    pending = list(inst.steps.filter(status='PENDING').select_related('assigned_to'))
    inst.steps.filter(status__in=['WAITING', 'PENDING']).update(status='CANCELLED')
    audit.log('workflow.withdraw', 'workflow', user=user, obj=inst, employee=inst.employee, description=inst.summary)
    _complete(inst, 'WITHDRAWN')
    approvers = [u for s in pending for u in _approvers_to_notify(s)]
    notify(approvers, 'DECISION', f"Request withdrawn: {inst.summary}", "The requester withdrew this request.", reverse('hr:manage_approvals'))


def escalate_overdue(now=None):
    """Remind an approver when a step is overdue, then escalate to HR if it
    stays unanswered another interval. Run daily (hr_run_escalations)."""
    now = now or timezone.now()
    reminded = escalated = 0
    for step in ApprovalStep.objects.filter(status='PENDING', due_at__lt=now, instance__status='PENDING').select_related('instance'):
        definition = ensure_definition(step.instance.company, step.instance.key)
        if step.reminded_at is None:
            step.reminded_at = now
            step.due_at = add_working_days(now, definition.escalation_days)
            step.save(update_fields=['reminded_at', 'due_at'])
            notify(_approvers_to_notify(step), 'OVERDUE', f"Approval overdue: {step.instance.summary}",
                   "This request is waiting for your decision.", reverse('hr:manage_approvals'))
            reminded += 1
        elif not step.escalated:
            step.escalated = True
            step.role = HR_ADMIN
            step.assigned_to = None
            step.due_at = add_working_days(now, definition.escalation_days)
            step.comment = (step.comment + " Escalated to HR after no response.").strip()
            step.save()
            notify(_approvers_to_notify(step), 'OVERDUE', f"Escalated to HR: {step.instance.summary}",
                   "This request was not answered in time and has been escalated.", reverse('hr:manage_approvals'))
            escalated += 1
    return reminded, escalated

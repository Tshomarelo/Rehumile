"""Biographical change requests: nothing changes until the workflow approves."""
import json

from django.db import transaction
from django.utils import timezone

from . import audit, workflow
from ..models import Address, BankAccount, ChangeRequest, Dependant, EmergencyContact, Qualification

# section -> (label, model or None for Employee, fields, list?, proof required, workflow key)
SECTIONS = {
    'contact': ('Contact details', None, ['phone', 'personal_email'], False, False, 'change_standard'),
    'address': ('Home address', Address, ['street', 'suburb', 'city', 'province', 'postal_code', 'country'], False, True, 'change_standard'),
    'emergency': ('Emergency contacts', EmergencyContact, ['name', 'relationship', 'phone', 'alt_phone'], True, False, 'change_standard'),
    'dependant': ('Dependants', Dependant, ['name', 'relationship', 'date_of_birth'], True, False, 'change_standard'),
    'bank': ('Banking details', BankAccount, ['bank_name', 'account_holder', 'account_number', 'branch_code', 'account_type'], False, True, 'change_banking'),
    'qualification': ('Qualifications', Qualification, ['title', 'institution', 'year_obtained', 'level'], True, False, 'change_standard'),
}
SENSITIVE = {'account_number'}
FIELD_LABELS = {'phone': 'Phone', 'personal_email': 'Personal email', 'street': 'Street', 'suburb': 'Suburb', 'city': 'City',
                'province': 'Province', 'postal_code': 'Postal code', 'country': 'Country', 'name': 'Name',
                'relationship': 'Relationship', 'alt_phone': 'Alternative phone', 'date_of_birth': 'Date of birth',
                'bank_name': 'Bank', 'account_holder': 'Account holder', 'account_number': 'Account number',
                'branch_code': 'Branch code', 'account_type': 'Account type', 'title': 'Title',
                'institution': 'Institution', 'year_obtained': 'Year', 'level': 'Level'}


def current_values(employee, section, target_id=None):
    _, model, fields, is_list, _, _ = SECTIONS[section]
    if model is None:
        obj = employee
    elif is_list:
        obj = model.objects.filter(pk=target_id, employee=employee).first() if target_id else None
    else:
        obj = model.objects.filter(employee=employee).first()
    return {f: ('' if getattr(obj, f, None) is None else str(getattr(obj, f))) for f in fields} if obj else {}


def diff_rows(cr):
    old = json.loads(cr.old_payload or '{}')
    new = json.loads(cr.new_payload or '{}')
    fields = SECTIONS[cr.section][2]
    rows = []
    for f in fields:
        o, n = old.get(f, ''), new.get(f, '')
        if cr.action == 'REMOVE':
            n = '(removed)'
        if o != n or cr.action == 'ADD':
            rows.append({'label': FIELD_LABELS.get(f, f), 'old': o, 'new': n, 'changed': o != n})
    return rows


@transaction.atomic
def submit(employee, user, section, action, values, target_id=None, proof=None):
    label, model, fields, is_list, proof_needed, key = SECTIONS[section]
    if proof_needed and action != 'REMOVE' and not proof:
        raise workflow.WorkflowError("Proof is required for this change (for example a utility bill or a bank letter).")
    if ChangeRequest.objects.filter(employee=employee, section=section, target_id=target_id, status='PENDING').exists():
        raise workflow.WorkflowError("There is already a pending change for this. Wait for it to be decided or withdraw it.")
    old = current_values(employee, section, target_id)
    new = {f: str(values.get(f, '') or '') for f in fields}
    if action == 'UPDATE' and old == new:
        raise workflow.WorkflowError("Nothing was changed.")
    cr = ChangeRequest.objects.create(
        employee=employee, section=section, action=action, target_id=target_id,
        old_payload=json.dumps(old), new_payload=json.dumps(new), proof=proof or None)
    audit.log('change.submit', 'biographical', user=user, obj=cr, employee=employee,
              new={'section': section, 'action': action}, sensitive=section == 'bank')
    workflow.start(cr, key, user, employee, f"{label}: {cr.get_action_display().lower()} for {employee.display_name}")
    return cr


@transaction.atomic
def apply_request(cr):
    _, model, fields, is_list, _, _ = SECTIONS[cr.section]
    emp = cr.employee
    new = json.loads(cr.new_payload or '{}')
    clean = {k: (v or None if k in ('date_of_birth', 'year_obtained') else v) for k, v in new.items()}
    if model is None:
        for k, v in new.items():
            setattr(emp, k, v)
        emp.save(update_fields=list(new))
    elif is_list:
        if cr.action == 'ADD':
            model.objects.create(employee=emp, **clean)
        elif cr.action == 'REMOVE':
            model.objects.filter(pk=cr.target_id, employee=emp).delete()
        else:
            model.objects.filter(pk=cr.target_id, employee=emp).update(**clean)
    else:
        model.objects.update_or_create(employee=emp, defaults=clean)
    cr.status = 'APPROVED'
    cr.applied_at = timezone.now()
    cr.save(update_fields=['status', 'applied_at'])
    audit.log('change.applied', 'biographical', obj=cr, employee=emp, new={'section': cr.section}, sensitive=cr.section == 'bank')

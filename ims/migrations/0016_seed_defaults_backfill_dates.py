"""Data migration: seed editable website content/prices, fix placeholder content, backfill invoice dates."""
from django.db import migrations
from django.db.models import F


def seed_and_backfill(apps, schema_editor):
    from ims.website_defaults import (
        CONTENT_DEFAULTS, PRICE_DEFAULTS, LEGACY_FAKE_VALUES, LEGACY_FAKE_ADDRESS,
    )
    WebsiteContent = apps.get_model('ims', 'WebsiteContent')
    ServicePrice = apps.get_model('ims', 'ServicePrice')
    Invoice = apps.get_model('ims', 'Invoice')

    defaults = {k: (s, l, v) for s, k, l, v in CONTENT_DEFAULTS}
    # An earlier editor seeded placeholder contact details; replace only untouched placeholders.
    for key, fake in LEGACY_FAKE_VALUES.items():
        if key in defaults:
            WebsiteContent.objects.filter(key=key, value=fake).update(value=defaults[key][2])
    WebsiteContent.objects.filter(key='contact_address', value=LEGACY_FAKE_ADDRESS).update(
        value='Jozini, KwaZulu-Natal')
    for section, key, label, value in CONTENT_DEFAULTS:
        WebsiteContent.objects.get_or_create(key=key, defaults={'section': section, 'label': label, 'value': value})

    for order, (group, category, name, price, unit, desc, prefix) in enumerate(PRICE_DEFAULTS):
        ServicePrice.objects.get_or_create(
            group=group, name=name,
            defaults={'category': category, 'price': price, 'unit': unit, 'description': desc,
                      'price_prefix': prefix, 'display_order': order, 'is_active': True},
        )

    # Paid/sent invoices created before dates were stamped: use the best date we have.
    Invoice.objects.filter(status__in=['sent', 'paid', 'overdue'], sent_at__isnull=True).update(sent_at=F('created_at'))
    for inv in Invoice.objects.filter(status='paid', payment_date__isnull=True).only('id', 'updated_at'):
        Invoice.objects.filter(pk=inv.pk).update(payment_date=inv.updated_at.date())


class Migration(migrations.Migration):

    dependencies = [
        ('ims', '0015_finance_quotations_payroll'),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, migrations.RunPython.noop),
    ]

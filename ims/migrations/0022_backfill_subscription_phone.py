"""Copy contact phone numbers from WiFi subscribers / SLA contracts onto their mirrored subscriptions."""
from django.db import migrations


def forward(apps, schema_editor):
    Subscription = apps.get_model('ims', 'Subscription')
    for sub in Subscription.objects.filter(contact_phone='').select_related('legacy_wifi', 'legacy_sla'):
        src = sub.legacy_wifi or sub.legacy_sla
        if src is not None and src.contact_phone:
            sub.contact_phone = src.contact_phone
            sub.save(update_fields=['contact_phone'])


class Migration(migrations.Migration):
    dependencies = [('ims', '0021_collections_recurring')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]

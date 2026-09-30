"""Mirror existing WiFi subscribers and SLA contracts into the unified Subscription list."""
from django.db import migrations


def forward(apps, schema_editor):
    from ims.subscription_sync import mirror_wifi_fields, mirror_sla_fields
    WifiSubscriber = apps.get_model('ims', 'WifiSubscriber')
    SLAContract = apps.get_model('ims', 'SLAContract')
    Subscription = apps.get_model('ims', 'Subscription')
    for w in WifiSubscriber.objects.all():
        if not Subscription.objects.filter(legacy_wifi=w).exists():
            sub = Subscription(legacy_wifi=w, service_type='wifi', quantity=1,
                               description='WiFi / Internet' + (f' ({w.axxess_id})' if w.axxess_id else ''),
                               start_date=w.created_at.date())
            mirror_wifi_fields(sub, w)
            sub.save()
    for c in SLAContract.objects.all():
        if not Subscription.objects.filter(legacy_sla=c).exists():
            sub = Subscription(legacy_sla=c, service_type='sla', quantity=1,
                               description=(c.contract_description or 'SLA monthly retainer')[:255], start_date=c.contract_start)
            mirror_sla_fields(sub, c)
            sub.save()


class Migration(migrations.Migration):
    dependencies = [('ims', '0019_subscriptions_branches')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]

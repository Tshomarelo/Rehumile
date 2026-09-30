"""
Keeps Subscription rows in step with the older WiFi-subscriber and SLA-contract records.

Those records stay the place where WiFi lines (Axxess import, loss-making flags) and SLA
contracts (call-out invoices) are entered. Price, cost, status, dates and client come from
them; the *branch* and the invoice wording belong to the Subscription and are never overwritten.
"""


def mirror_wifi_fields(sub, w):
    sub.company_id = w.company_id
    sub.client_name = w.client_name
    sub.contact_email = w.contact_email
    sub.unit_price = w.retail_price
    sub.unit_cost = w.wholesale_cost
    sub.billing_day = w.billing_day or 1
    sub.status = w.status
    sub.axxess_id = w.axxess_id
    sub.notes = w.notes


def mirror_sla_fields(sub, c):
    sub.company_id = c.company_id
    sub.client_name = c.client_name
    sub.contact_email = c.contact_email
    sub.unit_price = c.monthly_retainer
    sub.unit_cost = 0
    sub.billing_day = c.billing_day or 1
    sub.status = c.status
    sub.start_date = c.contract_start
    sub.end_date = c.contract_end
    sub.notes = c.notes


def on_wifi_saved(sender, instance, **kwargs):
    from .models import Subscription
    sub = Subscription.objects.filter(legacy_wifi=instance).first()
    if sub is None:
        sub = Subscription(legacy_wifi=instance, service_type='wifi', quantity=1,
                           description='WiFi / Internet' + (f' ({instance.axxess_id})' if instance.axxess_id else ''),
                           start_date=(instance.created_at or __import__('datetime').datetime.now()).date())
    mirror_wifi_fields(sub, instance)
    if sub.site_id and sub.site.company_id != sub.company_id:
        sub.site = None     # the client changed: a branch of the old client no longer applies
    sub.save()


def on_sla_saved(sender, instance, **kwargs):
    from .models import Subscription
    sub = Subscription.objects.filter(legacy_sla=instance).first()
    if sub is None:
        sub = Subscription(legacy_sla=instance, service_type='sla', quantity=1,
                           description=(instance.contract_description or 'SLA monthly retainer')[:255])
    mirror_sla_fields(sub, instance)
    if sub.site_id and sub.site.company_id != sub.company_id:
        sub.site = None
    sub.save()


def connect():
    from django.db.models.signals import post_save
    from .models import SLAContract, WifiSubscriber
    post_save.connect(on_wifi_saved, sender=WifiSubscriber, dispatch_uid='sub_sync_wifi')
    post_save.connect(on_sla_saved, sender=SLAContract, dispatch_uid='sub_sync_sla')

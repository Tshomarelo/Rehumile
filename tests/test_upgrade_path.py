"""
The live server already ran migrations 0012-0014 (partial payments, the first Subscription table, bank
reconciliation). This builds a database exactly at that point, adds real-looking rows, then runs the
remaining migrations and checks nothing was lost or broken.
"""
import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(code, db, *args):
    env = dict(os.environ, DJANGO_SETTINGS_MODULE='config.settings_test', TEST_DB=db)
    if args:
        cmd = [sys.executable, 'manage.py', *args, '--settings=config.settings_test']
    else:
        cmd = [sys.executable, '-c', textwrap.dedent(code)]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
    return r.stdout


SEED = '''
import django; django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
apps = MigrationExecutor(connection).loader.project_state([("ims", "0014_bank_reconciliation")]).apps
from datetime import date
Company = apps.get_model("ims", "Company"); Subscription = apps.get_model("ims", "Subscription")
Invoice = apps.get_model("ims", "Invoice"); Payment = apps.get_model("ims", "InvoicePayment")
Stmt = apps.get_model("ims", "BankStatement")
co = Company.objects.create(name="Maputalandfm", slug="maputalandfm", contact_person="P", contact_email="a@b.co")
Subscription.objects.create(subscription_type="hosting", service_name="cPanel hosting", client_name="Maputalandfm", company=co,
                            monthly_price=1000, monthly_cost=300, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))
Subscription.objects.create(subscription_type="domain", service_name="maputaland.fm", client_name="Domain Client",
                            contact_name="Sipho", monthly_price=50, monthly_cost=20)   # no start date, a type we fold into "other"
inv = Invoice.objects.create(invoice_number="INV-2026-08-001", company=co, billing_period_start=date(2026, 8, 1),
                             billing_period_end=date(2026, 8, 31), subtotal=1000, tax_amount=0, total_amount=1000,
                             ticket_count=0, hours_worked=0, status="partially_paid", amount_paid=400, invoice_type="subscription")
Payment.objects.create(invoice=inv, amount=400, payment_date=date(2026, 8, 20), payment_method="eft")
Stmt.objects.create(label="FNB July")
'''

CHECK = '''
import django; django.setup()
from ims.models import Subscription, Invoice, InvoicePayment, BankStatement, Company
assert Subscription.objects.count() == 2, Subscription.objects.count()
h = Subscription.objects.get(client_name="Maputalandfm")
assert (h.service_type, float(h.unit_price), float(h.unit_cost), float(h.quantity)) == ("hosting", 1000.0, 300.0, 1.0)
assert h.company.name == "Maputalandfm" and str(h.start_date) == "2026-08-01" and str(h.end_date) == "2026-08-31"
assert "cPanel hosting" in h.description
d = Subscription.objects.get(client_name="Domain Client")
assert d.service_type == "other" and "Domain registration" in d.description and "Sipho" in d.notes and d.start_date is not None
inv = Invoice.objects.get(invoice_number="INV-2026-08-001")
assert inv.status == "partially_paid" and float(inv.amount_paid) == 400 and float(inv.balance_due) == 600
assert InvoicePayment.objects.filter(invoice=inv).count() == 1 and BankStatement.objects.count() == 1
# the converted table is fully usable through the new model
from ims import billing
from datetime import date
billing._today = lambda: date(2026, 9, 1)
made = billing.generate(2026, 9)
assert len(made) == 1 and float(made[0].total_amount) == 50   # the hosting row ended on 31 Aug, so only the domain is billed
print('OK')
'''


def test_upgrade_from_the_server_schema_keeps_data(tmp_path):
    db = str(tmp_path / 'upgrade.sqlite3')
    run(None, db, 'migrate', 'ims', '0014', '--noinput', '-v', '0')
    run(SEED, db)
    run(None, db, 'migrate', '--noinput', '-v', '0')
    out = run(CHECK, db)
    assert 'OK' in out

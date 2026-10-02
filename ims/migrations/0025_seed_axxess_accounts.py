"""The three Axxess accounts and what Axxess charges on each (as supplied by the owner). Safe to re-run."""
from django.db import migrations

ACCOUNTS = [
    ('379248', 'Maputaland FM + Thebado head office', '1398.00'),
    ('343721', 'Thebado Mthombeni, Zisize, Ekasi, Manguzi, Jozini', '2655.00'),
    ('296356', "Owner's house, Nethezeka, Ingwavuma, Bosealetse, Richards Bay", '2175.00'),
]


def seed(apps, schema_editor):
    SupplierAccount = apps.get_model('ims', 'SupplierAccount')
    for number, name, total in ACCOUNTS:
        SupplierAccount.objects.get_or_create(account_number=number, defaults={'supplier': 'Axxess', 'name': name, 'charged_total': total})


class Migration(migrations.Migration):
    dependencies = [('ims', '0024_supplier_accounts_expense_payments')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

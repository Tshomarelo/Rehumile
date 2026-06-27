from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ims', '0009_invoice_company_nullable'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompanySettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('company_name', models.CharField(default='Rehumile TMW', max_length=200)),
                ('phone', models.CharField(default='', max_length=50)),
                ('email', models.EmailField(default='')),
                ('address', models.TextField(blank=True, default='')),
                ('website', models.URLField(blank=True, default='')),
                ('vat_number', models.CharField(blank=True, default='', max_length=50)),
                ('account_name', models.CharField(default='', max_length=100)),
                ('bank_name', models.CharField(default='', max_length=100)),
                ('account_number', models.CharField(default='', max_length=50)),
                ('branch_code', models.CharField(default='', max_length=20)),
                ('swift_code', models.CharField(blank=True, default='', max_length=20)),
                ('vat_rate', models.DecimalField(decimal_places=4, default=0.0, max_digits=5)),
                ('payment_terms', models.TextField(
                    default='Payment is due as per terms. Please use the invoice number as reference. '
                            'Late payments may attract interest as per our standard terms.'
                )),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'company_settings',
            },
        ),
    ]

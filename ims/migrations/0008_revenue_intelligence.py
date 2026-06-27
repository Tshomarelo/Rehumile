from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('ims', '0007_payments_model'),
    ]

    operations = [
        # ── WiFi Subscribers ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='WifiSubscriber',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('axxess_id', models.CharField(blank=True, max_length=150)),
                ('client_name', models.CharField(db_index=True, max_length=255)),
                ('contact_name', models.CharField(blank=True, max_length=255)),
                ('contact_email', models.EmailField(blank=True)),
                ('contact_phone', models.CharField(blank=True, max_length=20)),
                ('company', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='wifi_subscriptions', to='ims.company')),
                ('retail_price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('wholesale_cost', models.DecimalField(decimal_places=2, max_digits=10)),
                ('billing_day', models.IntegerField(default=1)),
                ('status', models.CharField(choices=[('active', 'Active'), ('suspended', 'Suspended'), ('cancelled', 'Cancelled')], db_index=True, default='active', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'wifi_subscribers', 'ordering': ['client_name']},
        ),
        # ── SLA Contracts ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name='SLAContract',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('client_name', models.CharField(db_index=True, max_length=255)),
                ('contact_name', models.CharField(blank=True, max_length=255)),
                ('contact_email', models.EmailField(blank=True)),
                ('contact_phone', models.CharField(blank=True, max_length=20)),
                ('company', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sla_contracts', to='ims.company')),
                ('monthly_retainer', models.DecimalField(decimal_places=2, max_digits=10)),
                ('contract_description', models.TextField(blank=True)),
                ('contract_start', models.DateField()),
                ('contract_end', models.DateField(blank=True, null=True)),
                ('billing_day', models.IntegerField(default=1)),
                ('status', models.CharField(choices=[('active', 'Active'), ('suspended', 'Suspended'), ('cancelled', 'Cancelled')], db_index=True, default='active', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'sla_contracts', 'ordering': ['client_name']},
        ),
        # ── Revenue Allocation Settings ────────────────────────────────────────
        migrations.CreateModel(
            name='RevenueAllocation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reinvestment_pct', models.DecimalField(decimal_places=4, default=0.15, max_digits=5)),
                ('opex_pct', models.DecimalField(decimal_places=4, default=0.15, max_digits=5)),
                ('owner_pct', models.DecimalField(decimal_places=4, default=0.70, max_digits=5)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'revenue_allocation'},
        ),
        # ── Invoice — new fields ───────────────────────────────────────────────
        migrations.AddField(
            model_name='invoice',
            name='invoice_type',
            field=models.CharField(
                choices=[('wifi', 'WiFi Subscription'), ('sla', 'SLA Monthly Retainer'), ('callout', 'SLA Call-Out'), ('adhoc', 'Ad-Hoc / Project')],
                db_index=True, default='adhoc', max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='wifi_subscriber',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='invoices', to='ims.wifisubscriber'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='sla_contract',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='invoices', to='ims.slacontract'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='wholesale_cost',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='description',
            field=models.CharField(blank=True, max_length=500),
        ),
    ]

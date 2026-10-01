from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ims", "0022_backfill_subscription_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="invoice_separately",
            field=models.BooleanField(
                default=False,
                help_text="Give this service its own invoice instead of combining it with the client's other services",
            ),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="service_type",
            field=models.CharField(
                choices=[
                    ("wifi", "WiFi / Internet"),
                    ("email", "Email hosting"),
                    ("hosting", "Website hosting"),
                    ("domain", "Domain"),
                    ("sla", "SLA retainer"),
                    ("other", "Other service"),
                ],
                db_index=True,
                default="wifi",
                max_length=20,
            ),
        ),
    ]

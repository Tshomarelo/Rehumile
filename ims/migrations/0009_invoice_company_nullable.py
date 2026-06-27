from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ims', '0008_revenue_intelligence'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoice',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoices',
                to='ims.company',
                db_index=True,
            ),
        ),
    ]

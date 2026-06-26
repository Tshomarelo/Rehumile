from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ims', '0002_presenter_show_schedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='incident',
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='invoices',
                to='ims.incident',
            ),
        ),
    ]

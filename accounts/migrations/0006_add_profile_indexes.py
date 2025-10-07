"""Add indexes to UserProfile search fields."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_alter_user_managers"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="company",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=100,
                verbose_name="公司",
            ),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="location",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=100,
                verbose_name="位置",
            ),
        ),
    ]

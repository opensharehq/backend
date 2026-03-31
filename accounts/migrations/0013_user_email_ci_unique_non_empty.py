"""Add a case-insensitive unique constraint for non-empty user emails."""

from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    """Enforce case-insensitive uniqueness for non-empty user emails."""

    dependencies = [
        ("accounts", "0012_refreshtoken"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="accounts_user_email_ci_unique_non_empty",
            ),
        ),
    ]

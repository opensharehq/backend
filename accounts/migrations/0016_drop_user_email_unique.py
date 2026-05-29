"""Drop the case-insensitive unique constraint on user email.

Email addresses are no longer unique nor validated since the email/password
sign-up flow has been removed in favor of social-only authentication.
"""

from django.db import migrations


class Migration(migrations.Migration):
    """Remove the legacy unique constraint on user.email."""

    dependencies = [
        ("accounts", "0015_add_withdrawal_account_model"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="user",
            name="accounts_user_email_ci_unique_non_empty",
        ),
    ]

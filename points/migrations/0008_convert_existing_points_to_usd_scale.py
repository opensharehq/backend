"""Convert live point liabilities from the RMB scale to the USD scale."""

from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

from points.point_conversion import apply_point_conversion, lock_conversion_tables


def convert_existing_points(apps, schema_editor):
    """Apply the conversion inside the migration transaction."""
    PointSource = apps.get_model("points", "PointSource")
    PointTransaction = apps.get_model("points", "PointTransaction")
    PendingPointGrant = apps.get_model("points", "PendingPointGrant")
    PointAllocation = apps.get_model("points", "PointAllocation")
    WithdrawalRequest = apps.get_model("points", "WithdrawalRequest")
    OutreachRecipient = apps.get_model("talent_reach", "OutreachRecipient")

    lock_conversion_tables(
        schema_editor.connection,
        [
            PointSource,
            PointTransaction,
            PendingPointGrant,
            PointAllocation,
            WithdrawalRequest,
            OutreachRecipient,
        ],
    )
    apply_point_conversion(
        PointSource=PointSource,
        PointTransaction=PointTransaction,
        PendingPointGrant=PendingPointGrant,
        PointAllocation=PointAllocation,
        WithdrawalRequest=WithdrawalRequest,
        OutreachRecipient=OutreachRecipient,
    )


def reverse_conversion(apps, schema_editor):
    """Reject reversal because rounding prevents exact reconstruction."""
    msg = "The RMB-to-USD point conversion is lossy; restore a database backup instead."
    raise IrreversibleError(msg)


class Migration(migrations.Migration):
    """Run the one-time point denomination conversion."""

    atomic = True

    dependencies = [
        ("points", "0007_add_refund_transaction_type"),
        ("talent_reach", "0004_outreachcampaign_source_owner_slug_and_more"),
    ]

    operations = [
        migrations.RunPython(convert_existing_points, reverse_conversion),
    ]

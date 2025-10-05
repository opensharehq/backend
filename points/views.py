"""Views for the points app."""

import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone


@login_required
def my_points(request):
    """
    Display user's points information.

    Shows:
    - Total points
    - Points by tag
    - Point sources
    - Transaction history

    """
    user = request.user

    # Get points by tag
    points_by_tag = user.get_points_by_tag()

    # Get active point sources (with remaining points)
    active_sources = user.point_sources.filter(remaining_points__gt=0).order_by(
        "-created_at"
    )

    # Get transaction history with pagination
    transactions = user.point_transactions.select_related().order_by("-created_at")
    paginator = Paginator(transactions, 20)  # 20 transactions per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Calculate points trend data for the last 30 days
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=29)  # 30 days including today

    # Generate date labels for all 30 days
    trend_labels = []
    for i in range(30):
        current_date = start_date + timedelta(days=i)
        trend_labels.append(current_date.strftime("%m/%d"))

    # Get all tags that the user has points from
    from points.models import Tag

    user_tags = (
        Tag.objects.filter(point_sources__user_profile=user).distinct().order_by("name")
    )

    # Calculate trend data for each tag
    trend_datasets = []
    for tag in user_tags:
        # Create a dict for daily changes for this tag
        daily_changes = {}

        # 1. Get EARN transactions (points granted with this tag)
        # These are tracked via PointSource created_at
        earn_sources = (
            user.point_sources.filter(tags=tag, created_at__date__gte=start_date)
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total_points=Sum("initial_points"))
            .order_by("date")
        )

        for item in earn_sources:
            daily_changes[item["date"]] = (
                daily_changes.get(item["date"], 0) + item["total_points"]
            )

        # 2. Get SPEND transactions (points consumed from sources with this tag)
        spend_transactions = (
            user.point_transactions.filter(
                created_at__date__gte=start_date,
                transaction_type="SPEND",
                consumed_sources__tags=tag,
            )
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total_points=Sum("points"))
            .order_by("date")
        )

        for item in spend_transactions:
            # points are negative for SPEND transactions
            daily_changes[item["date"]] = (
                daily_changes.get(item["date"], 0) + item["total_points"]
            )

        # Calculate cumulative points for this tag
        # Get current points for this tag (include all sources, even if used up)
        current_tag_points = sum(
            source.remaining_points for source in user.point_sources.filter(tags=tag)
        )

        # Calculate total change during the period
        total_change = sum(daily_changes.values())
        starting_points = current_tag_points - total_change

        # Generate trend data
        tag_data = []
        cumulative = starting_points
        for i in range(30):
            current_date = start_date + timedelta(days=i)
            daily_change = daily_changes.get(current_date, 0)
            cumulative += daily_change
            tag_data.append(cumulative)

        # Only add to datasets if there's meaningful data
        # (either current points or changes during period)
        if current_tag_points > 0 or total_change != 0:
            trend_datasets.append({"label": tag.name, "data": tag_data})

    context = {
        "total_points": user.total_points,
        "points_by_tag": points_by_tag,
        "active_sources": active_sources,
        "page_obj": page_obj,
        "trend_labels_json": json.dumps(trend_labels),
        "trend_datasets_json": json.dumps(trend_datasets),
    }

    return render(request, "points/my_points.html", context)

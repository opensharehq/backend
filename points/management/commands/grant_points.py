"""Management command for granting points to users."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from points.services import grant_points

User = get_user_model()


class Command(BaseCommand):
    """Grant points to a user."""

    help = "Grant points to a user by username or email"

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            "username",
            type=str,
            help="Username or email of the user to grant points to",
        )
        parser.add_argument(
            "points",
            type=int,
            help="Number of points to grant (must be positive)",
        )
        parser.add_argument(
            "--description",
            "-d",
            type=str,
            default="管理员发放",
            help="Description for the points grant (default: 管理员发放)",
        )
        parser.add_argument(
            "--tags",
            "-t",
            type=str,
            default="openshare",
            help="Comma-separated tags (name or slug) (default: openshare)",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        username = options["username"]
        points = options["points"]
        description = options["description"]
        tags_str = options["tags"]

        # Parse tags
        tag_names = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

        # Find user by username or email
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email=username)
            except User.DoesNotExist:
                msg = f"User not found: {username}"
                raise CommandError(msg) from None

        # Grant points
        try:
            grant_points(
                user_profile=user,
                points=points,
                description=description,
                tag_names=tag_names,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully granted {points} points to {user.username}"
                )
            )
            self.stdout.write(f"  Description: {description}")
            self.stdout.write(f"  Tags: {', '.join(tag_names)}")
            self.stdout.write(f"  User's total points: {user.total_points}")

        except ValueError as e:
            raise CommandError(str(e)) from e

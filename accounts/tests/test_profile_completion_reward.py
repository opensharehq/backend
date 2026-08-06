"""Tests for profile completion reward service."""

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Education, UserProfile, WorkExperience
from accounts.services.jwt_tokens import create_access_token
from accounts.services.profile_completion_reward import (
    calculate_reward_points,
    get_profile_completion_reward_info,
    grant_profile_completion_reward,
    has_claimed_reward,
    is_profile_complete,
)
from points.models import PointSource

User = get_user_model()


def _create_user_with_profile(username="testuser", **profile_kwargs):
    """Helper to create a user and attach a UserProfile."""
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongPass123!",
    )
    UserProfile.objects.create(user=user, **profile_kwargs)
    return user


def _add_work_experience(user):
    """Helper to add a work experience to the user's profile."""
    WorkExperience.objects.create(
        profile=user.profile,
        company_name="OpenShare",
        title="Engineer",
        start_date=date(2023, 1, 1),
    )


def _add_education(user):
    """Helper to add an education entry to the user's profile."""
    Education.objects.create(
        profile=user.profile,
        institution_name="Tsinghua University",
        field_of_study="Computer Science",
        start_date=date(2018, 9, 1),
    )


class IsProfileCompleteTests(TestCase):
    """Tests for is_profile_complete function."""

    def test_is_profile_complete_all_missing(self):
        """All fields empty and no work/education → incomplete with all missing."""
        user = _create_user_with_profile(username="all_missing")
        complete, missing = is_profile_complete(user)
        self.assertFalse(complete)
        self.assertEqual(
            missing, ["location", "birth_date", "work_experience", "education"]
        )

    def test_is_profile_complete_partial(self):
        """Location and birth_date set but no work/education → partial."""
        user = _create_user_with_profile(
            username="partial",
            location_country_id=":divisions/CN",
            birth_date=date(1990, 5, 15),
        )
        complete, missing = is_profile_complete(user)
        self.assertFalse(complete)
        self.assertEqual(missing, ["work_experience", "education"])

    def test_is_profile_complete_all_filled(self):
        """All fields filled including work and education → complete."""
        user = _create_user_with_profile(
            username="complete",
            location_country_id=":divisions/CN",
            birth_date=date(1990, 5, 15),
        )
        _add_work_experience(user)
        _add_education(user)
        complete, missing = is_profile_complete(user)
        self.assertTrue(complete)
        self.assertEqual(missing, [])

    def test_is_profile_complete_under_25_no_work(self):
        """User under 25 with education but no work → complete (work exempt)."""
        birth_date = date.today() - timedelta(days=23 * 365)
        user = _create_user_with_profile(
            username="young",
            location_country_id=":divisions/CN",
            birth_date=birth_date,
        )
        _add_education(user)
        complete, missing = is_profile_complete(user)
        self.assertTrue(complete)
        self.assertEqual(missing, [])

    def test_is_profile_complete_25_or_older_no_work(self):
        """User 26 years old with education but no work → incomplete."""
        birth_date = date.today() - timedelta(days=26 * 365)
        user = _create_user_with_profile(
            username="older",
            location_country_id=":divisions/CN",
            birth_date=birth_date,
        )
        _add_education(user)
        complete, missing = is_profile_complete(user)
        self.assertFalse(complete)
        self.assertEqual(missing, ["work_experience"])


class HasClaimedRewardTests(TestCase):
    """Tests for has_claimed_reward function."""

    def test_has_claimed_reward_false(self):
        """User who never claimed → returns False."""
        user = _create_user_with_profile(username="unclaimed")
        self.assertFalse(has_claimed_reward(user))

    def test_has_claimed_reward_true_via_flag(self):
        """User with profile_completion_rewarded=True → returns True."""
        user = _create_user_with_profile(
            username="claimed", profile_completion_rewarded=True
        )
        self.assertTrue(has_claimed_reward(user))


class CalculateRewardPointsTests(TestCase):
    """Tests for calculate_reward_points function."""

    @patch("accounts.services.profile_completion_reward._fetch_baseline_tiers")
    @patch("accounts.services.profile_completion_reward.query_user_yearly_openrank")
    @patch("accounts.services.profile_completion_reward._get_user_platform_ids")
    def test_calculate_reward_points(
        self, mock_platform_ids, mock_yearly_openrank, mock_baseline_tiers
    ):
        """Verify correct tier and points based on yearly openrank data."""
        user = _create_user_with_profile(username="contributor")

        mock_platform_ids.return_value = [("github", "12345")]
        mock_yearly_openrank.return_value = [
            {"year": 2022, "yearly_openrank": 5.0},
            {"year": 2023, "yearly_openrank": 25.0},
            {"year": 2024, "yearly_openrank": 10.0},
        ]
        # Thresholds: SSS>=100, SS>=50, S>=20, A>=10, B>=5, C>=2
        mock_baseline_tiers.return_value = {
            "2022": [100, 50, 20, 10, 5, 2],
            "2023": [100, 50, 20, 10, 5, 2],
            "2024": [100, 50, 20, 10, 5, 2],
        }

        result = calculate_reward_points(user)
        # Best year is 2023 with 25.0 → tier S (>=20) → 60 points
        self.assertEqual(result["points"], 60)
        self.assertEqual(result["highest_level"], "S")
        self.assertEqual(result["highest_level_year"], 2023)

    @patch("accounts.services.profile_completion_reward._fetch_baseline_tiers")
    @patch("accounts.services.profile_completion_reward.query_user_yearly_openrank")
    @patch("accounts.services.profile_completion_reward._get_user_platform_ids")
    def test_calculate_reward_points_with_trailing_zero_threshold(
        self, mock_platform_ids, mock_yearly_openrank, mock_baseline_tiers
    ):
        """CDN thresholds include a trailing 0 for D tier; must not raise IndexError."""
        user = _create_user_with_profile(username="low_contributor")

        mock_platform_ids.return_value = [("github", "67890")]
        mock_yearly_openrank.return_value = [
            {"year": 2023, "yearly_openrank": 1.0},
        ]
        # Real CDN format: 7 entries with a trailing 0 (D tier floor)
        mock_baseline_tiers.return_value = {
            "2023": [100, 50, 20, 10, 5, 2, 0],
        }

        result = calculate_reward_points(user)
        # 1.0 is below C threshold (2) → tier D → 5 points
        self.assertEqual(result["points"], 5)
        self.assertEqual(result["highest_level"], "D")
        self.assertEqual(result["highest_level_year"], 2023)


class GrantProfileCompletionRewardTests(TestCase):
    """Tests for grant_profile_completion_reward function."""

    @patch("accounts.services.profile_completion_reward.calculate_reward_points")
    def test_grant_profile_completion_reward_success(self, mock_calc):
        """Successful grant creates PointSource and sets rewarded flag."""
        user = _create_user_with_profile(
            username="grantee",
            location_country_id=":divisions/CN",
            birth_date=date(1990, 5, 15),
        )
        _add_work_experience(user)
        _add_education(user)
        mock_calc.return_value = {
            "points": 300,
            "highest_level": "SSS",
            "highest_level_year": 2024,
        }

        result = grant_profile_completion_reward(user)
        self.assertEqual(result, {"rewarded": True, "points": 300})

        # Verify PointSource was created
        reference_id = f"profile_completion_reward:{user.id}"
        self.assertTrue(
            PointSource.objects.filter(
                wallet=user.point_wallet, reference_id=reference_id
            ).exists()
        )

        # Verify profile flag was set
        user.profile.refresh_from_db()
        self.assertTrue(user.profile.profile_completion_rewarded)

    def test_grant_profile_completion_reward_duplicate(self):
        """Already-rewarded user gets None and no new PointSource."""
        user = _create_user_with_profile(
            username="duplicate",
            location_country_id=":divisions/CN",
            birth_date=date(1990, 5, 15),
            profile_completion_rewarded=True,
        )
        _add_work_experience(user)
        _add_education(user)

        initial_count = PointSource.objects.count()
        result = grant_profile_completion_reward(user)
        self.assertIsNone(result)
        self.assertEqual(PointSource.objects.count(), initial_count)

    def test_grant_profile_completion_reward_incomplete_profile(self):
        """Incomplete profile → returns None."""
        user = _create_user_with_profile(username="incomplete")

        result = grant_profile_completion_reward(user)
        self.assertIsNone(result)


class GetProfileCompletionRewardInfoTests(TestCase):
    """Tests for get_profile_completion_reward_info function."""

    @patch("accounts.services.profile_completion_reward.calculate_reward_points")
    def test_get_profile_completion_reward_info_eligible(self, mock_calc):
        """Incomplete profile with unclaimed reward shows eligible info."""
        user = _create_user_with_profile(
            username="eligible",
            location_country_id=":divisions/CN",
        )
        mock_calc.return_value = {
            "points": 100,
            "highest_level": "SS",
            "highest_level_year": 2023,
        }

        info = get_profile_completion_reward_info(user)
        self.assertFalse(info["eligible"])
        self.assertEqual(info["reward_points"], 100)
        self.assertIn("birth_date", info["missing_fields"])
        self.assertEqual(info["highest_level"], "SS")
        self.assertEqual(info["highest_level_year"], 2023)

    def test_get_profile_completion_reward_info_already_claimed(self):
        """Already claimed user → not eligible, no missing fields."""
        user = _create_user_with_profile(
            username="already_claimed", profile_completion_rewarded=True
        )

        info = get_profile_completion_reward_info(user)
        self.assertFalse(info["eligible"])
        self.assertEqual(info["reward_points"], 0)
        self.assertEqual(info["missing_fields"], [])


class ProfileRewardApiTests(TestCase):
    """Tests for the profile completion reward API endpoint."""

    def setUp(self):
        """Create authenticated user with profile for API tests."""
        self.user = _create_user_with_profile(
            username="api_user",
            location_country_id=":divisions/CN",
            birth_date=date(1990, 5, 15),
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }

    @patch("accounts.services.profile_completion_reward.calculate_reward_points")
    def test_api_profile_completion_reward_endpoint(self, mock_calc):
        """GET /api/v1/me/profile-completion-reward returns reward info."""
        mock_calc.return_value = {
            "points": 40,
            "highest_level": "A",
            "highest_level_year": 2024,
        }

        response = self.client.get(
            "/api/v1/me/profile-completion-reward", **self.headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("eligible", data)
        self.assertEqual(data["reward_points"], 40)
        self.assertIn("missing_fields", data)
        self.assertEqual(data["highest_level"], "A")
        self.assertEqual(data["highest_level_year"], 2024)

    def test_api_profile_completion_reward_without_profile(self):
        """User without a UserProfile gets the default all-missing payload."""
        no_profile_user = User.objects.create_user(
            username="no_profile_user",
            email="no_profile_user@example.com",
            password="StrongPass123!",
        )
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(no_profile_user)}"
        }

        response = self.client.get("/api/v1/me/profile-completion-reward", **headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "eligible": False,
                "reward_points": 0,
                "missing_fields": [
                    "location",
                    "birth_date",
                    "work_experience",
                    "education",
                ],
                "highest_level": None,
                "highest_level_year": None,
            },
        )

    def test_api_profile_no_longer_includes_reward_info(self):
        """GET /api/v1/me/profile no longer returns profile_completion_reward."""
        response = self.client.get("/api/v1/me/profile", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("profile_completion_reward", response.json())

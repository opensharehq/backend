"""Platform selection contracts from the allocation API through ClickHouse."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from accounts.models import User
from accounts.services.jwt_tokens import create_access_token
from chdb.services import query_contributions_with_operators
from points.models import PointAllocation, PointType
from points.services import grant_points


class AllocationPlatformTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="platform-operator")
        grant_points(
            owner=self.operator,
            amount=1000,
            point_type=PointType.GIFT,
            reason="Platform filter test fixture",
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.operator)}"
        }
        self.payload = {
            "source_selector": {"owner_type": "user", "point_type": "gift"},
            "project_scope": {"tags": ["repo:test", "repo:other"], "operators": ["OR"]},
            "start_month": "2024-01-01",
            "end_month": "2024-02-01",
        }
        providers = patch(
            "points.api_v1.configured_providers",
            return_value=(
                ("github", {"name": "GitHub"}),
                ("gitee", {"name": "Gitee"}),
                ("atomgit", {"name": "AtomGit"}),
                ("google-oauth2", {"name": "Google"}),
            ),
        )
        providers.start()
        self.addCleanup(providers.stop)

    def post(self, endpoint="/preview"):
        return self.client.post(
            f"/api/v1/points/allocations{endpoint}",
            data=self.payload,
            content_type="application/json",
            **self.headers,
        )

    def set_execute_payload(self):
        self.payload.update(
            total_amount=100,
            allocations=[
                {
                    "actor_id": "123",
                    "actor_login": "contributor",
                    "platform": "github",
                    "is_registered": False,
                    "contribution_score": 1,
                    "amount": 100,
                }
            ],
        )

    def test_pools_offer_only_configured_code_hosting_platforms(self):
        response = self.client.get("/api/v1/points/pools", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["allocation_platforms"], ["GitHub", "Gitee", "AtomGit"]
        )

    @patch("chdb.services.ClickHouseDB.query")
    def test_platform_filter_reaches_sql_before_ranking_and_limit(self, query):
        query.return_value = MagicMock(
            result_rows=[("GitHub", 123, "contributor", 1.0, [])]
        )
        for platforms in (["GitHub"], ["GitHub", "Gitee"], None):
            with self.subTest(platforms=platforms):
                self.payload["project_scope"]["platforms"] = platforms
                response = self.post()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["total_recipients"], 1)
                sql = query.call_args.args[0]
                parameters = query.call_args.kwargs["parameters"]
                if platforms is None:
                    self.assertNotIn("platform IN {platforms", sql)
                    self.assertNotIn("platforms", parameters)
                else:
                    clause = "AND platform IN {platforms:Array(String)}"
                    self.assertIn(clause, sql)
                    self.assertEqual(parameters["platforms"], platforms)
                    self.assertLess(sql.index(clause), sql.index("GROUP BY"))
                    self.assertLess(sql.index(clause), sql.index("LIMIT"))
                self.assertIn(" OR ", sql)
                self.assertEqual(parameters["limit"], 300_000)

    @patch("chdb.services.ClickHouseDB.query")
    def test_omitted_platforms_preserve_unrestricted_queries(self, query):
        query.return_value = MagicMock(result_rows=[])
        self.assertEqual(self.post().status_code, 200)
        self.assertNotIn("platform IN {platforms", query.call_args.args[0])
        self.assertNotIn("platforms", query.call_args.kwargs["parameters"])

    @patch("chdb.services.ClickHouseDB.query")
    def test_invalid_platforms_rejected_for_preview_and_execute(self, query):
        self.set_execute_payload()
        for platforms in (
            [],
            ["Google"],
            ["GitLab"],
            ["GitHub", "unknown"],
            ["GitHub') OR 1=1 --"],
        ):
            self.payload["project_scope"]["platforms"] = platforms
            for endpoint in ("/preview", ""):
                with self.subTest(platforms=platforms, endpoint=endpoint):
                    response = self.post(endpoint)
                    self.assertEqual(response.status_code, 422)
                    self.assertIn("project_scope.platforms", response.json()["detail"])
        query.assert_not_called()
        self.assertFalse(PointAllocation.objects.exists())

    def test_execute_persists_selected_platforms(self):
        self.set_execute_payload()
        self.payload["project_scope"]["platforms"] = ["GitHub", "Gitee"]
        response = self.post("")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            PointAllocation.objects.get().project_scope["platforms"],
            ["GitHub", "Gitee"],
        )

    def test_execute_rejects_recipients_outside_selected_platforms(self):
        self.set_execute_payload()
        self.payload["project_scope"]["platforms"] = ["Gitee"]
        response = self.post("")
        self.assertEqual(response.status_code, 422)
        self.assertIn("allocations.platform", response.json()["detail"])
        self.assertFalse(PointAllocation.objects.exists())

    @patch("chdb.services.ClickHouseDB.query")
    def test_empty_platform_list_never_becomes_unrestricted_query(self, query):
        self.assertEqual(
            query_contributions_with_operators(
                ["repo:test"], [], 202401, 202402, platforms=[]
            ),
            [],
        )
        query.assert_not_called()

"""Tests for chdb services."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from chdb import services


class CollectUserIdsTests(TestCase):
    """Tests for _collect_user_ids helper."""

    def test_collect_user_ids_github_only(self):
        """Collect only GitHub user IDs."""
        label_entities = {
            "label-1": {
                "users": {"github": [1, 2], "gitee": [3]},
            },
            "label-2": {
                "users": {"GitHub": [9], "gitlab": [10]},
            },
        }

        user_ids = services._collect_user_ids(label_entities)

        self.assertCountEqual(user_ids, [1, 2, 9])

    def test_collect_user_ids_empty(self):
        """Return empty list when no users exist."""
        label_entities = {
            "label-1": {
                "users": {},
            }
        }

        user_ids = services._collect_user_ids(label_entities)

        self.assertEqual(user_ids, [])


class QueryContributionsTests(TestCase):
    """Tests for query_contributions function."""

    @patch("chdb.services.ClickHouseDB.query")
    def test_query_contributions_success(self, mock_query):
        """Test successful contribution query."""
        # Mock ClickHouse query result
        mock_result = MagicMock()
        mock_result.result_rows = [
            (111111, "user1", 100.5, [("repo1", 10.0, 202501)]),
            (222222, "user2", 50.3, [("repo2", 5.0, 202501)]),
            (333333, "user3", 25.0, []),
        ]
        mock_query.return_value = mock_result

        # Call function
        contributions = services.query_contributions(
            label_ids=[":companies/test/project"],
            start_month=202501,
            end_month=202512,
        )

        # Verify results
        self.assertEqual(len(contributions), 3)

        # Check first contribution
        self.assertEqual(contributions[0]["platform"], "GitHub")
        self.assertEqual(contributions[0]["actor_id"], "111111")
        self.assertEqual(contributions[0]["actor_login"], "user1")
        self.assertAlmostEqual(contributions[0]["contribution_score"], 100.5, places=2)
        self.assertIn("details", contributions[0])

        call_args = mock_query.call_args
        self.assertEqual(call_args[0][0], services.CONTRIBUTIONS_SQL)
        self.assertEqual(call_args[1]["parameters"]["label_ids"], [":companies/test/project"])
        self.assertEqual(call_args[1]["parameters"]["year"], 2025)

    @patch("chdb.services.ClickHouseDB.query")
    def test_query_contributions_cross_year_uses_end_year(self, mock_query):
        """Test contribution query uses end year when range crosses years."""
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        services.query_contributions(
            label_ids=[":companies/test/project"],
            start_month=202412,
            end_month=202501,
        )

        call_args = mock_query.call_args
        self.assertEqual(call_args[0][0], services.CONTRIBUTIONS_SQL)
        self.assertEqual(call_args[1]["parameters"]["year"], 2025)

    def test_query_contributions_empty_labels(self):
        """Test query with empty label list."""
        contributions = services.query_contributions(
            label_ids=[], start_month=202405, end_month=202406
        )

        self.assertEqual(contributions, [])

    @patch("chdb.services.ClickHouseDB.query")
    def test_query_contributions_with_exception(self, mock_query):
        """Test query handling exceptions."""
        mock_query.side_effect = Exception("ClickHouse error")

        contributions = services.query_contributions(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )

        self.assertEqual(contributions, [])


class SearchTagsTests(TestCase):
    """Tests for search_tags helper."""

    @patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_basic(self, mock_query):
        """Test basic search behavior."""
        mock_result = MagicMock()
        mock_result.result_rows = [
            [
                "github-linux",
                "repo",
                "torvalds/linux",
                "Linux Kernel CN",
                ["github", "gitee"],
                '{"openrank": 1234.56}',
            ],
            [
                "apache",
                "org",
                "apache",
                "",
                ["github"],
                None,
            ],
        ]
        mock_query.return_value = mock_result

        tags = services.search_tags("vscode")

        self.assertEqual(len(tags), 2)
        self.assertEqual(tags[0]["id"], "github-linux")
        self.assertEqual(tags[0]["type"], "repo")
        self.assertEqual(tags[0]["platform"], "github/gitee")
        self.assertEqual(tags[0]["name"], "Linux Kernel CN")
        self.assertEqual(tags[0]["openrank"], 1234.56)
        self.assertEqual(tags[0]["name_display"], "Linux Kernel CN (Github/Gitee)")
        self.assertEqual(tags[0]["slug"], "github-linux")

        self.assertEqual(tags[1]["id"], "apache")
        self.assertEqual(tags[1]["platform"], "github")
        self.assertEqual(tags[1]["name_display"], "apache (Github)")
        self.assertIsNone(tags[1]["openrank"])

        mock_query.assert_called_once()
        call_args = mock_query.call_args
        self.assertIn("opensource.labels", call_args[0][0])
        self.assertIn("name ILIKE", call_args[0][0])
        self.assertIn("name_zh ILIKE", call_args[0][0])
        self.assertIn("id ILIKE", call_args[0][0])
        self.assertIn("LIMIT", call_args[0][0])
        self.assertEqual(call_args[1]["parameters"]["keyword"], "%vscode%")
        self.assertEqual(call_args[1]["parameters"]["limit"], 5)

    @patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_empty_keyword(self, mock_query):
        """Empty keywords should return no results and skip query."""
        tags = services.search_tags("")
        self.assertEqual(tags, [])
        mock_query.assert_not_called()

        tags = services.search_tags("   ")
        self.assertEqual(tags, [])
        mock_query.assert_not_called()

    @patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_no_results(self, mock_query):
        """No results should return an empty list."""
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        tags = services.search_tags("nonexistent-project-xyz")

        self.assertEqual(tags, [])
        mock_query.assert_called_once()

    @patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_custom_limit(self, mock_query):
        """Custom limit should be respected."""
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        services.search_tags("test", limit=10)

        call_args = mock_query.call_args
        self.assertEqual(call_args[1]["parameters"]["limit"], 10)

    @patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_query_exception(self, mock_query):
        """Query exceptions should be swallowed and return empty list."""
        mock_query.side_effect = Exception("Database connection error")

        tags = services.search_tags("vscode")

        self.assertEqual(tags, [])
        mock_query.assert_called_once()

    @patch("chdb.services.ClickHouseDB.query")
    def test_search_tags_keyword_trimmed(self, mock_query):
        """Keyword should be trimmed before query."""
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        services.search_tags("  vscode  ")

        call_args = mock_query.call_args
        self.assertEqual(call_args[1]["parameters"]["keyword"], "%vscode%")


class GetLabelUsersTests(TestCase):
    """Tests for get_label_users helper."""

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_basic(self, mock_query):
        """Test basic user info query."""
        mock_result = MagicMock()
        mock_result.result_rows = [
            [
                "github-microsoft-vscode",
                ["github", "gitee"],
                [
                    [123, 456],
                    [789],
                ],
            ],
        ]
        mock_query.return_value = mock_result

        label_info = services.get_label_users(["github-microsoft-vscode"])

        self.assertEqual(len(label_info), 1)
        self.assertIn("github-microsoft-vscode", label_info)

        info = label_info["github-microsoft-vscode"]
        self.assertEqual(info["platforms"], ["github", "gitee"])
        self.assertEqual(info["users"]["github"], [123, 456])
        self.assertEqual(info["users"]["gitee"], [789])

        mock_query.assert_called_once()
        call_args = mock_query.call_args
        self.assertIn("opensource.labels", call_args[0][0])
        self.assertIn("platforms.name", call_args[0][0])
        self.assertIn("platforms.users", call_args[0][0])
        self.assertEqual(
            call_args[1]["parameters"]["label_ids"], ["github-microsoft-vscode"]
        )

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_empty_list(self, mock_query):
        """Empty label list should return empty dict."""
        label_info = services.get_label_users([])

        self.assertEqual(label_info, {})
        mock_query.assert_not_called()

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_normalizes_ids(self, mock_query):
        """Label IDs should be normalized before query."""
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        label_info = services.get_label_users([16060815, " 37247796 ", None, ""])

        self.assertEqual(label_info, {})
        mock_query.assert_called_once()
        call_args = mock_query.call_args
        self.assertEqual(
            call_args[1]["parameters"]["label_ids"], ["16060815", "37247796"]
        )

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_no_results(self, mock_query):
        """No results should return empty dict."""
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        label_info = services.get_label_users(["nonexistent-label"])

        self.assertEqual(label_info, {})
        mock_query.assert_called_once()

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_multiple_labels(self, mock_query):
        """Multiple labels should map users per label."""
        mock_result = MagicMock()
        mock_result.result_rows = [
            [
                "github-microsoft-vscode",
                ["github"],
                [[123, 456]],
            ],
            [
                "github-facebook-react",
                ["github", "gitlab"],
                [[789], [321, 654]],
            ],
        ]
        mock_query.return_value = mock_result

        label_info = services.get_label_users(
            ["github-microsoft-vscode", "github-facebook-react"]
        )

        self.assertEqual(len(label_info), 2)
        self.assertIn("github-microsoft-vscode", label_info)
        self.assertIn("github-facebook-react", label_info)

        self.assertEqual(label_info["github-microsoft-vscode"]["platforms"], ["github"])
        self.assertEqual(
            label_info["github-microsoft-vscode"]["users"]["github"], [123, 456]
        )

        self.assertEqual(
            label_info["github-facebook-react"]["platforms"], ["github", "gitlab"]
        )
        self.assertEqual(label_info["github-facebook-react"]["users"]["github"], [789])
        self.assertEqual(
            label_info["github-facebook-react"]["users"]["gitlab"], [321, 654]
        )

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_query_exception(self, mock_query):
        """Query errors should return empty dict."""
        mock_query.side_effect = Exception("Database connection error")

        label_info = services.get_label_users(["github-microsoft-vscode"])

        self.assertEqual(label_info, {})
        mock_query.assert_called_once()

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_users_mismatched_array_lengths(self, mock_query):
        """Handle mismatched platform/user arrays."""
        mock_result = MagicMock()
        mock_result.result_rows = [
            [
                "test-label",
                ["github", "gitlab"],
                [[123]],
            ],
        ]
        mock_query.return_value = mock_result

        label_info = services.get_label_users(["test-label"])

        self.assertEqual(len(label_info), 1)
        info = label_info["test-label"]
        self.assertEqual(info["platforms"], ["github", "gitlab"])
        self.assertEqual(info["users"]["github"], [123])
        self.assertNotIn("gitlab", info["users"])


class GetLabelEntitiesTests(TestCase):
    """Tests for get_label_entities helper."""

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_entities_basic(self, mock_query):
        """Test basic entity query."""
        mock_result = MagicMock()
        mock_result.result_rows = [
            [
                "label-1",
                "repo",
                "org/repo",
                "Repo CN",
                ["child-1"],
                ["github", "gitee"],
                [[1], [2]],
                [[11, 12], [21]],
                [[101], [201, 202]],
            ],
        ]
        mock_query.return_value = mock_result

        label_info = services.get_label_entities(["label-1"])

        self.assertIn("label-1", label_info)
        info = label_info["label-1"]
        self.assertEqual(info["id"], "label-1")
        self.assertEqual(info["type"], "repo")
        self.assertEqual(info["name"], "org/repo")
        self.assertEqual(info["name_zh"], "Repo CN")
        self.assertEqual(info["children"], ["child-1"])
        self.assertEqual(info["platforms"], ["github", "gitee"])
        self.assertEqual(info["orgs"]["github"], [1])
        self.assertEqual(info["orgs"]["gitee"], [2])
        self.assertEqual(info["repos"]["github"], [11, 12])
        self.assertEqual(info["repos"]["gitee"], [21])
        self.assertEqual(info["users"]["github"], [101])
        self.assertEqual(info["users"]["gitee"], [201, 202])

        mock_query.assert_called_once()

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_entities_empty_list(self, mock_query):
        """Empty label list should return empty dict."""
        label_info = services.get_label_entities([])

        self.assertEqual(label_info, {})
        mock_query.assert_not_called()

    @patch("chdb.services.ClickHouseDB.query")
    def test_get_label_entities_normalizes_ids(self, mock_query):
        """Label IDs should be normalized before query."""
        mock_result = MagicMock()
        mock_result.result_rows = []
        mock_query.return_value = mock_result

        label_info = services.get_label_entities([123, " 456 ", None, ""])

        self.assertEqual(label_info, {})
        mock_query.assert_called_once()
        call_args = mock_query.call_args
        self.assertEqual(call_args[1]["parameters"]["label_ids"], ["123", "456"])

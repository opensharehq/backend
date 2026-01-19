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
    @patch("chdb.services.get_label_entities")
    def test_query_contributions_success(self, mock_get_entities, mock_query):
        """Test successful contribution query."""
        # Mock label entities
        mock_get_entities.return_value = {
            ":companies/test/project": {
                "id": ":companies/test/project",
                "type": "Project",
                "name": "Test Project",
                "platforms": ["GitHub"],
                "repos": {"github": [123, 456]},
            }
        }

        # Mock ClickHouse query result
        mock_result = MagicMock()
        mock_result.result_rows = [
            ("GitHub", 111111, "user1", 100.5),
            ("GitHub", 222222, "user2", 50.3),
            ("GitHub", 333333, "user3", 25.0),
        ]
        mock_query.return_value = mock_result

        # Call function
        contributions = services.query_contributions(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )

        # Verify results
        self.assertEqual(len(contributions), 3)

        # Check first contribution
        self.assertEqual(contributions[0]["platform"], "GitHub")
        self.assertEqual(contributions[0]["actor_id"], "111111")
        self.assertEqual(contributions[0]["actor_login"], "user1")
        self.assertAlmostEqual(contributions[0]["contribution_score"], 100.5, places=2)

    @patch("chdb.services.ClickHouseDB.query")
    @patch("chdb.services.get_label_entities")
    def test_query_contributions_with_user_filter(self, mock_get_entities, mock_query):
        """Test contribution query with user filtering."""
        mock_get_entities.return_value = {
            ":companies/test/project": {
                "id": ":companies/test/project",
                "type": "Project",
                "name": "Test Project",
                "platforms": ["GitHub"],
                "repos": {"github": [123]},
                "users": {"GitHub": [111, 222]},
            }
        }

        mock_result = MagicMock()
        mock_result.result_rows = [
            ("GitHub", 111, "user1", 20.0),
        ]
        mock_query.return_value = mock_result

        contributions = services.query_contributions(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )

        call_args = mock_query.call_args
        self.assertEqual(call_args[0][0], services.CONTRIBUTIONS_WITH_USERS_SQL)
        self.assertEqual(call_args[1]["parameters"]["repo_ids"], [123])
        self.assertEqual(call_args[1]["parameters"]["user_ids"], [111, 222])
        self.assertEqual(len(contributions), 1)

    @patch("chdb.services.ClickHouseDB.query")
    @patch("chdb.services.get_label_entities")
    def test_query_contributions_without_user_filter(
        self, mock_get_entities, mock_query
    ):
        """Test contribution query without user filtering."""
        mock_get_entities.return_value = {
            ":companies/test/project": {
                "id": ":companies/test/project",
                "type": "Project",
                "name": "Test Project",
                "platforms": ["GitHub"],
                "repos": {"github": [123]},
                "users": {"github": []},
            }
        }

        mock_result = MagicMock()
        mock_result.result_rows = [
            ("GitHub", 111, "user1", 10.0),
        ]
        mock_query.return_value = mock_result

        contributions = services.query_contributions(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )

        call_args = mock_query.call_args
        self.assertEqual(call_args[0][0], services.CONTRIBUTIONS_SQL)
        self.assertEqual(call_args[1]["parameters"]["repo_ids"], [123])
        self.assertEqual(len(contributions), 1)

    @patch("chdb.services.get_label_entities")
    def test_query_contributions_empty_labels(self, mock_get_entities):
        """Test query with empty label list."""
        contributions = services.query_contributions(
            label_ids=[], start_month=202405, end_month=202406
        )

        self.assertEqual(contributions, [])
        mock_get_entities.assert_not_called()

    @patch("chdb.services.get_label_entities")
    def test_query_contributions_no_repos(self, mock_get_entities):
        """Test query when labels have no repos."""
        mock_get_entities.return_value = {
            ":companies/test/project": {
                "id": ":companies/test/project",
                "type": "Project",
                "name": "Test Project",
                "platforms": ["GitHub"],
                "repos": {},  # No repos
            }
        }

        contributions = services.query_contributions(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )

        self.assertEqual(contributions, [])

    @patch("chdb.services.ClickHouseDB.query")
    @patch("chdb.services.get_label_entities")
    def test_query_contributions_with_exception(self, mock_get_entities, mock_query):
        """Test query handling exceptions."""
        mock_get_entities.return_value = {
            ":companies/test/project": {
                "repos": {"github": [123]},
            }
        }
        mock_query.side_effect = Exception("ClickHouse error")

        contributions = services.query_contributions(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )

        self.assertEqual(contributions, [])

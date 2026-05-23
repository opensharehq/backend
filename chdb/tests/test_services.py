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
            ("GitHub", 111111, "user1", 100.5, [("repo1", 10.0, 202501)]),
            ("GitHub", 222222, "user2", 50.3, [("repo2", 5.0, 202501)]),
            ("GitHub", 333333, "user3", 25.0, []),
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
        self.assertEqual(
            call_args[1]["parameters"]["label_ids"], [":companies/test/project"]
        )
        self.assertEqual(call_args[1]["parameters"]["start_month"], 202501)
        self.assertEqual(call_args[1]["parameters"]["end_month"], 202512)

    @patch("chdb.services.ClickHouseDB.query")
    def test_query_contributions_cross_year_uses_month_range(self, mock_query):
        """Test contribution query uses month range when range crosses years."""
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
        self.assertEqual(call_args[1]["parameters"]["start_month"], 202412)
        self.assertEqual(call_args[1]["parameters"]["end_month"], 202501)

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

        with self.assertLogs("chdb.services", level="ERROR") as cm:
            contributions = services.query_contributions(
                label_ids=[":companies/test/project"],
                start_month=202405,
                end_month=202406,
            )

        self.assertEqual(contributions, [])
        self.assertEqual(len(cm.output), 1)
        self.assertIn("查询贡献度数据失败", cm.output[0])


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

        with self.assertLogs("chdb.services", level="ERROR") as cm:
            tags = services.search_tags("vscode")

        self.assertEqual(tags, [])
        mock_query.assert_called_once()
        self.assertEqual(len(cm.output), 1)
        self.assertIn("搜索标签失败", cm.output[0])

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

        with self.assertLogs("chdb.services", level="ERROR") as cm:
            label_info = services.get_label_users(["github-microsoft-vscode"])

        self.assertEqual(label_info, {})
        mock_query.assert_called_once()
        self.assertEqual(len(cm.output), 1)
        self.assertIn("查询标签用户信息失败", cm.output[0])

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


class HelperFunctionsTests(TestCase):
    """Tests for helper utilities in chdb.services."""

    def test_get_result_rows_prefers_data_when_only_data_present(self):
        class DummyResult:
            def __init__(self):
                self.data = [[1, 2, 3]]

        self.assertEqual(services._get_result_rows(DummyResult()), [[1, 2, 3]])

    def test_get_result_rows_handles_none(self):
        self.assertEqual(services._get_result_rows(None), [])

    def test_get_result_rows_returns_empty_when_no_supported_attributes_exist(self):
        """Unknown result objects should gracefully return no rows."""

        class DummyResult:
            pass

        self.assertEqual(services._get_result_rows(DummyResult()), [])

    def test_format_platform_display_defaults_to_unknown(self):
        self.assertEqual(services._format_platform_display([]), ("unknown", "Unknown"))

    def test_prepare_label_ids_logs_when_list_empty(self):
        with self.assertLogs("chdb.services", level="WARNING") as cm:
            self.assertEqual(services._prepare_label_ids([]), [])
        self.assertIn("空标签列表查询被拒绝", cm.output[0])

    def test_prepare_label_ids_logs_when_normalized_empty(self):
        with self.assertLogs("chdb.services", level="WARNING") as cm:
            self.assertEqual(services._prepare_label_ids([None, "   "]), [])
        self.assertIn("标签列表去空后为空", cm.output[0])

    def test_collect_repo_ids_only_github(self):
        label_entities = {
            "label-1": {"repos": {"github": [101], "gitlab": [202]}},
            "label-2": {"repos": {"github": [303]}},
        }

        repo_ids = services._collect_repo_ids(label_entities)

        self.assertCountEqual(repo_ids, [101, 303])

    def test_collect_user_ids_only_github(self):
        label_entities = {
            "label-1": {"users": {"github": [1], "gitee": [2]}},
            "label-2": {"users": {"github": [3]}},
        }

        user_ids = services._collect_user_ids(label_entities)

        self.assertCountEqual(user_ids, [1, 3])

    def test_parse_contribution_rows_handles_multiple_formats(self):
        rows = [
            ["GitHub", 123, "login", 99.5, [("repo", 1.0, 202501)]],
            ["GitHub", 456, "other", 25.0, [("repo2", 0.5, 202502)]],
        ]

        parsed = services._parse_contribution_rows(rows)

        self.assertEqual(parsed[0]["platform"], "GitHub")
        self.assertEqual(parsed[0]["actor_id"], "123")
        self.assertIn("details", parsed[0])
        self.assertEqual(parsed[1]["actor_id"], "456")
        self.assertEqual(parsed[1]["actor_login"], "other")

    def test_parse_contribution_rows_defaults_blank_platform_to_github(self):
        """Blank platform values should use GitHub and preserve details."""
        rows = [
            [None, 12345, "default-github-user", 18.2, [("repo-x", 18.2, 202501)]],
        ]

        parsed = services._parse_contribution_rows(rows)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["platform"], "GitHub")
        self.assertEqual(parsed[0]["actor_id"], "12345")
        self.assertEqual(parsed[0]["actor_login"], "default-github-user")
        self.assertEqual(parsed[0]["contribution_score"], 18.2)
        self.assertEqual(parsed[0]["details"], [("repo-x", 18.2, 202501)])

    def test_parse_contribution_rows_five_column_platform_row(self):
        """5-column rows should honor explicit platform and include details."""
        rows = [
            ["GitLab", "gl-77", "gitlab-user", 31.4, [("repo-y", 31.4, 202502)]],
        ]

        parsed = services._parse_contribution_rows(rows)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["platform"], "GitLab")
        self.assertEqual(parsed[0]["actor_id"], "gl-77")
        self.assertEqual(parsed[0]["actor_login"], "gitlab-user")
        self.assertEqual(parsed[0]["contribution_score"], 31.4)
        self.assertEqual(parsed[0]["details"], [("repo-y", 31.4, 202502)])

    def test_parse_contribution_rows_omits_details_when_not_present(self):
        """Rows with null details should not include a details key."""
        rows = [
            ["GitHub", 888, "no-details-user", 12.0, None],
            ["Gitee", 999, "gitee-no-details", 5.5, None],
        ]

        parsed = services._parse_contribution_rows(rows)

        self.assertEqual(parsed[0]["platform"], "GitHub")
        self.assertEqual(parsed[0]["actor_id"], "888")
        self.assertNotIn("details", parsed[0])

        self.assertEqual(parsed[1]["platform"], "Gitee")
        self.assertEqual(parsed[1]["actor_id"], "999")
        self.assertNotIn("details", parsed[1])

    def test_parse_contribution_rows_normalizes_actor_id_to_string(self):
        """actor_id should always be normalized to string across row formats."""
        rows = [
            ["GitHub", 1001, "platform-row", 1.0, []],
            ["GitHub", 2002, "default-row", 2.0, []],
        ]

        parsed = services._parse_contribution_rows(rows)

        self.assertEqual(parsed[0]["actor_id"], "1001")
        self.assertEqual(parsed[1]["actor_id"], "2002")

    def test_build_users_and_map_platform_values_align_lengths(self):
        names = ["github", "gitlab"]
        users = [[1, 2], [3]]
        values = [["a"], None]

        built_users = services._build_users_by_platform(names, users)
        mapped_values = services._map_platform_values(names, values)

        self.assertEqual(built_users["github"], [1, 2])
        self.assertEqual(built_users["gitlab"], [3])
        self.assertEqual(mapped_values["github"], ["a"])
        self.assertEqual(mapped_values["gitlab"], [])

    def test_format_search_tag_row_missing_fields(self):
        row = ["id", "repo", None, "", [], None]
        formatted = services._format_search_tag_row(row)

        self.assertEqual(formatted["platform"], "unknown")
        self.assertEqual(formatted["name"], "id")
        self.assertEqual(formatted["slug"], "id")

    @patch("chdb.services.ClickHouseDB.query")
    def test_search_name_info_formats_numeric_and_label_ids(self, mock_query):
        """search_name_info should normalize numeric ids while preserving label ids."""
        mock_result = MagicMock()
        mock_result.result_rows = [
            ("github", "123", "repo", "Repo", "Repository"),
            ("Project", ":companies/demo", "Demo", "演示", "Label"),
        ]
        mock_query.return_value = mock_result

        results = services.search_name_info("demo")

        self.assertEqual(results[0]["id"], 123)
        self.assertEqual(results[1]["id"], ":companies/demo")
        mock_query.assert_called_once_with(
            services.SEARCH_NAME_INFO_SQL,
            parameters={"keyword": "%demo%"},
        )

    def test_search_name_info_empty_keyword_returns_empty_list(self):
        """Blank search keywords should not query ClickHouse."""
        with patch("chdb.services.ClickHouseDB.query") as mock_query:
            results = services.search_name_info("  ")

        self.assertEqual(results, [])
        mock_query.assert_not_called()

    @patch("chdb.services.ClickHouseDB.query", side_effect=Exception("boom"))
    def test_search_name_info_query_error_returns_empty_list(self, _mock_query):
        """ClickHouse failures should be converted to an empty result list."""
        self.assertEqual(services.search_name_info("demo"), [])

    def test_parse_openrank_returns_none_for_bad_payloads(self):
        payload = {"openrank": "bad"}
        self.assertIsNone(services._parse_openrank_payload(payload))

    def test_parse_openrank_returns_none_when_key_is_missing(self):
        """Missing OpenRank keys should return None."""
        self.assertIsNone(services._parse_openrank_payload({"stars": 10}))

    def test_extract_openrank_handles_numbers_and_invalid_json(self):
        self.assertEqual(services._extract_openrank(123), 123.0)
        self.assertIsNone(services._extract_openrank("not json"))
        self.assertIsNone(services._extract_openrank("[1,2,3]"))

    def test_get_label_entities_exception_falls_back_to_empty(self):
        with patch("chdb.services.ClickHouseDB.query", side_effect=Exception("boom")):
            with self.assertLogs("chdb.services", level="ERROR") as cm:
                self.assertEqual(services.get_label_entities(["foo"]), {})
        self.assertIn("查询标签实体失败", cm.output[0])

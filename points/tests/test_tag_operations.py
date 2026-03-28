"""Tests for tag operations."""

from unittest.mock import patch

from django.test import TestCase

from points.tag_operations import TagOperation


class TagOperationTests(TestCase):
    """Tests for tag operations."""

    @patch("chdb.services.get_label_entities")
    def test_evaluate_single_repo_tag(self, mock_get_labels):
        """Test evaluating a single repo tag."""
        mock_get_labels.return_value = {
            "repo-label": {
                "id": "repo-label",
                "type": "repo",
                "name": "org/repo",
                "name_zh": "",
                "children": [],
                "platforms": ["github"],
                "orgs": {},
                "repos": {"github": [123]},
                "users": {},
            }
        }

        result = TagOperation.evaluate_project_tags(["repo-label"])
        self.assertEqual(result, {"repo:github:123"})

    @patch("chdb.services.get_label_entities")
    def test_evaluate_and_operation(self, mock_get_labels):
        """Test AND operation on tags."""
        mock_get_labels.return_value = {
            "label-a": {
                "id": "label-a",
                "type": "repo",
                "name": "org/a",
                "name_zh": "",
                "children": [],
                "platforms": ["github"],
                "orgs": {},
                "repos": {"github": [1, 2]},
                "users": {},
            },
            "label-b": {
                "id": "label-b",
                "type": "repo",
                "name": "org/b",
                "name_zh": "",
                "children": [],
                "platforms": ["github"],
                "orgs": {},
                "repos": {"github": [2]},
                "users": {},
            },
        }

        result = TagOperation.evaluate_project_tags(
            ["label-a", "label-b"], operation=TagOperation.AND
        )
        self.assertEqual(result, {"repo:github:2"})

    @patch("chdb.services.get_label_entities")
    def test_evaluate_or_operation(self, mock_get_labels):
        """Test OR operation on tags."""
        mock_get_labels.return_value = {
            "label-a": {
                "id": "label-a",
                "type": "repo",
                "name": "org/a",
                "name_zh": "",
                "children": [],
                "platforms": ["github"],
                "orgs": {},
                "repos": {"github": [1]},
                "users": {},
            },
            "label-b": {
                "id": "label-b",
                "type": "repo",
                "name": "org/b",
                "name_zh": "",
                "children": [],
                "platforms": ["github"],
                "orgs": {},
                "repos": {"github": [2]},
                "users": {},
            },
        }

        result = TagOperation.evaluate_project_tags(
            ["label-a", "label-b"], operation=TagOperation.OR
        )
        self.assertEqual(result, {"repo:github:1", "repo:github:2"})

    @patch("chdb.services.get_label_entities")
    def test_evaluate_not_operation(self, mock_get_labels):
        """Test NOT operation on tags."""
        mock_get_labels.return_value = {
            "label-a": {
                "id": "label-a",
                "type": "repo",
                "name": "org/a",
                "name_zh": "",
                "children": [],
                "platforms": ["github"],
                "orgs": {},
                "repos": {"github": [1, 2]},
                "users": {},
            },
            "label-b": {
                "id": "label-b",
                "type": "repo",
                "name": "org/b",
                "name_zh": "",
                "children": [],
                "platforms": ["github"],
                "orgs": {},
                "repos": {"github": [2]},
                "users": {},
            },
        }

        result = TagOperation.evaluate_project_tags(
            ["label-a", "label-b"], operation=TagOperation.NOT
        )
        self.assertEqual(result, {"repo:github:1"})

    def test_evaluate_empty_tags(self):
        """Test evaluating empty tag list."""
        result = TagOperation.evaluate_project_tags([])
        self.assertEqual(result, set())

    @patch("chdb.services.get_label_entities", return_value={})
    def test_evaluate_nonexistent_tag(self, _mock_get_labels):
        """Test evaluating non-existent tag."""
        result = TagOperation.evaluate_project_tags(["nonexistent-tag"])
        self.assertEqual(result, set())

    @patch("chdb.services.get_label_entities")
    def test_evaluate_user_tags(self, mock_get_labels):
        """Test evaluating user tags."""
        mock_get_labels.return_value = {
            "user-label": {
                "id": "user-label",
                "type": "user",
                "name": "core",
                "name_zh": "",
                "children": [],
                "platforms": ["github"],
                "orgs": {},
                "repos": {},
                "users": {"github": [101, 202]},
            }
        }

        result = TagOperation.evaluate_user_tags(["user-label"])
        self.assertEqual(result, {"101", "202"})

    @patch("chdb.services.get_label_entities")
    def test_evaluate_xor_operation(self, mock_get_labels):
        """Test XOR operation on project tags."""
        mock_get_labels.return_value = {
            "label-a": {"repos": {"github": [1, 2]}, "orgs": {}, "children": []},
            "label-b": {"repos": {"github": [2, 3]}, "orgs": {}, "children": []},
        }

        result = TagOperation.evaluate_project_tags(
            ["label-a", "label-b"], operation=TagOperation.XOR
        )

        self.assertEqual(result, {"repo:github:1", "repo:github:3"})

    @patch("chdb.services.get_label_entities")
    def test_projects_fall_back_to_orgs(self, mock_get_labels):
        """Test project resolution falls back to org identifiers."""
        mock_get_labels.return_value = {
            "org-label": {
                "repos": {},
                "orgs": {"gitee": [99]},
                "children": [],
                "name": "",
                "name_zh": "",
                "id": "org-label",
            }
        }

        result = TagOperation.evaluate_project_tags(["org-label"])

        self.assertEqual(result, {"org:gitee:99"})

    @patch("chdb.services.get_label_entities")
    def test_projects_fall_back_to_children(self, mock_get_labels):
        """Test project resolution falls back to child identifiers."""
        mock_get_labels.return_value = {
            "child-label": {
                "repos": {},
                "orgs": {},
                "children": ["child-1", "", None],
                "name": "",
                "name_zh": "",
                "id": "child-label",
            }
        }

        result = TagOperation.evaluate_project_tags(["child-label"])

        self.assertEqual(result, {"child-1"})

    @patch("chdb.services.get_label_entities")
    def test_projects_fall_back_to_name(self, mock_get_labels):
        """Test project resolution falls back to display names."""
        mock_get_labels.return_value = {
            "named-label": {
                "repos": {},
                "orgs": {},
                "children": [],
                "name": "",
                "name_zh": "中文标签",
                "id": "named-label",
            }
        }

        result = TagOperation.evaluate_project_tags(["named-label"])

        self.assertEqual(result, {"中文标签"})

    @patch("chdb.services.get_label_entities")
    def test_evaluate_project_tags_missing_label_uses_empty_set(self, mock_get_labels):
        """Test missing labels participate as empty sets in set operations."""
        mock_get_labels.return_value = {
            "label-a": {
                "repos": {"github": [1]},
                "orgs": {},
                "children": [],
                "name": "org/a",
                "name_zh": "",
                "id": "label-a",
            }
        }

        result = TagOperation.evaluate_project_tags(
            ["label-a", "missing"], operation=TagOperation.AND
        )

        self.assertEqual(result, set())

    def test_evaluate_project_tags_handles_truthy_empty_normalized_list(self):
        """Test project evaluation safely handles a truthy iterable with no values."""

        class TruthyEmptyList(list):
            def __bool__(self):
                return True

        with patch.object(
            TagOperation, "_normalize_tag_ids", return_value=TruthyEmptyList()
        ):
            result = TagOperation.evaluate_project_tags(["ignored"])

        self.assertEqual(result, set())

    def test_evaluate_user_tags_empty_tags(self):
        """Test evaluating empty user tags returns an empty set."""
        self.assertEqual(TagOperation.evaluate_user_tags([]), set())

    @patch("chdb.services.get_label_entities", return_value={})
    def test_evaluate_user_tags_missing_label_uses_empty_set(self, _mock_get_labels):
        """Test missing user labels contribute empty sets."""
        result = TagOperation.evaluate_user_tags(["missing"])

        self.assertEqual(result, set())

    @patch("chdb.services.get_label_entities")
    def test_evaluate_user_tags_xor_operation(self, mock_get_labels):
        """Test XOR operation on user tags."""
        mock_get_labels.return_value = {
            "label-a": {"users": {"github": [101, 202]}},
            "label-b": {"users": {"github": [202, 303]}},
        }

        result = TagOperation.evaluate_user_tags(
            ["label-a", "label-b"], operation=TagOperation.XOR
        )

        self.assertEqual(result, {"101", "303"})

    @patch("chdb.services.get_label_entities")
    def test_evaluate_user_tags_and_or_not_operations(self, mock_get_labels):
        """Test set operations beyond XOR for user tags."""
        mock_get_labels.return_value = {
            "label-a": {"users": {"github": [101, 202]}},
            "label-b": {"users": {"github": [202, 303]}},
        }

        and_result = TagOperation.evaluate_user_tags(
            ["label-a", "label-b"], operation=TagOperation.AND
        )
        or_result = TagOperation.evaluate_user_tags(
            ["label-a", "label-b"], operation=TagOperation.OR
        )
        not_result = TagOperation.evaluate_user_tags(
            ["label-a", "label-b"], operation=TagOperation.NOT
        )

        self.assertEqual(and_result, {"202"})
        self.assertEqual(or_result, {"101", "202", "303"})
        self.assertEqual(not_result, {"101"})

    def test_evaluate_user_tags_handles_truthy_empty_normalized_list(self):
        """Test user evaluation safely handles a truthy iterable with no values."""

        class TruthyEmptyList(list):
            def __bool__(self):
                return True

        with patch.object(
            TagOperation, "_normalize_tag_ids", return_value=TruthyEmptyList()
        ):
            result = TagOperation.evaluate_user_tags(["ignored"])

        self.assertEqual(result, set())

    @patch("chdb.services.get_label_entities", side_effect=Exception("boom"))
    def test_fetch_label_entities_returns_empty_on_exception(self, _mock_get_labels):
        """Test entity fetch failures are downgraded to an empty result."""
        self.assertEqual(TagOperation._fetch_label_entities(["tag"]), {})

    def test_normalize_tag_ids_ignores_none_and_blank_values(self):
        """Test tag normalization removes empty values and strips whitespace."""
        normalized = TagOperation._normalize_tag_ids([None, " ", " tag-a ", 123])

        self.assertEqual(normalized, ["tag-a", "123"])

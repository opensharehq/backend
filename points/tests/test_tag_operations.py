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

"""Tests for the IP region detection service and API endpoint."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from common.services import region as region_service


class GetClientIpTests(SimpleTestCase):
    """Verify client IP extraction precedence."""

    def setUp(self):
        """Create a request factory shared by tests."""
        self.factory = RequestFactory()

    def test_x_forwarded_for_first_hop_wins(self):
        """The first comma-separated entry of X-Forwarded-For is used."""
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1",
            REMOTE_ADDR="10.0.0.1",
        )

        self.assertEqual(region_service.get_client_ip(request), "203.0.113.5")

    def test_falls_back_to_remote_addr(self):
        """REMOTE_ADDR is returned when X-Forwarded-For is missing."""
        request = self.factory.get("/", REMOTE_ADDR="198.51.100.7")

        self.assertEqual(region_service.get_client_ip(request), "198.51.100.7")

    def test_returns_none_when_no_ip_present(self):
        """Both headers missing yields None."""
        request = self.factory.get("/")
        request.META.pop("REMOTE_ADDR", None)

        self.assertIsNone(region_service.get_client_ip(request))

    def test_blank_x_forwarded_for_falls_back(self):
        """An empty XFF entry should not mask the real REMOTE_ADDR."""
        request = self.factory.get(
            "/",
            HTTP_X_FORWARDED_FOR=" , 10.0.0.1",
            REMOTE_ADDR="198.51.100.7",
        )

        self.assertEqual(region_service.get_client_ip(request), "198.51.100.7")


class ParseRegionTests(SimpleTestCase):
    """Verify ip2region row parsing."""

    def test_parses_standard_row(self):
        """A standard row exposes the ISO code and province."""
        self.assertEqual(
            region_service._parse_region("中国|广东省|深圳市|电信|CN"),
            ("CN", "广东省"),
        )

    def test_returns_none_for_empty_input(self):
        """Empty rows yield None."""
        self.assertIsNone(region_service._parse_region(""))

    def test_returns_none_for_malformed_input(self):
        """Rows missing fields yield None."""
        self.assertIsNone(region_service._parse_region("中国|广东省|深圳市"))


class IsMainlandChinaIpTests(SimpleTestCase):
    """Verify the high-level mainland China classification."""

    def setUp(self):
        """Reset the searcher cache between tests."""
        region_service._reset_searcher_cache()

    def tearDown(self):
        """Drop any searcher cached during the test."""
        region_service._reset_searcher_cache()

    def test_returns_none_when_xdb_path_unset(self):
        """Without IP2REGION_XDB_PATH the lookup is unavailable."""
        with override_settings(IP2REGION_XDB_PATH=""):
            self.assertIsNone(region_service.is_mainland_china_ip("203.0.113.5"))

    def test_returns_none_when_xdb_file_missing(self):
        """A configured but absent file is treated as unavailable."""
        absent = str(Path(tempfile.gettempdir()) / "does-not-exist.xdb")
        with override_settings(IP2REGION_XDB_PATH=absent):
            self.assertIsNone(region_service.is_mainland_china_ip("203.0.113.5"))

    def test_returns_none_for_empty_ip(self):
        """An empty IP shortcut returns None without touching the searcher."""
        self.assertIsNone(region_service.is_mainland_china_ip(""))
        self.assertIsNone(region_service.is_mainland_china_ip(None))

    def _patched_searcher(self, region_value: str) -> MagicMock:
        """Return a patched searcher that yields ``region_value`` on search."""
        searcher = MagicMock()
        searcher.search.return_value = region_value
        return searcher

    def test_mainland_ip_returns_true(self):
        """Mainland provinces under the CN ISO code resolve to True."""
        searcher = self._patched_searcher("中国|广东省|深圳市|电信|CN")
        with (
            patch.object(region_service, "_resolve_xdb_path", return_value="/fake.xdb"),
            patch.object(region_service, "_load_searcher", return_value=searcher),
        ):
            self.assertTrue(region_service.is_mainland_china_ip("113.118.113.77"))

    def test_hong_kong_ip_returns_false(self):
        """HK addresses share the CN code but are excluded from the mainland."""
        searcher = self._patched_searcher("中国|香港|香港|电讯盈科|CN")
        with (
            patch.object(region_service, "_resolve_xdb_path", return_value="/fake.xdb"),
            patch.object(region_service, "_load_searcher", return_value=searcher),
        ):
            self.assertFalse(region_service.is_mainland_china_ip("103.10.0.1"))

    def test_overseas_ip_returns_false(self):
        """A non-CN ISO code is not mainland."""
        searcher = self._patched_searcher("United States|California|San Jose|Cogent|US")
        with (
            patch.object(region_service, "_resolve_xdb_path", return_value="/fake.xdb"),
            patch.object(region_service, "_load_searcher", return_value=searcher),
        ):
            self.assertFalse(region_service.is_mainland_china_ip("8.8.8.8"))

    def test_searcher_exception_returns_none(self):
        """Lookup errors fail closed instead of bubbling out."""
        searcher = MagicMock()
        searcher.search.side_effect = RuntimeError("boom")
        with (
            patch.object(region_service, "_resolve_xdb_path", return_value="/fake.xdb"),
            patch.object(region_service, "_load_searcher", return_value=searcher),
        ):
            self.assertIsNone(region_service.is_mainland_china_ip("1.2.3.4"))

    def test_empty_region_returns_none(self):
        """Empty region rows fail closed."""
        searcher = self._patched_searcher("")
        with (
            patch.object(region_service, "_resolve_xdb_path", return_value="/fake.xdb"),
            patch.object(region_service, "_load_searcher", return_value=searcher),
        ):
            self.assertIsNone(region_service.is_mainland_china_ip("1.2.3.4"))


class RegionEndpointTests(TestCase):
    """Integration test for ``GET /api/v1/common/region``."""

    URL = "/api/v1/common/region"

    def test_returns_null_when_unavailable(self):
        """The endpoint returns null when no xdb file is configured."""
        with override_settings(IP2REGION_XDB_PATH=""):
            response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"is_mainland_cn": None})

    def test_uses_x_forwarded_for_when_present(self):
        """The endpoint prefers the first XFF hop for the IP lookup."""
        with patch("common.api_v1.is_mainland_china_ip", return_value=True) as mocked:
            response = self.client.get(
                self.URL, HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"is_mainland_cn": True})
        mocked.assert_called_once_with("203.0.113.7")

    def test_returns_false_for_overseas(self):
        """Non-mainland IPs are reported explicitly so the frontend can hide AtomGit."""
        with patch("common.api_v1.is_mainland_china_ip", return_value=False):
            response = self.client.get(self.URL, HTTP_X_FORWARDED_FOR="8.8.8.8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"is_mainland_cn": False})


class ResolveXdbPathTests(SimpleTestCase):
    """Verify xdb file path resolution."""

    def test_returns_path_when_file_exists(self):
        """An existing file path is returned as a Path object."""
        with tempfile.NamedTemporaryFile(suffix=".xdb", delete=False) as fp:
            fp.write(b"stub")
            xdb_path = fp.name
        try:
            with override_settings(IP2REGION_XDB_PATH=xdb_path):
                resolved = region_service._resolve_xdb_path()
            self.assertIsNotNone(resolved)
            self.assertEqual(str(resolved), xdb_path)
        finally:
            Path(xdb_path).unlink(missing_ok=True)


class LoadSearcherTests(SimpleTestCase):
    """Verify the searcher loader uses the ip2region library and caches results."""

    def setUp(self):
        """Reset the searcher cache between tests."""
        region_service._reset_searcher_cache()

    def tearDown(self):
        """Drop any searcher cached during the test."""
        region_service._reset_searcher_cache()

    def _stub_ip2region_modules(self, searcher: object) -> dict[str, object]:
        """Build fake ``ip2region.searcher`` / ``ip2region.util`` modules."""
        util_module = SimpleNamespace(
            IPv4="ipv4",
            load_content_from_file=lambda _path: b"buffer",
        )
        searcher_module = SimpleNamespace(
            new_with_buffer=lambda _ip_version, _buffer: searcher,
        )
        # ``import ip2region.searcher as xdb`` resolves the submodule via the
        # parent package's attribute, so the parent stub must expose both
        # children directly.
        parent = SimpleNamespace(searcher=searcher_module, util=util_module)
        return {
            "ip2region": parent,
            "ip2region.searcher": searcher_module,
            "ip2region.util": util_module,
        }

    def test_builds_and_caches_searcher(self):
        """The searcher is built once and reused on subsequent calls."""
        fake_searcher = MagicMock(name="searcher")
        with tempfile.NamedTemporaryFile(suffix=".xdb", delete=False) as fp:
            fp.write(b"stub")
            xdb_path = Path(fp.name)
        try:
            modules = self._stub_ip2region_modules(fake_searcher)
            with patch.dict(sys.modules, modules):
                first = region_service._load_searcher(xdb_path)
                second = region_service._load_searcher(xdb_path)
            self.assertIs(first, fake_searcher)
            # Second call must hit the cache without re-importing.
            self.assertIs(second, fake_searcher)
        finally:
            xdb_path.unlink(missing_ok=True)

    def test_end_to_end_lookup_through_load_searcher(self):
        """is_mainland_china_ip uses the real loader path with stubbed ip2region."""
        fake_searcher = MagicMock(name="searcher")
        fake_searcher.search.return_value = "中国|广东省|深圳市|电信|CN"
        with tempfile.NamedTemporaryFile(suffix=".xdb", delete=False) as fp:
            fp.write(b"stub")
            xdb_path = fp.name
        try:
            modules = self._stub_ip2region_modules(fake_searcher)
            with (
                override_settings(IP2REGION_XDB_PATH=xdb_path),
                patch.dict(sys.modules, modules),
            ):
                result = region_service.is_mainland_china_ip("113.118.113.77")
            self.assertTrue(result)
            fake_searcher.search.assert_called_once_with("113.118.113.77")
        finally:
            Path(xdb_path).unlink(missing_ok=True)

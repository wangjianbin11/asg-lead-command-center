import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from feishu_client import FeishuApiError, FeishuClient, FeishuClientConfig


class FakeFeishuTransport:
    """Records every call and returns canned Feishu-shaped responses.

    This stands in for a real urllib HTTP round-trip so the client's pagination,
    auth-token caching, and record CRUD can be exercised with no network.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, payload, timeout):
        self.calls.append((method, url, headers, payload, timeout))
        if "tenant_access_token" in url:
            return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
        if "page_token=next-page" in url:
            return {
                "code": 0,
                "data": {
                    "items": [{"record_id": "rec2", "fields": {"Lead ID": "LEAD-2"}}],
                    "has_more": False,
                },
            }
        if method == "GET":
            return {
                "code": 0,
                "data": {
                    "items": [{"record_id": "rec1", "fields": {"Lead ID": "LEAD-1"}}],
                    "has_more": True,
                    "page_token": "next-page",
                },
            }
        if method == "POST":
            return {"code": 0, "data": {"record": {"record_id": "new-rec", "fields": payload["fields"]}}}
        if method == "PUT":
            return {"code": 0, "data": {"record": {"record_id": "rec1", "fields": payload["fields"]}}}
        return {"code": 999, "msg": "unexpected"}


def _client(transport=None):
    return FeishuClient(
        FeishuClientConfig(app_id="app", app_secret="secret", app_token="base"),
        transport=transport or FakeFeishuTransport(),
    )


class FeishuClientTests(unittest.TestCase):
    # --- Case 7: pagination + CRUD via fake transport ---------------------

    def test_list_records_supports_pagination(self):
        # Spec §8.2 / §10: list_records must follow page_token across pages
        # until has_more is False.
        transport = FakeFeishuTransport()
        client = _client(transport)
        records = client.list_records("tbl")
        self.assertEqual([item["record_id"] for item in records], ["rec1", "rec2"])

    def test_list_records_follows_page_token_in_order(self):
        transport = FakeFeishuTransport()
        client = _client(transport)
        records = client.list_records("tbl")
        # First the initial page, then the next-page fetch.
        get_urls = [call[1] for call in transport.calls if call[0] == "GET"]
        self.assertEqual(len(get_urls), 2)
        self.assertIn("page_token=next-page", get_urls[1])
        self.assertEqual(records[0]["record_id"], "rec1")
        self.assertEqual(records[1]["record_id"], "rec2")

    def test_iter_records_stops_when_has_more_false(self):
        transport = FakeFeishuTransport()
        client = _client(transport)
        items = list(client.iter_records("tbl"))
        self.assertEqual(len(items), 2)
        self.assertFalse(transport.calls[-1][1].endswith("has_more=True"))

    def test_list_records_limit_stops_early(self):
        transport = FakeFeishuTransport()
        client = _client(transport)
        records = client.list_records("tbl", limit=1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_id"], "rec1")

    def test_create_and_update_records_wrap_fields(self):
        transport = FakeFeishuTransport()
        client = _client(transport)
        created = client.create_record("tbl", {"Lead ID": "LEAD-1"})
        updated = client.update_record("tbl", "rec1", {"Status": "Scored"})
        self.assertEqual(created["record_id"], "new-rec")
        self.assertEqual(updated["fields"]["Status"], "Scored")

    def test_create_record_echoes_fields(self):
        transport = FakeFeishuTransport()
        client = _client(transport)
        created = client.create_record(
            "tbl", {"Lead ID": "LEAD-1", "ASG Fit Score": 86}
        )
        self.assertEqual(created["fields"]["Lead ID"], "LEAD-1")
        self.assertEqual(created["fields"]["ASG Fit Score"], 86)

    def test_create_record_rejects_empty_fields(self):
        client = _client()
        with self.assertRaises(FeishuApiError):
            client.create_record("tbl", {})

    def test_update_record_requires_record_id(self):
        client = _client()
        with self.assertRaises(FeishuApiError):
            client.update_record("tbl", "", {"Status": "Scored"})

    def test_update_record_rejects_empty_fields(self):
        client = _client()
        with self.assertRaises(FeishuApiError):
            client.update_record("tbl", "rec1", {})

    def test_authorization_header_sent_on_data_calls(self):
        # Data calls (records CRUD) must carry a Bearer token in the header,
        # and must never put the app_secret in their request body. The tenant
        # access token endpoint is the one documented Feishu exception that
        # legitimately includes app_secret in its body, so it is excluded here.
        transport = FakeFeishuTransport()
        client = _client(transport)
        client.list_records("tbl")
        client.create_record("tbl", {"Lead ID": "L1"})
        data_calls = [
            c for c in transport.calls
            if c[0] in ("GET", "POST", "PUT") and "tenant_access_token" not in c[1]
        ]
        self.assertTrue(data_calls)
        for method, url, headers, body, _ in data_calls:
            self.assertTrue(
                headers["Authorization"].startswith("Bearer "),
                "%s %s missing Bearer header" % (method, url),
            )
            if body is not None:
                self.assertNotIn(
                    "app_secret",
                    body,
                    "app_secret must not appear in records request body",
                )

    def test_get_tenant_access_token_caches_token(self):
        # Multiple data calls must reuse the same tenant token (one auth call).
        transport = FakeFeishuTransport()
        client = _client(transport)
        client.list_records("tbl")
        client.create_record("tbl", {"Lead ID": "L1"})
        auth_calls = [c for c in transport.calls if "tenant_access_token" in c[1]]
        self.assertEqual(len(auth_calls), 1)

    # --- error handling ---------------------------------------------------

    def test_feishu_error_code_raises(self):
        class ErrTransport:
            def __call__(self, method, url, headers, payload, timeout):
                return {"code": 91402, "msg": "table not found"}

        client = _client(ErrTransport())
        with self.assertRaises(FeishuApiError):
            client.list_records("tbl")

    def test_missing_app_token_raises(self):
        client = FeishuClient(FeishuClientConfig(app_id="x", app_secret="y", app_token=""))
        with self.assertRaises(FeishuApiError):
            client.list_records("tbl")

    def test_missing_credentials_raise_on_token_request(self):
        client = FeishuClient(FeishuClientConfig())
        with self.assertRaises(FeishuApiError):
            client.get_tenant_access_token()

    def test_iter_records_missing_table_id_raises(self):
        client = _client()
        with self.assertRaises(FeishuApiError):
            list(client.iter_records(""))

    # --- config from env --------------------------------------------------

    def test_config_from_env_reads_credentials(self):
        import os

        saved = {
            k: os.environ.get(k)
            for k in (
                "FEISHU_APP_ID",
                "FEISHU_APP_SECRET",
                "FEISHU_BASE_APP_TOKEN",
                "FEISHU_TIMEOUT_SECONDS",
            )
        }
        try:
            os.environ["FEISHU_APP_ID"] = "env-app"
            os.environ["FEISHU_APP_SECRET"] = "env-secret"
            os.environ["FEISHU_BASE_APP_TOKEN"] = "env-base"
            os.environ["FEISHU_TIMEOUT_SECONDS"] = "12"
            config = FeishuClientConfig.from_env()
            self.assertEqual(config.app_id, "env-app")
            self.assertEqual(config.app_secret, "env-secret")
            self.assertEqual(config.app_token, "env-base")
            self.assertEqual(config.timeout, 12.0)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()


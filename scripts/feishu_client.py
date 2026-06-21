#!/usr/bin/env python3
"""Minimal Feishu Base client for ASG Lead Command Center.

The client intentionally reads all credentials and table IDs from environment
variables. Tests use fake transports and never call Feishu.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional


API_BASE = "https://open.feishu.cn/open-apis"
Transport = Callable[[str, str, Dict[str, str], Optional[Dict[str, Any]], float], Dict[str, Any]]


class FeishuApiError(RuntimeError):
    """Raised when Feishu returns an error or an invalid response."""


@dataclass
class FeishuClientConfig:
    app_id: str = ""
    app_secret: str = ""
    app_token: str = ""
    access_token: str = ""
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "FeishuClientConfig":
        return cls(
            app_id=os.getenv("FEISHU_APP_ID", "").strip(),
            app_secret=os.getenv("FEISHU_APP_SECRET", "").strip(),
            app_token=os.getenv("FEISHU_BASE_APP_TOKEN", "").strip(),
            access_token=(
                os.getenv("FEISHU_ACCESS_TOKEN", "").strip()
                or os.getenv("FEISHU_PERSONAL_TOKEN", "").strip()
                or os.getenv("FEISHU_TOKEN", "").strip()
            ),
            timeout=float(os.getenv("FEISHU_TIMEOUT_SECONDS", "60")),
        )


class FeishuClient:
    def __init__(
        self,
        config: Optional[FeishuClientConfig] = None,
        transport: Optional[Transport] = None,
    ) -> None:
        self.config = config or FeishuClientConfig.from_env()
        self.transport = transport
        self._tenant_access_token = self.config.access_token
        self._token_expires_at = 0.0

    def get_tenant_access_token(self, force_refresh: bool = False) -> str:
        if self._tenant_access_token and not force_refresh and time.time() < self._token_expires_at:
            return self._tenant_access_token
        if self.config.access_token and not force_refresh:
            self._tenant_access_token = self.config.access_token
            self._token_expires_at = time.time() + 3600
            return self._tenant_access_token
        if not self.config.app_id or not self.config.app_secret:
            raise FeishuApiError("missing FEISHU_APP_ID/FEISHU_APP_SECRET")

        payload = {
            "app_id": self.config.app_id,
            "app_secret": self.config.app_secret,
        }
        response = self._http_json(
            "POST",
            API_BASE + "/auth/v3/tenant_access_token/internal",
            {"Content-Type": "application/json"},
            payload,
        )
        self._raise_for_feishu_error(response, "get tenant access token")
        token = str(response.get("tenant_access_token") or "")
        if not token:
            raise FeishuApiError("tenant access token missing from response: %s" % response)
        expires_in = int(response.get("expire") or 7200)
        self._tenant_access_token = token
        self._token_expires_at = time.time() + max(60, expires_in - 120)
        return token

    def list_tables(self) -> List[Dict[str, Any]]:
        if not self.config.app_token:
            raise FeishuApiError("missing FEISHU_BASE_APP_TOKEN")
        data = self.api_request(
            "GET",
            "/bitable/v1/apps/%s/tables" % self.config.app_token,
            query={"page_size": 100},
        )
        return list(data.get("items") or [])

    def iter_records(
        self,
        table_id: str,
        view_id: str = "",
        field_names: Optional[List[str]] = None,
        filter_expression: Optional[str] = None,
        page_size: int = 100,
    ) -> Iterator[Dict[str, Any]]:
        if not self.config.app_token:
            raise FeishuApiError("missing FEISHU_BASE_APP_TOKEN")
        if not table_id:
            raise FeishuApiError("missing table_id")

        page_token = ""
        while True:
            query: Dict[str, Any] = {"page_size": page_size}
            if page_token:
                query["page_token"] = page_token
            if view_id:
                query["view_id"] = view_id
            if field_names:
                query["field_names"] = json.dumps(field_names, ensure_ascii=False)
            if filter_expression:
                query["filter"] = filter_expression

            data = self.api_request(
                "GET",
                "/bitable/v1/apps/%s/tables/%s/records" % (self.config.app_token, table_id),
                query=query,
            )
            for item in data.get("items") or []:
                yield item
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                raise FeishuApiError("Feishu pagination indicated has_more but no page_token")

    def list_records(
        self,
        table_id: str,
        view_id: str = "",
        field_names: Optional[List[str]] = None,
        filter_expression: Optional[str] = None,
        page_size: int = 100,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for record in self.iter_records(table_id, view_id, field_names, filter_expression, page_size):
            records.append(record)
            if limit is not None and len(records) >= limit:
                break
        return records

    def create_record(self, table_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        if not fields:
            raise FeishuApiError("create_record requires non-empty fields")
        data = self.api_request(
            "POST",
            "/bitable/v1/apps/%s/tables/%s/records" % (self.config.app_token, table_id),
            payload={"fields": fields},
        )
        return dict(data.get("record") or data)

    def update_record(self, table_id: str, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        if not record_id:
            raise FeishuApiError("update_record requires record_id")
        if not fields:
            raise FeishuApiError("update_record requires non-empty fields")
        data = self.api_request(
            "PUT",
            "/bitable/v1/apps/%s/tables/%s/records/%s"
            % (self.config.app_token, table_id, record_id),
            payload={"fields": fields},
        )
        return dict(data.get("record") or data)

    def api_request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        token = self.get_tenant_access_token()
        url = self._build_url(path, query)
        headers = {
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
        }
        response = self._http_json(method, url, headers, payload)
        self._raise_for_feishu_error(response, "%s %s" % (method, path))
        return dict(response.get("data") or {})

    def _build_url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
        url = path if path.startswith("http") else API_BASE + path
        if query:
            clean_query = {
                key: str(value)
                for key, value in query.items()
                if value is not None and str(value) != ""
            }
            encoded = urllib.parse.urlencode(clean_query)
            if encoded:
                url = url + ("&" if "?" in url else "?") + encoded
        return url

    def _http_json(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if self.transport:
            return self.transport(method, url, headers, payload, self.config.timeout)

        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise FeishuApiError("Feishu HTTP %s: %s" % (exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise FeishuApiError("Feishu request failed: %s" % exc) from exc
        try:
            return dict(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise FeishuApiError("Feishu returned invalid JSON: %s" % raw[:300]) from exc

    @staticmethod
    def _raise_for_feishu_error(response: Dict[str, Any], action: str) -> None:
        code = response.get("code", 0)
        if code not in (0, "0", None):
            raise FeishuApiError("%s failed: %s" % (action, response))


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ASG Lead Command Center Feishu client")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="show local Feishu configuration status")
    doctor.add_argument("--live", action="store_true", help="also request a tenant access token")

    list_records = sub.add_parser("list-records", help="list records from a table")
    list_records.add_argument("--table-id", required=True)
    list_records.add_argument("--limit", type=int, default=10)

    create_record = sub.add_parser("create-record", help="create one record from JSON fields")
    create_record.add_argument("--table-id", required=True)
    create_record.add_argument("--fields-json", required=True)

    update_record = sub.add_parser("update-record", help="update one record from JSON fields")
    update_record.add_argument("--table-id", required=True)
    update_record.add_argument("--record-id", required=True)
    update_record.add_argument("--fields-json", required=True)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = FeishuClientConfig.from_env()
    client = FeishuClient(config)

    if args.command == "doctor":
        result = {
            "FEISHU_APP_ID": bool(config.app_id),
            "FEISHU_APP_SECRET": bool(config.app_secret),
            "FEISHU_BASE_APP_TOKEN": bool(config.app_token),
            "direct_access_token": bool(config.access_token),
        }
        if args.live:
            result["tenant_access_token_ok"] = bool(client.get_tenant_access_token())
        _print_json(result)
        return 0

    if args.command == "list-records":
        _print_json(client.list_records(args.table_id, limit=args.limit))
        return 0

    if args.command == "create-record":
        fields = json.loads(args.fields_json)
        _print_json(client.create_record(args.table_id, fields))
        return 0

    if args.command == "update-record":
        fields = json.loads(args.fields_json)
        _print_json(client.update_record(args.table_id, args.record_id, fields))
        return 0

    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FeishuApiError as exc:
        print("error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)


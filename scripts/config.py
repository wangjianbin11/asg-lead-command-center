#!/usr/bin/env python3
"""Runtime configuration helpers for ASG Lead Command Center."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional


class ConfigError(RuntimeError):
    """Raised when required runtime configuration is missing."""


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def required_env(name: str) -> str:
    value = env(name)
    if not value:
        raise ConfigError("missing required environment variable: %s" % name)
    return value


@dataclass
class RuntimeConfig:
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_base_app_token: str = ""
    default_ai_provider: str = "openai"
    default_model: str = ""
    timezone: str = "Asia/Shanghai"
    table_ids: Optional[Dict[str, str]] = None

    @classmethod
    def from_env(cls, strict_feishu: bool = False) -> "RuntimeConfig":
        get_value = required_env if strict_feishu else env
        return cls(
            feishu_app_id=get_value("FEISHU_APP_ID"),
            feishu_app_secret=get_value("FEISHU_APP_SECRET"),
            feishu_base_app_token=get_value("FEISHU_BASE_APP_TOKEN"),
            default_ai_provider=env("DEFAULT_AI_PROVIDER", "openai"),
            default_model=env("DEFAULT_MODEL"),
            timezone=env("TIMEZONE", "Asia/Shanghai"),
            table_ids={
                "lead": env("FEISHU_LEAD_TABLE_ID"),
                "contact": env("FEISHU_CONTACT_TABLE_ID"),
                "score": env("FEISHU_SCORE_TABLE_ID"),
                "outreach": env("FEISHU_OUTREACH_TABLE_ID"),
                "conversation": env("FEISHU_CONVERSATION_TABLE_ID"),
                "content": env("FEISHU_CONTENT_TABLE_ID"),
                "report": env("FEISHU_REPORT_TABLE_ID"),
                "prompt": env("FEISHU_PROMPT_TABLE_ID"),
            },
        )

    def table_id(self, name: str) -> str:
        table_ids = self.table_ids or {}
        value = table_ids.get(name, "")
        if not value:
            raise ConfigError("missing Feishu table id for logical table: %s" % name)
        return value


"""Tests for install_service utility functions."""

import os
from pathlib import Path
from unittest.mock import patch


# ── _safe_agent_name ──────────────────────────────────────────────────────────


class TestSafeAgentName:
    def _call(self, instance_id: str, prefix: str = "hire"):
        with patch.dict(os.environ, {"HXA_CONNECT_AGENT_PREFIX": prefix}):
            # Re-import to pick up new env
            import importlib
            import app.services.install_service as mod
            mod._AGENT_PREFIX = prefix
            return mod._safe_agent_name(instance_id)

    def test_normal_instance_id(self):
        name = self._call("inst_abc123def456")
        assert name == "hire_abc123def456"

    def test_strips_inst_prefix(self):
        name = self._call("inst_e27571bdbfed")
        assert name == "hire_e27571bdbfed"
        assert "inst_" not in name

    def test_truncates_to_12_chars(self):
        name = self._call("inst_abcdef123456extra")
        suffix = name.split("_", 1)[1]
        assert len(suffix) == 12

    def test_short_id(self):
        name = self._call("inst_abc")
        assert name == "hire_abc"

    def test_custom_prefix(self):
        name = self._call("inst_xyz123", prefix="mybot")
        assert name == "mybot_xyz123"

    def test_special_chars_in_prefix_cleaned(self):
        name = self._call("inst_test123", prefix="my@bot!v2")
        # @ and ! should be replaced with _
        assert name.startswith("my_bot_v2_")

    def test_empty_prefix_defaults_to_hire(self):
        name = self._call("inst_test123", prefix="")
        assert name.startswith("hire_")

    def test_all_special_prefix_defaults_to_hire(self):
        name = self._call("inst_test123", prefix="@#$%")
        assert name.startswith("hire_")


# ── _normalize_anthropic_api_key ──────────────────────────────────────────────


class TestNormalizeAnthropicApiKey:
    def _call(self, current: str, token: str):
        from app.services.install_service import _normalize_anthropic_api_key
        return _normalize_anthropic_api_key(current, token)

    def test_prefers_current_sk_ant(self):
        assert self._call("sk-ant-abc123", "sk-ant-xyz789") == "sk-ant-abc123"

    def test_falls_back_to_token_sk_ant(self):
        assert self._call("", "sk-ant-xyz789") == "sk-ant-xyz789"

    def test_proxy_fallback(self):
        assert self._call("", "") == "sk-ant-proxy-via-sub2api"

    def test_non_sk_ant_current_ignored(self):
        assert self._call("some-other-key", "") == "sk-ant-proxy-via-sub2api"

    def test_whitespace_stripped(self):
        assert self._call("  sk-ant-abc  ", "").startswith("sk-ant-abc")

    def test_none_values(self):
        assert self._call(None, None) == "sk-ant-proxy-via-sub2api"


# ── _read_env_file / _write_env_file ─────────────────────────────────────────


class TestEnvFile:
    def test_roundtrip(self, tmp_path: Path):
        from app.services.install_service import _read_env_file, _write_env_file
        env_path = tmp_path / ".env"
        data = {"KEY1": "value1", "KEY2": "hello world", "EMPTY": ""}
        _write_env_file(env_path, data)
        result = _read_env_file(env_path)
        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "hello world"

    def test_read_nonexistent(self, tmp_path: Path):
        from app.services.install_service import _read_env_file
        result = _read_env_file(tmp_path / "nope.env")
        assert result == {}

    def test_comments_ignored(self, tmp_path: Path):
        from app.services.install_service import _read_env_file
        env_path = tmp_path / ".env"
        env_path.write_text("# comment\nKEY=val\n")
        result = _read_env_file(env_path)
        assert "KEY" in result
        assert "#" not in str(result.keys())

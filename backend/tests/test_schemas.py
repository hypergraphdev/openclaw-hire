"""Tests for Pydantic request/response schemas validation."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    RegisterRequest,
    LoginRequest,
    CreateInstanceRequest,
    ConfigureTelegramRequest,
    PRODUCT_MAP,
)


class TestRegisterRequest:
    def test_valid(self):
        r = RegisterRequest(name="Alice", email="alice@example.com", password="12345678")
        assert r.name == "Alice"

    def test_short_password(self):
        with pytest.raises(ValidationError, match="at least 8"):
            RegisterRequest(name="Alice", email="alice@example.com", password="short")

    def test_empty_name(self):
        with pytest.raises(ValidationError):
            RegisterRequest(name="  ", email="alice@example.com", password="12345678")

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            RegisterRequest(name="Alice", email="not-email", password="12345678")

    def test_name_stripped(self):
        r = RegisterRequest(name="  Bob  ", email="bob@test.com", password="12345678")
        assert r.name == "Bob"

    def test_optional_company(self):
        r = RegisterRequest(name="Eve", email="eve@test.com", password="12345678")
        assert r.company_name is None
        r2 = RegisterRequest(name="Eve", email="eve@test.com", password="12345678", company_name="Acme")
        assert r2.company_name == "Acme"


class TestLoginRequest:
    def test_valid(self):
        r = LoginRequest(email="user@test.com", password="pass")
        assert r.email == "user@test.com"

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="bad", password="pass")


class TestCreateInstanceRequest:
    def test_valid_openclaw(self):
        r = CreateInstanceRequest(name="my-app", product="openclaw")
        assert r.product == "openclaw"

    def test_valid_zylos(self):
        r = CreateInstanceRequest(name="my-bot", product="zylos")
        assert r.product == "zylos"

    def test_invalid_product(self):
        with pytest.raises(ValidationError, match="Product must be"):
            CreateInstanceRequest(name="test", product="unknown")

    def test_empty_name(self):
        with pytest.raises(ValidationError):
            CreateInstanceRequest(name="  ", product="openclaw")


class TestConfigureTelegramRequest:
    def test_valid(self):
        r = ConfigureTelegramRequest(telegram_bot_token="123456:ABC-DEF")
        assert r.telegram_bot_token == "123456:ABC-DEF"

    def test_empty_token(self):
        with pytest.raises(ValidationError):
            ConfigureTelegramRequest(telegram_bot_token="  ")


class TestProductCatalog:
    def test_products_defined(self):
        assert "openclaw" in PRODUCT_MAP
        assert "zylos" in PRODUCT_MAP

    def test_product_fields(self):
        oc = PRODUCT_MAP["openclaw"]
        assert oc.name == "OpenClaw"
        assert len(oc.features) > 0
        assert oc.repo_url.startswith("https://")

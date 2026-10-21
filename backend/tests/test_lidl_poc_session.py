"""Offline security regression tests for the local Lidl research CLI."""
import importlib.util
import json
import stat
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine, select

from app.core.encryption import DecryptionError, EncryptionKeyError, get_encryption_service
from app.models import Budget, BudgetMember, ExternalReceiptConnection, User

spec = importlib.util.spec_from_file_location(
    "lidl_research_cli", Path(__file__).resolve().parents[2] / "scripts/poc_lidl_auth.py"
)
assert spec and spec.loader
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


@pytest.fixture(autouse=True)
def private_session(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SESSION_FILE", tmp_path / "scratch/session.json")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TOKEN_PRIMARY_KEY_ID", "v1")
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEYS", raising=False)
    get_encryption_service(reload_env=True)


def test_session_is_encrypted_and_owner_binding_roundtrips():
    target = {"connection_id": 10, "budget_id": 20, "user_id": 30}
    cli._save_session({"refresh_token": "private-refresh", "access_token": "private-access"}, target)
    raw = cli.SESSION_FILE.read_text()
    assert "private-refresh" not in raw and "private-access" not in raw
    assert set(json.loads(raw)) == {"version", "key_id", "ciphertext"}
    assert stat.S_IMODE(cli.SESSION_FILE.stat().st_mode) == 0o600
    session = cli._load_session()
    assert session["refresh_token"] == "private-refresh"
    assert session["target"] == target


def test_missing_key_does_not_write_session_or_start_login(monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY")
    browser = Mock()
    monkeypatch.setattr(cli, "_try_playwright_login", browser)
    with pytest.raises(EncryptionKeyError):
        cli._save_session({"refresh_token": "private-refresh"})
    assert not cli.SESSION_FILE.exists()
    with pytest.raises(EncryptionKeyError):
        cli.run_live_login()
    browser.assert_not_called()


def test_legacy_plaintext_is_migrated_without_network():
    cli.SESSION_FILE.parent.mkdir()
    cli.SESSION_FILE.write_text(json.dumps({"refresh_token": "legacy-private-refresh"}))
    result = cli._load_session()
    assert result["refresh_token"] == "legacy-private-refresh"
    assert result["target"] is None
    assert "legacy-private-refresh" not in cli.SESSION_FILE.read_text()
    assert stat.S_IMODE(cli.SESSION_FILE.stat().st_mode) == 0o600


def test_wrong_key_cannot_read_session_or_overwrite_it(monkeypatch):
    cli._save_session({"refresh_token": "private-refresh"})
    original = cli.SESSION_FILE.read_bytes()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(DecryptionError):
        cli._load_session()
    assert cli.SESSION_FILE.read_bytes() == original


@pytest.fixture
def household(tmp_path):
    (tmp_path / "data").mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'data/database.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = User(email="first@test.local", hashed_password="hash")
        second = User(email="second@test.local", hashed_password="hash")
        session.add_all([first, second])
        session.commit()
        session.refresh(first)
        session.refresh(second)
        budget = Budget(name="Family", owner_id=first.id)
        session.add(budget)
        session.commit()
        session.refresh(budget)
        session.add_all([
            BudgetMember(budget_id=budget.id, user_id=first.id, role="owner"),
            BudgetMember(budget_id=budget.id, user_id=second.id, role="editor"),
        ])
        assert budget.id is not None and first.id is not None and second.id is not None
        one = ExternalReceiptConnection(budget_id=budget.id, owner_user_id=first.id, provider="lidl")
        two = ExternalReceiptConnection(budget_id=budget.id, owner_user_id=second.id, provider="lidl")
        session.add_all([one, two])
        session.commit()
        session.refresh(one)
        session.refresh(two)
        target = {"connection_id": one.id, "budget_id": budget.id, "user_id": first.id}
        second_user_id = second.id
    yield engine, target, second_user_id
    engine.dispose()


def test_only_explicit_household_connection_receives_token(household):
    engine, target, _ = household
    cli._sync_token_to_local_db({"refresh_token": "one-account-token"}, target)
    with Session(engine) as session:
        connections = session.exec(select(ExternalReceiptConnection)).all()
        assert len(connections) == 2
        for connection in connections:
            if connection.id == target["connection_id"]:
                assert connection.status == "active"
                assert connection.encrypted_refresh_token is not None
                assert get_encryption_service().decrypt(connection.encrypted_refresh_token) == "one-account-token"
            else:
                assert connection.encrypted_refresh_token is None
                assert connection.status == "reauth_required"


@pytest.mark.parametrize("wrong_field", ["user_id", "budget_id", "connection_id"])
def test_wrong_target_cannot_change_any_household_connection(household, wrong_field):
    engine, target, second_user_id = household
    wrong = dict(target)
    wrong[wrong_field] = second_user_id if wrong_field == "user_id" else 9999
    with pytest.raises(HTTPException):
        cli._sync_token_to_local_db({"refresh_token": "wrong-token"}, wrong)
    with Session(engine) as session:
        assert all(c.encrypted_refresh_token is None for c in session.exec(select(ExternalReceiptConnection)))


def test_refresh_preserves_binding_and_existing_refresh_token(household, monkeypatch):
    _, target, _ = household
    cli._save_session({"access_token": "old-access", "refresh_token": "old-refresh"}, target)
    client = Mock()
    client.refresh_access_token.return_value = {"access_token": "new-access"}
    monkeypatch.setattr(cli, "LidlPoCClient", lambda config: client)
    cli.run_live_refresh()
    saved = cli._load_session()
    assert saved["refresh_token"] == "old-refresh"
    assert saved["access_token"] == "new-access"
    assert saved["target"] == target
    client.refresh_access_token.assert_called_once_with("old-refresh")


def test_research_session_refresh_does_not_update_application_connections(monkeypatch):
    cli._save_session({"refresh_token": "research-only"})
    client = Mock()
    client.refresh_access_token.return_value = {"access_token": "new", "refresh_token": "rotated"}
    monkeypatch.setattr(cli, "LidlPoCClient", lambda config: client)
    sync = Mock()
    monkeypatch.setattr(cli, "_sync_token_to_local_db", sync)
    cli.run_live_refresh()
    sync.assert_not_called()
    assert cli._load_session()["refresh_token"] == "rotated"

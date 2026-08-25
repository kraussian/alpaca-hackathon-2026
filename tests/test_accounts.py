import datetime as dt

import pytest

from agent_pkg.accounts import KICKOFF, resolve_credentials

DEV_KEY = "PKDEVKEY0123456789ABCDEF12"
COMP_KEY = "PKCOMPKEY0123456789ABCDE12"

BEFORE_KICKOFF = dt.datetime(2026, 8, 25, 13, 0, tzinfo=dt.UTC)
AFTER_KICKOFF = dt.datetime(2026, 8, 28, 15, 1, tzinfo=dt.UTC)


def set_env(monkeypatch, **over):
    env = {
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_ACCOUNT_ROLE": "dev",
        "DEV_API_KEY": DEV_KEY,
        "DEV_SECRET_KEY": "devsecret",
        "ALPACA_API_KEY": COMP_KEY,
        "ALPACA_SECRET_KEY": "compsecret",
    }
    env.update(over)
    for k in (
        "ALPACA_PAPER_TRADE",
        "ALPACA_ACCOUNT_ROLE",
        "DEV_API_KEY",
        "DEV_SECRET_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    ):
        if env.get(k) is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, env[k])


def test_dev_role_selects_the_dev_keys(monkeypatch):
    set_env(monkeypatch)
    key, secret, role = resolve_credentials(now=BEFORE_KICKOFF)
    assert key == DEV_KEY
    assert secret == "devsecret"
    assert role == "dev"


def test_dev_role_never_returns_the_competition_key(monkeypatch):
    set_env(monkeypatch)
    key, _, _ = resolve_credentials(now=BEFORE_KICKOFF)
    assert key != COMP_KEY


def test_unset_role_is_an_error_not_a_default(monkeypatch):
    set_env(monkeypatch, ALPACA_ACCOUNT_ROLE=None)
    with pytest.raises(RuntimeError, match="ALPACA_ACCOUNT_ROLE"):
        resolve_credentials(now=BEFORE_KICKOFF)


def test_unknown_role_is_an_error(monkeypatch):
    set_env(monkeypatch, ALPACA_ACCOUNT_ROLE="production")
    with pytest.raises(RuntimeError, match="production"):
        resolve_credentials(now=BEFORE_KICKOFF)


def test_competition_role_is_refused_before_kickoff(monkeypatch):
    set_env(monkeypatch, ALPACA_ACCOUNT_ROLE="competition")
    with pytest.raises(RuntimeError, match="kickoff"):
        resolve_credentials(now=BEFORE_KICKOFF)


def test_competition_role_is_refused_one_second_before_kickoff(monkeypatch):
    set_env(monkeypatch, ALPACA_ACCOUNT_ROLE="competition")
    with pytest.raises(RuntimeError, match="kickoff"):
        resolve_credentials(now=KICKOFF - dt.timedelta(seconds=1))


def test_competition_role_is_allowed_after_kickoff(monkeypatch):
    set_env(monkeypatch, ALPACA_ACCOUNT_ROLE="competition")
    key, secret, role = resolve_credentials(now=AFTER_KICKOFF)
    assert key == COMP_KEY
    assert secret == "compsecret"
    assert role == "competition"


def test_missing_dev_keys_is_an_error(monkeypatch):
    set_env(monkeypatch, DEV_API_KEY=None)
    with pytest.raises(RuntimeError, match="DEV_API_KEY"):
        resolve_credentials(now=BEFORE_KICKOFF)


def test_non_paper_key_prefix_is_refused(monkeypatch):
    set_env(monkeypatch, DEV_API_KEY="AKLIVEKEY0123456789ABCDE12")
    with pytest.raises(RuntimeError, match="prefix"):
        resolve_credentials(now=BEFORE_KICKOFF)


def test_paper_flag_off_is_refused(monkeypatch):
    set_env(monkeypatch, ALPACA_PAPER_TRADE="false")
    with pytest.raises(RuntimeError, match="paper"):
        resolve_credentials(now=BEFORE_KICKOFF)

"""Tests for the user-global default Brain.

``spkt brain set-default`` lets the CLI run from anywhere by falling back
to a configured Brain when no ``.spikuit/`` is found by walking up.
"""

from pathlib import Path

import pytest

from spikuit_core.config import (
    get_default_brain,
    global_config_dir,
    global_config_path,
    init_brain,
    load_config,
    set_default_brain,
)


@pytest.fixture
def isolate_global(tmp_path, monkeypatch):
    """Point XDG_CONFIG_HOME at a scratch dir so the real ~/.config is untouched."""
    scratch = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(scratch))
    return scratch


def test_global_config_dir_honors_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert global_config_dir() == tmp_path / "cfg" / "spikuit"


def test_global_config_dir_defaults_to_dot_config(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert global_config_dir() == Path.home() / ".config" / "spikuit"


def test_get_default_brain_none_when_unset(isolate_global):
    assert get_default_brain() is None


def test_set_and_get_default_brain_roundtrip(tmp_path, isolate_global):
    vault = tmp_path / "vault"
    vault.mkdir()
    init_brain(vault)

    stored = set_default_brain(vault)
    assert stored == vault.resolve()
    assert get_default_brain() == vault.resolve()
    assert global_config_path().exists()


def test_set_default_brain_rejects_non_brain(tmp_path, isolate_global):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(FileNotFoundError):
        set_default_brain(plain)


def test_load_config_falls_back_to_default_brain(tmp_path, monkeypatch, isolate_global):
    vault = tmp_path / "vault"
    vault.mkdir()
    init_brain(vault, name="my-vault")
    set_default_brain(vault)

    # cwd has no .spikuit/ anywhere up its tree.
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    config = load_config()
    assert config.root == vault.resolve()
    assert config.name == "my-vault"


def test_load_config_local_brain_wins_over_default(tmp_path, monkeypatch, isolate_global):
    default_vault = tmp_path / "default"
    default_vault.mkdir()
    init_brain(default_vault, name="default-vault")
    set_default_brain(default_vault)

    local = tmp_path / "local"
    local.mkdir()
    init_brain(local, name="local-vault")
    monkeypatch.chdir(local)

    config = load_config()
    assert config.root == local.resolve()
    assert config.name == "local-vault"

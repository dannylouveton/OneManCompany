"""Tests for the company language setting (UI + AI employees)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from onemancompany.core import config as config_mod
from onemancompany.core import i18n


def _set_language(monkeypatch, value):
    monkeypatch.setattr(config_mod, "load_app_config", lambda: {"language": value} if value is not None else {})


class TestNormalizeLanguage:
    @pytest.mark.parametrize(
        "value,expected",
        [("fr", "fr"), ("FR", "fr"), ("fr-FR", "fr"), ("en_US", "en"), ("zh", "zh"),
         ("de", ""), ("", ""), (None, ""), (42, "")],
    )
    def test_normalize(self, value, expected):
        assert i18n.normalize_language(value) == expected


class TestLanguageDirective:
    def test_unset_language_adds_nothing(self, monkeypatch):
        _set_language(monkeypatch, None)
        assert i18n.get_company_language() == ""
        assert i18n.language_directive() == ""

    def test_french_directive(self, monkeypatch):
        _set_language(monkeypatch, "fr")
        text = i18n.language_directive()
        assert "## Working Language" in text
        assert "French" in text

    def test_explicit_language_overrides_config(self, monkeypatch):
        _set_language(monkeypatch, "fr")
        assert "Simplified Chinese" in i18n.language_directive("zh")

    def test_unsupported_config_value_is_ignored(self, monkeypatch):
        _set_language(monkeypatch, "klingon")
        assert i18n.language_directive() == ""


class TestCompanyContextInjection:
    """The directive reaches every executor through the task context block."""

    def _manager(self):
        from onemancompany.core.vessel import EmployeeManager

        mgr = EmployeeManager.__new__(EmployeeManager)
        mgr.executors = {"00010": MagicMock()}
        return mgr

    def _build(self, monkeypatch, lang):
        _set_language(monkeypatch, lang)
        with patch("onemancompany.core.store.load_culture", return_value=[]), \
             patch("onemancompany.core.store.load_employee_guidance", return_value=[]), \
             patch("onemancompany.core.store.load_employee_work_principles", return_value=""), \
             patch("onemancompany.core.config.load_workflows", return_value={}), \
             patch("onemancompany.core.config.load_employee_profile_yaml", return_value={}):
            return self._manager()._build_company_context_block("00010")

    def test_directive_present_when_set(self, monkeypatch):
        assert "## Working Language" in self._build(monkeypatch, "fr")

    def test_directive_absent_when_unset(self, monkeypatch):
        assert "## Working Language" not in self._build(monkeypatch, None)


class TestNicknames:
    def test_french_pool_used_when_language_is_french(self, monkeypatch):
        from onemancompany.agents import onboarding

        _set_language(monkeypatch, "fr")
        monkeypatch.setattr(
            onboarding, "_load_nickname_pool",
            lambda lang="zh": ["Le Renard", "La Chouette"] if lang == "fr" else ["凌风"],
        )
        assert onboarding._pick_nickname(2, {"Le Renard"}) == "La Chouette"

    def test_chinese_pool_by_default(self, monkeypatch):
        from onemancompany.agents import onboarding

        _set_language(monkeypatch, None)
        monkeypatch.setattr(onboarding, "_load_nickname_pool", lambda lang="zh": ["凌风", "御风行"])
        assert onboarding._pick_nickname(2, set()) == "凌风"

    def test_shipped_french_pool_is_unique(self):
        from onemancompany.agents.onboarding import _NICKNAMES_FILE

        names = [n for n in (_NICKNAMES_FILE.parent / "nicknames.fr.txt").read_text(encoding="utf-8").splitlines() if n.strip()]
        assert len(names) >= 30
        assert len(names) == len(set(names))


class TestLanguageRoutes:
    @pytest.mark.asyncio
    async def test_get_language(self, monkeypatch):
        from onemancompany.api.routes import get_language_settings

        _set_language(monkeypatch, "fr")
        result = await get_language_settings()
        assert result["language"] == "fr"
        assert "fr" in result["supported"] and "en" in result["supported"]

    @pytest.mark.asyncio
    async def test_put_rejects_unsupported(self):
        from fastapi import HTTPException
        from onemancompany.api.routes import update_language_settings

        with pytest.raises(HTTPException):
            await update_language_settings({"language": "xx"})

    @pytest.mark.asyncio
    async def test_put_writes_config_and_renames_nicknames(self, monkeypatch, tmp_path):
        from onemancompany.api import routes

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("hot_reload: true\n", encoding="utf-8")
        state = {"cfg": {"hot_reload": True}}

        def reload():
            state["cfg"] = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            return state["cfg"]

        monkeypatch.setattr(config_mod, "APP_CONFIG_PATH", cfg_path)
        monkeypatch.setattr(config_mod, "load_app_config", lambda: state["cfg"])
        monkeypatch.setattr(config_mod, "reload_app_config", reload)
        monkeypatch.setattr(routes, "_load_all", lambda: {
            "00001": {"nickname": "老板", "level": 5},
            "00002": {"nickname": "暖心侠", "level": 4},
            "00006": {"nickname": "Le Hibou", "level": 2},
            "00007": {"nickname": "The Owl", "level": 2},
        })
        monkeypatch.setattr("onemancompany.agents.onboarding._get_existing_nicknames", lambda: {"Le Hibou"})
        monkeypatch.setattr("onemancompany.agents.onboarding._pick_nickname", lambda n, existing: "Le Renard")
        monkeypatch.setattr("onemancompany.agents.onboarding._load_nickname_pool", lambda lang="zh": ["Le Hibou", "Le Renard"])
        save = AsyncMock()
        monkeypatch.setattr(routes._store, "save_employee", save)
        monkeypatch.setattr(routes, "_localize_default_principles", lambda emp_id, lang: False)
        monkeypatch.setattr(routes, "_rename_in_work_principles", lambda emp_id, nickname: None)

        result = await routes.update_language_settings({"language": "fr", "rename_nicknames": True})

        assert result["language"] == "fr"
        assert yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["language"] == "fr"
        assert result["renamed"] == {"00001": "Le Patron", "00002": "Le Renard", "00007": "Le Renard"}
        assert save.await_count == 3



class TestWorkPrinciplesHeading:
    def test_heading_nickname_is_replaced(self, monkeypatch, tmp_path):
        from onemancompany.api import routes

        emp_dir = tmp_path / "00004"
        emp_dir.mkdir()
        wp = emp_dir / "work_principles.md"
        wp.write_text("# Pat EA (玲珑阁) Work Principles\n\n- Be precise (always)\n", encoding="utf-8")
        monkeypatch.setattr(config_mod, "EMPLOYEES_DIR", tmp_path)

        routes._rename_in_work_principles("00004", "La Tramontane")

        text = wp.read_text(encoding="utf-8")
        assert text.startswith("# Pat EA (La Tramontane) Work Principles")
        assert "- Be precise (always)" in text


class TestLocalizedPrinciples:
    def _setup(self, monkeypatch, tmp_path, content):
        from onemancompany.api import routes

        data = tmp_path / "data"
        (data / "00003").mkdir(parents=True)
        (data / "00003" / "work_principles.md").write_text(content, encoding="utf-8")
        monkeypatch.setattr(config_mod, "EMPLOYEES_DIR", data)
        return routes, data / "00003" / "work_principles.md"

    def test_default_english_becomes_french(self, monkeypatch, tmp_path):
        from onemancompany.agents.onboarding import _NICKNAMES_FILE

        shipped = (_NICKNAMES_FILE.parent / "employees" / "00003" / "work_principles.md").read_text(encoding="utf-8")
        routes, path = self._setup(monkeypatch, tmp_path, shipped.replace("(铁面侠)", "(Le Forgeron)"))
        assert routes._localize_default_principles("00003", "fr") is True
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Principes de travail — Alex COO (Le Forgeron)")
        assert "Principes fondamentaux" in text
        # and back to English
        assert routes._localize_default_principles("00003", "en") is True
        assert path.read_text(encoding="utf-8").startswith("# Alex COO (Le Forgeron) Work Principles")

    def test_edited_principles_are_kept(self, monkeypatch, tmp_path):
        routes, path = self._setup(monkeypatch, tmp_path, "# Alex COO (X) Work Principles\n\n- my own rule\n")
        assert routes._localize_default_principles("00003", "fr") is False
        assert "my own rule" in path.read_text(encoding="utf-8")

    def test_french_heading_nickname_rename(self, monkeypatch, tmp_path):
        routes, path = self._setup(monkeypatch, tmp_path, "# Principes de travail — Alex COO (Le Forgeron)\n\n- a (b)\n")
        routes._rename_in_work_principles("00003", "Le Lynx")
        assert path.read_text(encoding="utf-8") == "# Principes de travail — Alex COO (Le Lynx)\n\n- a (b)\n"

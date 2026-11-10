"""The founding DSI: created once with the COO's settings, then part of the direction everywhere."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import yaml

from onemancompany.core import config as config_mod
from onemancompany.core import founding


def _write_profile(emp_dir, data):
    emp_dir.mkdir(parents=True, exist_ok=True)
    (emp_dir / "profile.yaml").write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


@pytest.fixture()
def company(tmp_path, monkeypatch):
    hr = tmp_path / "human_resource"
    employees = hr / "employees"
    coo = employees / "00003"
    _write_profile(coo, {"name": "Alex COO", "role": "COO", "level": 4, "hosting": "self",
                         "api_provider": "anthropic", "llm_model": "claude-opus-5-5", "auth_method": "api_key",
                         "permissions": ["company_file_access", "web_search"], "temperature": 0.7})
    (coo / "skills" / "tool_management").mkdir(parents=True)
    (coo / "skills" / "tool_management" / "SKILL.md").write_text("# Tool Management", encoding="utf-8")
    (coo / "manifest.json").write_text(json.dumps({"id": "coo-founding", "name": "COO Manager", "role": "COO",
                                                   "hosting": "self"}, indent=2), encoding="utf-8")
    (coo / "launch.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (coo / "avatar.png").write_bytes(b"fox")
    _write_profile(employees / "00007", {"name": "Léa", "role": "Lead DevOps / SRE", "level": 2})
    (hr / "avatars").mkdir()
    (hr / "avatars" / "fox.png").write_bytes(b"fox")
    (hr / "avatars" / "owl.png").write_bytes(b"owl")
    guides = hr / "role_guides"
    monkeypatch.setattr(config_mod, "EMPLOYEES_DIR", employees)
    monkeypatch.setattr(config_mod, "HR_DIR", hr)
    monkeypatch.setattr(config_mod, "ROLE_GUIDES_DIR", guides)
    monkeypatch.setattr("onemancompany.core.i18n.get_company_language", lambda: "fr")
    return employees


def test_the_dsi_is_created_once_from_the_coo(company):
    emp_id = founding.create_founding_dsi()
    assert emp_id == "00008"
    folder = company / emp_id
    profile = yaml.safe_load((folder / "profile.yaml").read_text(encoding="utf-8"))
    assert profile["role"] == "DSI" and profile["level"] == 4 and profile["title"] == "Founding"
    assert (profile["name"], profile["nickname"]) == ("Charlie DSI", "Le Gardien")
    assert profile["hosting"] == "self" and profile["llm_model"] == "claude-opus-5-5"
    assert profile["permissions"] == ["company_file_access", "web_search"]
    assert profile["employee_number"] == "00008" and profile["department"] == "IT"
    assert "coffre" in (folder / "role_guide.md").read_text(encoding="utf-8")  # French guide from the template
    assert (config_mod.ROLE_GUIDES_DIR / "DSI.md").exists()
    assert "Le Gardien" in (folder / "work_principles.md").read_text(encoding="utf-8")
    assert (folder / "skills" / "tool_management" / "SKILL.md").exists()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "dsi-founding" and manifest["role"] == "DSI" and manifest["hosting"] == "self"
    assert (folder / "avatar.png").read_bytes() == b"owl"  # the fox is already worn by the COO
    assert founding.founding_dsi_on_disk(company) == "00008"
    assert founding.create_founding_dsi() == "00008" and not (company / "00009").exists()


def test_no_dsi_before_the_company_exists(company, tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "EMPLOYEES_DIR", tmp_path / "nowhere")
    assert founding.create_founding_dsi() == ""
    assert founding.founding_dsi_on_disk(tmp_path / "nowhere") == ""


def test_only_a_founding_dsi_counts(company):
    _write_profile(company / "00010", {"role": "DSI", "level": 2})
    _write_profile(company / "00011", {"role": "DSI", "level": "Lv.4"})
    (company / "00012").mkdir()
    (company / "00012" / "profile.yaml").write_text("- not a profile", encoding="utf-8")
    assert founding.founding_dsi_on_disk(company) == ""
    _write_profile(company / "00013", {"role": "dsi", "level": 4})
    assert founding.founding_dsi_on_disk(company) == "00013"


def test_the_server_restarts_once_after_creating_the_dsi(monkeypatch):
    from onemancompany import main as main_mod

    execv = MagicMock()
    monkeypatch.setattr(main_mod.os, "execv", execv)
    monkeypatch.setenv(main_mod.ENV_FOUNDING_DSI_RESTART, "")  # unset again after the test
    monkeypatch.setattr(config_mod, "DSI_ID", "")
    monkeypatch.setattr(founding, "create_founding_dsi", lambda: "00009")
    main_mod._ensure_founding_dsi()
    assert execv.call_count == 1 and execv.call_args[0][1][1:] == ["-m", "onemancompany.main"]
    assert main_mod.os.environ[main_mod.ENV_FOUNDING_DSI_RESTART] == "1"
    main_mod._ensure_founding_dsi()  # the flag stops a loop
    monkeypatch.setenv(main_mod.ENV_FOUNDING_DSI_RESTART, "")
    monkeypatch.setattr(founding, "create_founding_dsi", lambda: "")
    main_mod._ensure_founding_dsi()  # nothing created: no restart
    monkeypatch.setattr(config_mod, "DSI_ID", "00009")
    monkeypatch.setattr(founding, "create_founding_dsi", lambda: pytest.fail("already there"))
    main_mod._ensure_founding_dsi()
    assert execv.call_count == 1


def test_the_dsi_sits_in_the_executive_row(monkeypatch):
    from onemancompany.core import layout

    monkeypatch.setattr(config_mod, "DSI_ID", "00009")
    positions = layout._get_executive_positions()
    xs = sorted(x for x, _ in positions.values())
    assert positions["00009"] == (15, layout.EXEC_ROW_GY) and len(xs) == 5
    assert all(b - a >= 3 for a, b in zip(xs, xs[1:]))  # desks are two tiles wide
    assert not any(x in (8, 9, 10) for x in xs) and max(xs) + 1 < layout.TOTAL_COLS  # the CEO's desk is at 9
    monkeypatch.setattr(config_mod, "DSI_ID", "")
    assert len(layout._get_executive_positions()) == 4


def test_founding_executives_get_their_role_guide(tmp_path, monkeypatch):
    from onemancompany.core import vessel

    (tmp_path / "00003").mkdir()
    (tmp_path / "00003" / "role_guide.md").write_text("# COO — Role Guide\nAccess desk", encoding="utf-8")
    (tmp_path / "00001").mkdir()
    (tmp_path / "00001" / "role_guide.md").write_text("# CEO", encoding="utf-8")
    monkeypatch.setattr(config_mod, "EMPLOYEES_DIR", tmp_path)
    assert "Access desk" in vessel.build_role_identity("00003")
    assert vessel.build_role_identity("00001") == ""
    assert vessel.build_role_identity("00005") == ""  # founding, no guide on disk


def test_other_executives_know_the_dsi(monkeypatch):
    from onemancompany.core import vessel

    monkeypatch.setattr(config_mod, "DSI_ID", "00009")
    monkeypatch.setattr(config_mod, "EXEC_IDS", frozenset({"00002", "00003", "00004", "00005", "00009"}))
    monkeypatch.setattr(vessel._store, "load_culture", lambda: [])
    monkeypatch.setattr(vessel._store, "load_employee_guidance", lambda e: [])
    monkeypatch.setattr(vessel._store, "load_employee_work_principles", lambda e: "")
    monkeypatch.setattr(config_mod, "load_workflows", lambda: {})
    mgr = vessel.EmployeeManager.__new__(vessel.EmployeeManager)
    mgr.executors = {}
    monkeypatch.setattr(vessel, "build_role_identity", lambda e: "")
    assert "The DSI (00009)" in mgr._build_company_context_block("00004")
    assert "The DSI (00009)" not in mgr._build_company_context_block("00009")
    assert "The DSI (00009)" not in mgr._build_company_context_block("00007")


def test_the_desk_names_the_dsi_in_threads(monkeypatch):
    from onemancompany.core import access_desk

    monkeypatch.setattr(access_desk, "_lang", lambda: "fr")
    monkeypatch.setattr(access_desk, "label", lambda e: e)
    req = {"service": "OVH", "card": {"what": "le compte", "deliverable": "action"}}
    entry = {"employee": "00007", "reason": "DNS", "access": "write", "opened_by": "le CEO"}
    monkeypatch.setattr(access_desk, "dsi_id", lambda: "00009")
    assert "le DSI s'en occupe" in access_desk.thread_text("requested", req, entry)
    assert "le DSI a envoyé une demande au CEO" in access_desk.thread_text("escalated", req)
    monkeypatch.setattr(access_desk, "dsi_id", lambda: "")
    assert "Transmise au COO" in access_desk.thread_text("requested", req, {**entry, "opened_by": ""})


def test_the_founding_dsi_runs_the_desk(monkeypatch):
    from onemancompany.core import access_desk

    monkeypatch.setattr(config_mod, "DSI_ID", "00009")
    monkeypatch.setattr("onemancompany.core.store.load_all_employees", lambda: pytest.fail("no scan needed"))
    assert access_desk.dsi_id() == "00009" and access_desk.desk_owner_id() == "00009"

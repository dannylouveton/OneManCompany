"""Founding team: the DSI joins HR, the COO, the EA and the CSO.

The DSI (head of IT and access) is not hired: like the other founding
executives, it is part of the company from the start. A company created
before the DSI existed gets one on its next start (main.run). Its profile
follows the COO's (same agent family, model and permissions), with the DSI's
own identity, role guide, work principles and desk in the executive row.

This module is imported by core/config.py: keep its top-level imports to the
standard library, yaml and loguru.
"""

from __future__ import annotations

import hashlib
import random
import shutil
from pathlib import Path

import yaml
from loguru import logger

DSI_ROLE = "DSI"
DSI_DEPARTMENT = "IT"
FOUNDING_LEVEL = 4
DSI_NAMES = {"fr": ("Charlie DSI", "Le Gardien"), "en": ("Charlie DSI", "The Keeper")}
# Settings taken from the COO's profile: how the company runs its executives
_FROM_COO = ("hosting", "api_provider", "llm_model", "temperature", "image_model", "auth_method",
             "salary_per_1m_tokens", "permissions", "tool_permissions")
_PRINCIPLES = {
    "fr": ("# Principes de travail — {name} ({nickname})\n\n"
           "**Service** : IT\n**Rôle** : DSI\n**Niveau** : Fondateur\n\n"
           "## Principes fondamentaux\n"
           "1. Donner à chacun les accès dont son travail a besoin, au plus juste et vite\n"
           "2. Ne jamais voir, écrire ni transmettre un secret : mots de passe et clés restent dans le coffre\n"
           "3. Créer les comptes au nom de l'entreprise, dans le respect des conditions des fournisseurs\n"
           "4. Ne solliciter le CEO que pour ce que lui seul peut faire\n"),
    "en": ("# {name} ({nickname}) Work Principles\n\n"
           "**Department**: IT\n**Role**: DSI\n**Level**: Founding\n\n"
           "## Core Principles\n"
           "1. Give everyone the access their work needs, no more, and quickly\n"
           "2. Never see, write or pass on a secret: passwords and keys stay in the vault\n"
           "3. Create accounts on behalf of the company, within each provider's terms\n"
           "4. Only ask the CEO for what only the CEO can do\n"),
}


def _lang() -> str:
    from onemancompany.core.i18n import get_company_language

    return "fr" if get_company_language() == "fr" else "en"


def _level(data: dict) -> int:
    try:
        return int(data.get("level", 0) or 0)
    except (TypeError, ValueError):
        return 0


def founding_dsi_on_disk(employees_dir: Path) -> str:
    """Employee number of the founding DSI (role DSI, founding level), or ""."""
    if not employees_dir.is_dir():
        return ""
    for emp_dir in sorted(employees_dir.iterdir()):
        profile = emp_dir / "profile.yaml"
        if not profile.is_file():
            continue
        try:
            data = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.debug("[founding] unreadable profile {}: {}", profile, exc)
            continue
        if isinstance(data, dict) and str(data.get("role", "")).strip().upper() == DSI_ROLE \
                and _level(data) >= FOUNDING_LEVEL:
            return emp_dir.name
    return ""


def _next_number(employees_dir: Path) -> str:
    numbers = [int(d.name) for d in employees_dir.iterdir() if d.is_dir() and d.name.isdigit()]
    return f"{max([5, *numbers]) + 1:05d}"


def _role_guide_text(lang: str) -> str:
    from onemancompany.core.config import COMPANY_TEMPLATE_DIR, ROLE_GUIDES_DIR, SOURCE_ROOT

    template = SOURCE_ROOT / COMPANY_TEMPLATE_DIR
    for path in (ROLE_GUIDES_DIR / f"{DSI_ROLE}.md",
                 template / "locales" / lang / "human_resource" / "role_guides" / f"{DSI_ROLE}.md",
                 template / "human_resource" / "role_guides" / f"{DSI_ROLE}.md"):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pick_avatar(avatars_dir: Path, employees_dir: Path) -> Path | None:
    """A random avatar no colleague already wears (any avatar if all are taken)."""
    if not avatars_dir.is_dir():
        return None
    avatars = sorted(p for p in avatars_dir.iterdir() if p.suffix in (".png", ".jpg", ".jpeg"))
    if not avatars:
        return None
    worn = {_digest(p) for p in employees_dir.glob("*/avatar.*") if p.is_file()}
    free = [p for p in avatars if _digest(p) not in worn]
    return random.choice(free or avatars)


def create_founding_dsi() -> str:
    """Create the founding DSI if the company has none. Returns its employee number ("" if not created)."""
    from onemancompany.core.config import COO_ID, EMPLOYEES_DIR, HR_DIR, ROLE_GUIDES_DIR

    existing = founding_dsi_on_disk(EMPLOYEES_DIR)
    if existing:
        return existing
    coo_dir = EMPLOYEES_DIR / COO_ID
    if not (coo_dir / "profile.yaml").is_file():
        return ""  # company not initialised yet (onboarding creates the founding team)
    try:
        coo = yaml.safe_load((coo_dir / "profile.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[founding] COO profile unreadable, DSI gets defaults: {}", exc)
        coo = {}

    lang = _lang()
    name, nickname = DSI_NAMES[lang]
    emp_id = _next_number(EMPLOYEES_DIR)
    emp_dir = EMPLOYEES_DIR / emp_id
    profile = {k: coo[k] for k in _FROM_COO if k in coo}
    profile.setdefault("hosting", "company")
    profile.setdefault("permissions", ["company_file_access", "web_search", "asset_management"])
    profile.update({
        "name": name, "nickname": nickname, "role": DSI_ROLE, "department": DSI_DEPARTMENT,
        "level": FOUNDING_LEVEL, "title": "Founding", "employee_number": emp_id, "desk_position": [15, 0],
        "sprite": "", "skills": ["tool_management"], "performance_history": [], "current_quarter_tasks": 0,
        "probation": False, "onboarding_completed": True,
    })

    emp_dir.mkdir(parents=True)
    (emp_dir / "profile.yaml").write_text(
        yaml.dump(profile, allow_unicode=True, default_flow_style=False, sort_keys=True), encoding="utf-8")
    (emp_dir / "work_principles.md").write_text(
        _PRINCIPLES[lang].format(name=name, nickname=nickname), encoding="utf-8")

    guide = _role_guide_text(lang)
    if guide:
        (emp_dir / "role_guide.md").write_text(guide, encoding="utf-8")
        shared = ROLE_GUIDES_DIR / f"{DSI_ROLE}.md"
        if not shared.exists():
            shared.parent.mkdir(parents=True, exist_ok=True)
            shared.write_text(guide, encoding="utf-8")

    (emp_dir / "skills").mkdir()
    if (coo_dir / "skills" / "tool_management").is_dir():
        shutil.copytree(coo_dir / "skills" / "tool_management", emp_dir / "skills" / "tool_management")
    if (coo_dir / "launch.sh").is_file():
        shutil.copy2(coo_dir / "launch.sh", emp_dir / "launch.sh")
    if (coo_dir / "manifest.json").is_file():
        manifest = (coo_dir / "manifest.json").read_text(encoding="utf-8")
        manifest = (manifest.replace('"coo-founding"', '"dsi-founding"')
                    .replace('"COO Manager"', '"DSI"')
                    .replace('"role": "COO"', f'"role": "{DSI_ROLE}"'))
        (emp_dir / "manifest.json").write_text(manifest, encoding="utf-8")

    avatar = _pick_avatar(HR_DIR / "avatars", EMPLOYEES_DIR)
    if avatar is not None:
        shutil.copy2(avatar, emp_dir / f"avatar{avatar.suffix}")

    logger.info("[founding] created the DSI: {} ({}, {})", emp_id, name, nickname)
    return emp_id

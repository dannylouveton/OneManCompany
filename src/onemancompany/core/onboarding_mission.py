"""New hires start like top performers: a charter and a first mission.

At hire (or on demand for someone already on the team):

* the **onboarding charter** (company rule ``onboarding_charter``) is added to
  the employee's work principles, which are injected into every task;
* an **arrival note** (company rule ``onboarding_mission``) wakes them up:
  nothing is assigned; like a top performer, they decide how to take up the
  role, act, and report up the hierarchy (report_up);
* the weekly improvement round is theirs to set up (set_cron); config can
  still impose it with ``weekly: true``.

Both texts live with the company rules, so the CEO can read and edit them.
config.yaml::

    onboarding:
      charter: true    # default
      mission: true    # default
      weekly: false    # default: the employee sets up their own round
"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

CHARTER_DOC = "onboarding_charter"
MISSION_DOC = "onboarding_mission"
WEEKLY_CRON = "weekly_improvements"
_START = "<!-- onboarding-charter:start -->"
_END = "<!-- onboarding-charter:end -->"

_WEEKLY_TASK = {
    "fr": ("Tour hebdomadaire de ton domaine : repère les 3 améliorations les plus utiles "
           "(problèmes, choses qui traînent, opportunités), réalise-les, puis envoie au CEO "
           "un compte rendu court avec report_to_ceo."),
    "en": ("Weekly round of your area: spot the 3 most useful improvements (problems, "
           "unfinished work, opportunities), carry them out, then send the CEO a short "
           "report with report_to_ceo."),
}
_PROJECT_NAME = {"fr": "Intégration de {who}", "en": "Onboarding: {who}"}


def _settings() -> dict:
    from onemancompany.core.config import load_app_config

    cfg = load_app_config().get("onboarding")
    cfg = cfg if isinstance(cfg, dict) else {}
    # The weekly round is the employee's own initiative (set_cron), not imposed.
    return {"charter": cfg.get("charter", True) is not False,
            "mission": cfg.get("mission", True) is not False,
            "weekly": cfg.get("weekly", False) is True}


def _lang() -> str:
    from onemancompany.core.i18n import get_company_language

    return "fr" if get_company_language() == "fr" else "en"


def _doc(name: str) -> str:
    from onemancompany.core.config import load_workflows

    return (load_workflows().get(name) or "").strip()


def apply_charter(employee_id: str) -> bool:
    """Add (or refresh) the charter in the employee's work principles."""
    from onemancompany.core.config import EMPLOYEES_DIR

    charter = _doc(CHARTER_DOC)
    if not charter:
        return False
    path = EMPLOYEES_DIR / employee_id / "work_principles.md"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"{_START}\n{charter}\n{_END}"
    if _START in current and _END in current:
        updated = re.sub(re.escape(_START) + r".*?" + re.escape(_END), lambda _m: block, current, flags=re.S)
    else:
        updated = (current.rstrip() + "\n\n" if current.strip() else "") + block + "\n"
    if updated != current:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
    return True


def render_mission(template: str, values: dict[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value or "—")
    return out


async def launch_mission(employee_id: str, hire_context: str = "") -> dict:
    """Let the newcomer start: an arrival note, not an assignment.

    Nothing is assigned from the top. The employee is woken up with the
    "taking up the role" note (company rule ``onboarding_mission``): context
    and the way top performers start. What to do is theirs to decide; results
    go up the hierarchy with report_up.
    """
    from onemancompany.api.routes import _push_adhoc_task
    from onemancompany.core.config import get_workspace_dir
    from onemancompany.core.store import load_employee

    template = _doc(MISSION_DOC)
    if not template:
        return {"status": "skipped", "reason": "no onboarding_mission rule"}
    emp = load_employee(employee_id) or {}
    note = render_mission(template, {
        "name": emp.get("name", ""), "nickname": emp.get("nickname") or emp.get("name") or employee_id,
        "role": emp.get("role", ""), "department": emp.get("department", ""),
        "context": hire_context.strip(), "workspace": str(get_workspace_dir(employee_id)),
    })
    node_id = _push_adhoc_task(employee_id, note)
    logger.info("[onboarding] arrival note sent to {} (node {})", employee_id, node_id)
    return {"status": "launched", "node_id": node_id}


def start_weekly(employee_id: str) -> dict:
    from onemancompany.core.automation import start_cron

    return start_cron(employee_id, WEEKLY_CRON, "7d", _WEEKLY_TASK[_lang()])


async def onboard(employee_id: str, hire_context: str = "", *, force: bool = False) -> dict:
    """Charter + mission + weekly round, as configured. Never raises."""
    settings = {**_settings(), "charter": True, "mission": True} if force else _settings()
    result: dict = {"employee_id": employee_id}
    try:
        if settings["charter"]:
            result["charter"] = apply_charter(employee_id)
        if settings["mission"]:
            result["mission"] = await launch_mission(employee_id, hire_context)
        if settings["weekly"]:
            result["weekly"] = start_weekly(employee_id).get("status", "ok")
    except Exception as exc:  # a hire must never fail because of onboarding
        logger.exception("[onboarding] failed for {}: {}", employee_id, exc)
        result["error"] = str(exc)
    return result

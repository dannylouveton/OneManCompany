"""New hires start like top performers: a charter and a first mission.

At hire (or on demand for someone already on the team):

* the **onboarding charter** (company rule ``onboarding_charter``) is added to
  the employee's work principles, which are injected into every task;
* an **onboarding mission** project (company rule ``onboarding_mission``) is
  assigned directly to them: map what exists, carry out quick wins, write a
  roadmap and start it, report;
* a **weekly improvement** scheduled task keeps the initiative going.

Both texts live with the company rules, so the CEO can read and edit them.
config.yaml::

    onboarding:
      charter: true    # default
      mission: true    # default
      weekly: true     # default
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
    return {k: cfg.get(k, True) is not False for k in ("charter", "mission", "weekly")}


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
    """Create the onboarding mission project, assigned directly to the employee."""
    from onemancompany.agents.tree_tools import _add_to_project_team
    from onemancompany.core.config import CEO_ID, TASK_TREE_FILENAME
    from onemancompany.core.conversation import get_conversation_service
    from onemancompany.core.project_archive import create_iteration, create_named_project, get_project_dir
    from onemancompany.core.store import load_employee
    from onemancompany.core.task_lifecycle import NodeType, TaskPhase
    from onemancompany.core.task_tree import TaskTree
    from onemancompany.core.vessel import _save_project_tree, employee_manager

    template = _doc(MISSION_DOC)
    if not template:
        return {"status": "skipped", "reason": "no onboarding_mission rule"}
    emp = load_employee(employee_id) or {}
    who = emp.get("nickname") or emp.get("name") or employee_id
    lang = _lang()
    project_name = _PROJECT_NAME[lang].format(who=who)
    pid = create_named_project(project_name)
    iter_id = create_iteration(pid, project_name, "pending")
    pdir = get_project_dir(pid)
    ctx_id = f"{pid}/{iter_id}" if iter_id else pid
    mission = render_mission(template, {
        "name": emp.get("name", ""), "nickname": who, "role": emp.get("role", ""),
        "department": emp.get("department", ""), "context": hire_context.strip(),
        "workspace": str(pdir),
    })
    mission += f"\n\n[Project ID: {ctx_id}] [Project workspace: {pdir}]"

    tree = TaskTree(project_id=ctx_id, mode="simple")
    root = tree.create_root(employee_id=CEO_ID, description=project_name)
    root.node_type = NodeType.CEO_PROMPT
    root.set_status(TaskPhase.PROCESSING)
    node = tree.add_child(parent_id=root.id, employee_id=employee_id, description=mission,
                          acceptance_criteria=[], title=project_name)
    node.project_id = ctx_id
    node.project_dir = str(pdir)
    _save_project_tree(pdir, tree)
    conv = await get_conversation_service().get_or_create_project_conversation(ctx_id, [CEO_ID, employee_id])
    await get_conversation_service().push_system_message(conv.id, f"Project created: {project_name}",
                                                         source_employee="system")
    _add_to_project_team(pdir, CEO_ID)
    _add_to_project_team(pdir, employee_id)
    employee_manager.schedule_node(employee_id, node.id, str(Path(pdir) / TASK_TREE_FILENAME))
    employee_manager._schedule_next(employee_id)
    logger.info("[onboarding] mission {} launched for {}", ctx_id, employee_id)
    return {"status": "launched", "project_id": pid, "project_dir": str(pdir)}


def start_weekly(employee_id: str) -> dict:
    from onemancompany.core.automation import start_cron

    return start_cron(employee_id, WEEKLY_CRON, "7d", _WEEKLY_TASK[_lang()])


async def onboard(employee_id: str, hire_context: str = "", *, force: bool = False) -> dict:
    """Charter + mission + weekly round, as configured. Never raises."""
    settings = {"charter": True, "mission": True, "weekly": True} if force else _settings()
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

"""New hires start like top performers: a charter and a first mission.

At hire (or on demand for someone already on the team):

* the **onboarding charter** (company rule ``onboarding_charter``) is how
  everyone here works: it is injected for every employee, not copied;
* an **arrival note** (company rule ``onboarding_mission``) wakes them up:
  nothing is assigned; like a top performer, they decide how to take up the
  role, act, and report up the hierarchy (report_up);
* the weekly improvement round is theirs to set up (set_cron); config can
  still impose it with ``weekly: true``.

Both texts live with the company rules, so the CEO can read and edit them.
config.yaml::

    onboarding:
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
_PROJECT_NAME = {"fr": "Prise de poste — {who}", "en": "Taking up the role: {who}"}


def _settings() -> dict:
    from onemancompany.core.config import load_app_config

    cfg = load_app_config().get("onboarding")
    cfg = cfg if isinstance(cfg, dict) else {}
    # The weekly round is the employee's own initiative (set_cron), not imposed.
    return {"mission": cfg.get("mission", True) is not False,
            "weekly": cfg.get("weekly", False) is True}


def _lang() -> str:
    from onemancompany.core.i18n import get_company_language

    return "fr" if get_company_language() == "fr" else "en"


def _doc(name: str) -> str:
    from onemancompany.core.config import load_workflows

    return (load_workflows().get(name) or "").strip()


def remove_charter(employee_id: str) -> bool:
    """Remove a charter copy from the employee's work principles (older versions copied it).

    The charter is a company rule now, injected for every employee.
    """
    from onemancompany.core.config import EMPLOYEES_DIR

    path = EMPLOYEES_DIR / employee_id / "work_principles.md"
    if not path.exists():
        return False
    current = path.read_text(encoding="utf-8")
    updated = re.sub(r"\n*" + re.escape(_START) + r".*?" + re.escape(_END) + r"\n?", "\n", current, flags=re.S)
    if updated != current:
        path.write_text(updated.rstrip() + "\n", encoding="utf-8")
        return True
    return False


def render_mission(template: str, values: dict[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value or "—")
    return out


async def launch_mission(employee_id: str, hire_context: str = "") -> dict:
    """Let the newcomer start: an arrival note, not an assignment.

    The note (company rule ``onboarding_mission``) gives context and the way
    top performers start; what to do is theirs to decide, and results go up
    the hierarchy with report_up. It lives in its own project, "Taking up the
    role: <name>", so the CEO sees it on the project wall with its deliverables.
    """
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
    project_name = _PROJECT_NAME[_lang()].format(who=who)
    pid = create_named_project(project_name)
    iter_id = create_iteration(pid, project_name, "pending")
    pdir = get_project_dir(pid)
    ctx_id = f"{pid}/{iter_id}" if iter_id else pid
    note = render_mission(template, {
        "name": emp.get("name", ""), "nickname": who,
        "role": emp.get("role", ""), "department": emp.get("department", ""),
        "context": hire_context.strip(), "workspace": str(pdir),
    })
    note += f"\n\n[Project ID: {ctx_id}] [Project workspace: {pdir}]"

    tree = TaskTree(project_id=ctx_id, mode="simple")
    root = tree.create_root(employee_id=CEO_ID, description=project_name)
    root.node_type = NodeType.CEO_PROMPT
    root.set_status(TaskPhase.PROCESSING)
    node = tree.add_child(parent_id=root.id, employee_id=employee_id, description=note,
                          acceptance_criteria=[], title=project_name)
    node.project_id = ctx_id
    node.project_dir = str(pdir)
    _save_project_tree(pdir, tree)
    conv_svc = get_conversation_service()
    conv = await conv_svc.get_or_create_project_conversation(ctx_id, [CEO_ID, employee_id])
    await conv_svc.push_system_message(conv.id, f"Project created: {project_name}", source_employee="system")
    _add_to_project_team(pdir, CEO_ID)
    _add_to_project_team(pdir, employee_id)
    employee_manager.schedule_node(employee_id, node.id, str(Path(pdir) / TASK_TREE_FILENAME))
    employee_manager._schedule_next(employee_id)
    logger.info("[onboarding] arrival note sent to {} in project {}", employee_id, ctx_id)
    return {"status": "launched", "project_id": pid, "project_dir": str(pdir), "node_id": node.id}


def start_weekly(employee_id: str) -> dict:
    from onemancompany.core.automation import start_cron

    return start_cron(employee_id, WEEKLY_CRON, "7d", _WEEKLY_TASK[_lang()])


async def onboard(employee_id: str, hire_context: str = "", *, force: bool = False) -> dict:
    """Charter + mission + weekly round, as configured. Never raises."""
    settings = {**_settings(), "mission": True} if force else _settings()
    result: dict = {"employee_id": employee_id}
    try:
        result["charter"] = "company rule"  # injected for everyone, see vessel
        if settings["mission"]:
            result["mission"] = await launch_mission(employee_id, hire_context)
        if settings["weekly"]:
            result["weekly"] = start_weekly(employee_id).get("status", "ok")
    except Exception as exc:  # a hire must never fail because of onboarding
        logger.exception("[onboarding] failed for {}: {}", employee_id, exc)
        result["error"] = str(exc)
    return result

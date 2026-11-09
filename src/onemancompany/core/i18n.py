"""Company language setting — shared by the web UI and every AI employee.

The language is stored as ``language`` in the runtime ``config.yaml``.
An empty / missing value keeps the upstream behaviour (no language
directive: agents follow the language of each task).
"""

from __future__ import annotations

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "zh": "中文",
}

DEFAULT_LANGUAGE = "en"

# Name of each language written in English, used inside agent prompts.
_PROMPT_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "fr": "French",
    "zh": "Simplified Chinese",
}


def normalize_language(value: object) -> str:
    """Return a supported language code, or "" when the value is not supported."""
    if not isinstance(value, str):
        return ""
    code = value.strip().lower().split("-")[0].split("_")[0]
    return code if code in SUPPORTED_LANGUAGES else ""


def get_company_language() -> str:
    """Return the configured company language code, or "" when unset."""
    from onemancompany.core.config import load_app_config

    return normalize_language(load_app_config().get("language", ""))


def language_directive(lang: str | None = None) -> str:
    """Prompt section telling the agent which language to work in.

    Returns "" when no language is configured, so prompts stay unchanged.
    """
    code = normalize_language(lang) if lang is not None else get_company_language()
    if not code:
        return ""
    name = _PROMPT_LANGUAGE_NAMES[code]
    return (
        "## Working Language\n"
        f"The company's working language is {name}. Write every message, report, "
        f"meeting contribution, task title, summary and deliverable in {name}, "
        "even when instructions, SOPs or tool outputs are in another language. "
        "Keep code, identifiers, file names and quoted source material unchanged."
    )

"""Employees' browsers: real pages, with no secret ever reaching a model.

Each employee has a persistent Chromium profile (cookies, sessions) in
``company/browsers/<id>/``, a folder the agents' sessions cannot read. The
browser runs in OneManCompany's server, outside the agents' sandbox, in its
own thread and event loop (Playwright objects stay on that loop).

What an agent sees of a page is text (``snapshot``) with refs for what it can
act on. Password fields never show their value; vault values and anything
that looks like a key, a token, a card number or an IBAN are replaced by
``[secret]``. Values from the vault are typed by OneManCompany's code, and
only on the site the vault item belongs to (``site_of``). A value shown on a
page (a new API key) can be read straight into the vault or a company tool
without passing through the model.

The CEO watches and takes over any browser from the 🔑 panel: a live view
(screencast) with mouse and keyboard. That is how captchas, SMS codes,
payments, terms of service and the CEO's own sign-ins are done; agents ask
for it with ``add_ask``.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote, quote_plus, urlparse

from loguru import logger

VIEWPORT = {"width": 1280, "height": 800}
MAX_LINES = 450
MAX_CHARS = 16000
IDLE_CLOSE_SECONDS = 20 * 60
ACTION_TIMEOUT_MS = 15000
REF_RE = re.compile(r"[et]\d{1,5}")
SECRET = "[secret]"


class BrowserError(Exception):
    """Something the agent can act on (bad ref, wrong site, no browser)."""


# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------

def browsers_dir() -> Path:
    from onemancompany.core import config

    return config.COMPANY_DIR / "browsers"


def profile_dir(employee_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(employee_id or "")):
        raise BrowserError(f"bad employee id {employee_id!r}")
    return browsers_dir() / str(employee_id)


def _asks_path() -> Path:
    return browsers_dir() / "asks.json"


# ---------------------------------------------------------------------------
# Which site a page or a login belongs to
# ---------------------------------------------------------------------------

_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "gouv", "ac", "edu", "asso", "nom", "ltd", "plc"}


def site_of(url_or_host: str) -> str:
    """Registrable site of a URL or host: console.scaleway.com → scaleway.com, a.b.co.uk → b.co.uk."""
    text = str(url_or_host or "").strip()
    host = (urlparse(text).hostname if "://" in text else text.split("/")[0].split(":")[0]) or ""
    host = host.lower().strip(".")
    if not host or re.fullmatch(r"[\d.]+", host) or ":" in host or "." not in host:
        return host
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


_BAD_SCHEMES = re.compile(r"^\s*(javascript|data|file|about|chrome|blob|vbscript|view-source|ftp):", re.I)


def normalize_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        raise BrowserError("Give an address, e.g. https://console.scaleway.com")
    if _BAD_SCHEMES.match(url):
        raise BrowserError("Only http and https pages can be opened")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise BrowserError("Only http and https pages can be opened")
    return url


# ---------------------------------------------------------------------------
# Masking: nothing secret leaves the browser as text
# ---------------------------------------------------------------------------

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"),  # IBAN
]
_CARD = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
_GENERIC = re.compile(r"[A-Za-z0-9_\-+=]{32,}")
_vault_cache: dict = {"mtime": None, "values": []}
_vault_lock = threading.Lock()


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _looks_random(token: str) -> bool:
    return (any(c.isupper() for c in token) and any(c.islower() for c in token)
            and sum(c.isdigit() for c in token) >= 2)


def _vault_values() -> list[str]:
    """All values held in the vault (decrypted in this process only), longest first."""
    from onemancompany.core import vault

    path = vault.vault_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    with _vault_lock:
        if _vault_cache["mtime"] != mtime:
            try:
                _vault_cache["values"] = sorted({v for v in vault.secret_values() if len(v) >= 6}, key=len,
                                                reverse=True)
            except Exception as exc:  # never show a page unmasked because the vault could not be read
                logger.warning("[browser] vault unreadable for masking: {}", exc)
                raise BrowserError("The vault cannot be read right now; try again in a moment") from exc
            _vault_cache["mtime"] = mtime
        return list(_vault_cache["values"])


def mask(text: str, extra: list[str] | None = None) -> str:
    """Replace every secret-looking value (and every vault value, also URL-encoded) by [secret]."""
    for value in [*(extra or []), *_vault_values()]:
        for form in dict.fromkeys([value, quote(value, safe=""), quote_plus(value)]):
            if form and form in text:
                text = text.replace(form, SECRET)
    for pattern in _PATTERNS:
        text = pattern.sub(SECRET, text)
    text = _CARD.sub(lambda m: SECRET if _luhn(re.sub(r"\D", "", m.group())) else m.group(), text)
    return _GENERIC.sub(lambda m: SECRET if _looks_random(m.group()) else m.group(), text)


def pick_secret(text: str) -> str:
    """The value to keep from an element's text: the key-looking token if there is one, else all of it."""
    text = str(text or "").strip()
    for pattern in _PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group().strip()
    tokens = [t.strip(".,;:\"'()[]«»") for t in re.split(r"\s+", text)]
    keys = [t for t in tokens if len(t) >= 16 and re.search(r"\d", t) and re.search(r"[A-Za-z]", t)]
    return max(keys, key=len) if keys else text


# ---------------------------------------------------------------------------
# The page as text, with refs (runs inside the page)
# ---------------------------------------------------------------------------

SNAPSHOT_JS = r"""
(maxLines) => {
  const out = [];
  let n = 0;
  document.querySelectorAll('[data-omc-ref]').forEach(el => el.removeAttribute('data-omc-ref'));
  const clean = (t, max = 160) => (t || '').replace(/\s+/g, ' ').trim().slice(0, max);
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 && r.height <= 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.05;
  };
  const nameOf = (el) => {
    const aria = el.getAttribute('aria-label'); if (aria && clean(aria)) return clean(aria);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(id => (document.getElementById(id) || {}).innerText || '').join(' ');
      if (clean(t)) return clean(t);
    }
    if (el.labels && el.labels.length) {
      const t = Array.from(el.labels).map(l => l.innerText).join(' ');
      if (clean(t)) return clean(t);
    }
    if (el.placeholder) return clean(el.placeholder);
    if (el.title) return clean(el.title);
    if (el.alt) return clean(el.alt);
    const tag = el.tagName.toLowerCase();
    if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') {
      const t = clean(el.innerText || '', 100); if (t) return t;
    }
    if (tag === 'input' && ['submit', 'button', 'reset'].includes((el.type || '').toLowerCase())) return clean(el.value);
    return clean(el.getAttribute('name') || el.id || '', 60);
  };
  const HIDDEN_AUTOCOMPLETE = /cc-number|cc-csc|one-time-code|new-password|current-password/i;
  const SECRET_WORDS = /secret|token|api[ _-]?key|access[ _-]?key|cl[ée]s?\b|password|mot de passe|passphrase|private|priv[ée]e|credential|webhook|bearer/i;
  const hideTokens = (text) => text.replace(/[A-Za-z0-9_\-+\/=.:]{16,}/g,
    (m) => (/\d/.test(m) && /[A-Za-z]/.test(m) && !/^https?:/.test(m)) ? '[secret]' : m);
  const secretContext = (el) => {
    const parts = [el.getAttribute('aria-label') || '', el.getAttribute('name') || '', el.id || '',
                   el.getAttribute('placeholder') || ''];
    if (el.labels) parts.push(...Array.from(el.labels).map(l => l.innerText || ''));
    const prev = el.previousElementSibling;
    if (prev) parts.push((prev.innerText || '').slice(0, 120));
    if (el.parentElement) parts.push((el.parentElement.innerText || '').slice(0, 160));
    return SECRET_WORDS.test(parts.join(' '));
  };
  const INTERACTIVE = 'a[href],button,input:not([type=hidden]),select,textarea,summary,' +
    '[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],' +
    '[role=combobox],[role=switch],[role=textbox],[contenteditable=""],[contenteditable=true],[onclick]';
  const ref = (el, prefix) => { n += 1; const r = prefix + n; el.setAttribute('data-omc-ref', r); return r; };
  const describe = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    let role = el.getAttribute('role') || {a: 'link', button: 'button', select: 'select', textarea: 'textbox',
                                           summary: 'button'}[tag] || '';
    if (!role && tag === 'input') {
      role = ['checkbox', 'radio', 'file', 'range', 'color'].includes(type) ? type
        : ['submit', 'button', 'reset', 'image'].includes(type) ? 'button'
        : type === 'password' ? 'password' : 'textbox';
    }
    if (!role) role = el.isContentEditable ? 'textbox' : 'clickable';
    let line = `${role} "${nameOf(el)}"`;
    if (tag === 'input' || tag === 'textarea' || role === 'textbox') {
      if (['checkbox', 'radio'].includes(type)) line += el.checked ? ' [checked]' : ' [unchecked]';
      else if (!['submit', 'button', 'reset', 'image', 'file'].includes(type)) {
        const v = (tag === 'input' || tag === 'textarea') ? (el.value || '') : (el.innerText || '');
        const hide = type === 'password' || HIDDEN_AUTOCOMPLETE.test(el.getAttribute('autocomplete') || '');
        const shown = secretContext(el) ? hideTokens(clean(v, 200)) : clean(v, 200);
        line += v ? (hide ? ' = [hidden]' : ` = "${shown}"`) : ' = (empty)';
        if (el.required) line += ' (required)';
      }
    } else if (tag === 'select') {
      const opts = Array.from(el.options).slice(0, 40).map(o => (o.selected ? '*' : '') + clean(o.text, 40));
      line += ` options: ${opts.join(' | ')}`;
    } else if (tag === 'a') {
      const href = el.getAttribute('href') || '';
      if (href && !href.startsWith('javascript')) line += ` -> ${clean(href, 120)}`;
    }
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') line += ' (disabled)';
    if (el.getAttribute('aria-checked') === 'true' || el.getAttribute('aria-selected') === 'true') line += ' [selected]';
    return line;
  };
  const SKIP = new Set(['script', 'style', 'noscript', 'template', 'svg', 'head', 'meta', 'link', 'canvas']);
  const walk = (el) => {
    if (out.length >= maxLines || !(el instanceof Element)) return;
    const tag = el.tagName.toLowerCase();
    if (SKIP.has(tag)) return;
    if (tag !== 'body' && !visible(el)) return;
    if (tag === 'iframe') {
      let same = false; try { same = !!el.contentDocument; } catch (e) {}
      out.push(`[frame${same ? '' : ' from another site: if it is a captcha, a payment or a sign-in widget, ask the CEO'}] ` +
               clean(el.title || el.name || el.getAttribute('src') || '', 120));
      return;
    }
    if (el.matches(INTERACTIVE)) {
      out.push(`[${ref(el, 'e')}] ${describe(el)}`);
      if (['a', 'button', 'input', 'select', 'textarea', 'summary'].includes(tag) || el.isContentEditable) return;
    } else {
      let direct = '';
      for (const c of el.childNodes) if (c.nodeType === 3) direct += c.textContent;
      direct = clean(direct, 400);
      if (direct && (SECRET_WORDS.test(direct) || secretContext(el))) direct = hideTokens(direct);
      if (direct) {
        const heading = /^h[1-6]$/.test(tag) ? '#'.repeat(+tag[1]) + ' ' : '';
        out.push(`[${ref(el, 't')}] ${heading}${direct}`);
      }
    }
    for (const c of el.children) walk(c);
    if (el.shadowRoot) for (const c of el.shadowRoot.children) walk(c);
  };
  if (document.body) walk(document.body);
  return {url: location.href, title: document.title, lines: out, truncated: out.length >= maxLines};
}
"""

_FIELD_JS = """el => ({tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
  editable: !!(el.isContentEditable || ['input', 'textarea', 'select'].includes(el.tagName.toLowerCase()))})"""
_READ_JS = """el => {
  const v = (el.value !== undefined && el.value !== null && String(el.value) !== '') ? String(el.value) : '';
  return v || el.innerText || el.textContent || '';
}"""


# ---------------------------------------------------------------------------
# The browser thread
# ---------------------------------------------------------------------------

@dataclass
class _Session:
    employee_id: str
    context: object
    page: object
    lock: asyncio.Lock
    last_used: float = field(default_factory=time.monotonic)
    viewers: dict = field(default_factory=dict)  # viewer id -> sink(message)
    cdp: object = None


class BrowserService:
    """One Playwright, one profile per employee, driven from any event loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start = threading.Lock()
        self._pw = None
        self._sessions: dict[str, _Session] = {}

    # -- plumbing ----------------------------------------------------------

    def _ensure_thread(self) -> asyncio.AbstractEventLoop:
        with self._start:
            if self._loop is None:
                loop = asyncio.new_event_loop()

                def run() -> None:
                    asyncio.set_event_loop(loop)
                    loop.create_task(self._reaper())
                    loop.run_forever()

                self._thread = threading.Thread(target=run, name="omc-browser", daemon=True)
                self._thread.start()
                self._loop = loop
        return self._loop

    async def _call(self, fn, *args):
        loop = self._ensure_thread()
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(fn(*args), loop))

    async def _session(self, employee_id: str) -> _Session:
        if self._pw is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise BrowserError("The browser is not installed on this server (pip install playwright, then "
                                   "playwright install chromium)") from exc
            self._pw = await async_playwright().start()
        s = self._sessions.get(employee_id)
        if s is not None:
            s.last_used = time.monotonic()
            if not s.page.is_closed():
                return s
            s.page = s.context.pages[-1] if s.context.pages else await s.context.new_page()
            return s
        folder = profile_dir(employee_id)
        folder.mkdir(parents=True, exist_ok=True)
        from onemancompany.core.i18n import get_company_language

        try:
            context = await self._pw.chromium.launch_persistent_context(
                str(folder), headless=True, viewport=VIEWPORT, accept_downloads=False,
                locale="fr-FR" if get_company_language() == "fr" else "en-US")
        except Exception as exc:
            raise BrowserError(f"The browser could not start: {exc}") from exc
        page = context.pages[0] if context.pages else await context.new_page()
        s = _Session(employee_id, context, page, asyncio.Lock())
        self._sessions[employee_id] = s

        def on_page(new_page) -> None:  # a popup or a new tab becomes the current page
            s.page = new_page
            if s.viewers:
                asyncio.ensure_future(self._cast(s))

        context.on("page", on_page)
        context.on("close", lambda *_: self._sessions.pop(employee_id, None)
                   if self._sessions.get(employee_id) is s else None)
        logger.info("[browser] opened the browser of {}", employee_id)
        return s

    async def _reaper(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            for emp, s in list(self._sessions.items()):
                if not s.viewers and not s.lock.locked() and now - s.last_used > IDLE_CLOSE_SECONDS:
                    await self._close_impl(emp)

    @staticmethod
    async def _settle(page) -> None:
        for state, timeout in (("domcontentloaded", 10000), ("networkidle", 2500)):
            try:
                await page.wait_for_load_state(state, timeout=timeout)
            except Exception as exc:  # pages that never go idle are normal
                logger.debug("[browser] page not {} yet: {}", state, exc)

    @staticmethod
    def _locator(s: _Session, ref: str):
        ref = str(ref or "").strip().strip("[]")
        if not REF_RE.fullmatch(ref):
            raise BrowserError("Use a ref from the last snapshot, e.g. e12")
        return s.page.locator(f'[data-omc-ref="{ref}"]').first

    async def _found(self, s: _Session, ref: str):
        loc = self._locator(s, ref)
        if await loc.count() == 0:
            raise BrowserError(f"{ref} is no longer on the page: take a new snapshot (browser_snapshot)")
        return loc

    async def _snap(self, s: _Session) -> str:
        page = s.page
        try:
            data = await page.evaluate(SNAPSHOT_JS, MAX_LINES)
        except Exception as exc:
            data = {"url": page.url, "title": "", "lines": [f"(the page cannot be read yet: {exc})"]}
        pages = list(s.context.pages)
        head = [f"URL: {data.get('url', '')}", f"Title: {data.get('title', '')}"]
        if len(pages) > 1 and page in pages:
            head.append(f"Tabs: {len(pages)} (this is tab {pages.index(page) + 1}; browser_tabs to switch)")
        body = "\n".join(data.get("lines") or []) or "(nothing visible yet)"
        if data.get("truncated"):
            body += "\n… (page cut here: open a more specific page or scroll with browser_press('PageDown'))"
        return mask("\n".join(head) + "\n\n" + body)[:MAX_CHARS]

    # -- what agents do ----------------------------------------------------

    async def _open_impl(self, emp: str, url: str) -> str:
        s = await self._session(emp)
        async with s.lock:
            try:
                await s.page.goto(normalize_url(url), wait_until="domcontentloaded", timeout=30000)
            except BrowserError:
                raise
            except Exception as exc:
                raise BrowserError(f"The page did not open: {exc}") from exc
            await self._settle(s.page)
            return await self._snap(s)

    async def _snapshot_impl(self, emp: str) -> str:
        s = await self._session(emp)
        async with s.lock:
            return await self._snap(s)

    async def _click_impl(self, emp: str, ref: str) -> str:
        s = await self._session(emp)
        async with s.lock:
            loc = await self._found(s, ref)
            await loc.click(timeout=ACTION_TIMEOUT_MS)
            await asyncio.sleep(0.3)  # a new tab may open
            await self._settle(s.page)
            return await self._snap(s)

    async def _type_impl(self, emp: str, ref: str, text: str, submit: bool) -> str:
        s = await self._session(emp)
        async with s.lock:
            loc = await self._found(s, ref)
            info = await loc.evaluate(_FIELD_JS)
            if info.get("type") == "password":
                raise BrowserError("This is a password field: use browser_fill_secret (OneManCompany types the "
                                   "value from the vault; nobody sees it)")
            if not info.get("editable"):
                raise BrowserError(f"{ref} is not a field you can type in")
            await loc.fill(str(text), timeout=ACTION_TIMEOUT_MS)
            if submit:
                await loc.press("Enter")
                await self._settle(s.page)
            return await self._snap(s)

    async def _select_impl(self, emp: str, ref: str, option: str) -> str:
        s = await self._session(emp)
        async with s.lock:
            loc = await self._found(s, ref)
            try:
                await loc.select_option(label=str(option), timeout=ACTION_TIMEOUT_MS)
            except Exception:
                await loc.select_option(value=str(option), timeout=ACTION_TIMEOUT_MS)
            await self._settle(s.page)
            return await self._snap(s)

    async def _press_impl(self, emp: str, key: str) -> str:
        s = await self._session(emp)
        async with s.lock:
            await s.page.keyboard.press(str(key))
            await self._settle(s.page)
            return await self._snap(s)

    async def _back_impl(self, emp: str) -> str:
        s = await self._session(emp)
        async with s.lock:
            await s.page.go_back(wait_until="domcontentloaded", timeout=30000)
            await self._settle(s.page)
            return await self._snap(s)

    async def _tabs_impl(self, emp: str, switch_to: int) -> dict:
        s = await self._session(emp)
        async with s.lock:
            pages = list(s.context.pages)
            if switch_to > 0:
                if switch_to > len(pages):
                    raise BrowserError(f"There are {len(pages)} tabs")
                s.page = pages[switch_to - 1]
                await s.page.bring_to_front()
                if s.viewers:
                    await self._cast(s)
            tabs = []
            for i, p in enumerate(pages, 1):
                try:
                    title = await p.title()
                except Exception:
                    title = ""
                tabs.append({"tab": i, "url": mask(p.url), "title": mask(title), "current": p is s.page})
            return {"tabs": tabs, "snapshot": await self._snap(s) if switch_to > 0 else ""}

    async def _fill_impl(self, emp: str, ref: str, value: str, submit: bool, site: str) -> str:
        """Type a value nobody may see, only on ``site`` (the vault item's)."""
        s = await self._session(emp)
        async with s.lock:
            here = site_of(s.page.url)
            if site and here != site:
                raise BrowserError(f"This login is for {site}, and the page is on {here or 'no site'}: open the "
                                   f"sign-in page of {site} first")
            loc = await self._found(s, ref)
            info = await loc.evaluate(_FIELD_JS)
            if not info.get("editable"):
                raise BrowserError(f"{ref} is not a field you can type in")
            await loc.fill(value, timeout=ACTION_TIMEOUT_MS)
            if submit:
                await loc.press("Enter")
                await self._settle(s.page)
            return mask(await self._snap(s), [value])

    async def _read_impl(self, emp: str, ref: str) -> tuple[str, str]:
        """(raw text of the element, site of the page). For OneManCompany's code only, never for a model."""
        s = await self._session(emp)
        async with s.lock:
            loc = await self._found(s, ref)
            return str(await loc.evaluate(_READ_JS) or ""), site_of(s.page.url)

    async def _url_impl(self, emp: str) -> str:
        s = self._sessions.get(emp)
        return s.page.url if s is not None and not s.page.is_closed() else ""

    async def _close_impl(self, emp: str) -> None:
        s = self._sessions.pop(emp, None)
        if s is None:
            return
        for sink in list(s.viewers.values()):
            sink({"type": "closed"})
        try:
            await s.context.close()
        except Exception as exc:
            logger.debug("[browser] close {}: {}", emp, exc)
        logger.info("[browser] closed the browser of {}", emp)

    async def _list_impl(self) -> list[dict]:
        out = []
        for emp, s in self._sessions.items():
            try:
                title = await s.page.title()
            except Exception:
                title = ""
            out.append({"employee_id": emp, "url": s.page.url, "title": title, "tabs": len(s.context.pages),
                        "watching": len(s.viewers)})
        return out

    # -- the CEO's live view -------------------------------------------------

    async def _cast(self, s: _Session) -> None:
        old, s.cdp = s.cdp, None
        if old is not None:
            try:
                await old.detach()
            except Exception as exc:  # the page it watched is gone
                logger.debug("[browser] old live view session: {}", exc)
        if not s.viewers:
            return
        cdp = await s.context.new_cdp_session(s.page)

        def on_frame(params: dict) -> None:
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": params.get("sessionId")}))
            meta = params.get("metadata") or {}
            frame = {"type": "frame", "data": params.get("data", ""), "w": meta.get("deviceWidth"),
                     "h": meta.get("deviceHeight"), "url": s.page.url}
            for sink in list(s.viewers.values()):
                sink(frame)

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 70, "maxWidth": VIEWPORT["width"],
                                                "maxHeight": VIEWPORT["height"], "everyNthFrame": 1})
        s.cdp = cdp

    async def _watch_impl(self, emp: str, viewer: str, sink: Callable[[dict], None]) -> None:
        s = await self._session(emp)
        s.viewers[viewer] = sink
        await self._cast(s)

    async def _unwatch_impl(self, emp: str, viewer: str) -> None:
        s = self._sessions.get(emp)
        if s is None:
            return
        s.viewers.pop(viewer, None)
        s.last_used = time.monotonic()
        if not s.viewers and s.cdp is not None:
            try:
                await s.cdp.send("Page.stopScreencast")
                await s.cdp.detach()
            except Exception as exc:  # the page it watched is gone
                logger.debug("[browser] stop live view: {}", exc)
            s.cdp = None

    async def _input_impl(self, emp: str, msg: dict) -> None:
        """Mouse and keyboard from the CEO's live view (coordinates in page pixels)."""
        s = await self._session(emp)
        s.last_used = time.monotonic()
        page, kind = s.page, msg.get("type")
        if kind == "mouse":
            x, y = float(msg.get("x", 0)), float(msg.get("y", 0))
            button = msg.get("button") if msg.get("button") in ("left", "right", "middle") else "left"
            event = msg.get("event")
            if event == "move":
                await page.mouse.move(x, y)
            elif event == "down":
                await page.mouse.move(x, y)
                await page.mouse.down(button=button)
            elif event == "up":
                await page.mouse.up(button=button)
            elif event == "wheel":
                await page.mouse.move(x, y)
                await page.mouse.wheel(float(msg.get("dx", 0)), float(msg.get("dy", 0)))
        elif kind == "key":
            key = str(msg.get("key") or "")
            if key and msg.get("event") == "down":
                await page.keyboard.down(key)
            elif key and msg.get("event") == "up":
                await page.keyboard.up(key)
        elif kind == "text":
            await page.keyboard.insert_text(str(msg.get("text") or ""))
        elif kind == "navigate":
            await page.goto(normalize_url(str(msg.get("url") or "")), wait_until="domcontentloaded", timeout=30000)
        elif kind == "back":
            await page.go_back(timeout=30000)
        elif kind == "reload":
            await page.reload(timeout=30000)

    async def _ceo_fill_impl(self, emp: str, value: str) -> None:
        """The CEO fills the focused field from the vault (no site check: the CEO sees the page)."""
        s = await self._session(emp)
        await s.page.keyboard.insert_text(value)

    # -- public API (any event loop) ------------------------------------------

    async def open(self, emp: str, url: str) -> str:
        return await self._call(self._open_impl, emp, url)

    async def snapshot(self, emp: str) -> str:
        return await self._call(self._snapshot_impl, emp)

    async def click(self, emp: str, ref: str) -> str:
        return await self._call(self._click_impl, emp, ref)

    async def type_text(self, emp: str, ref: str, text: str, submit: bool = False) -> str:
        return await self._call(self._type_impl, emp, ref, text, submit)

    async def select(self, emp: str, ref: str, option: str) -> str:
        return await self._call(self._select_impl, emp, ref, option)

    async def press(self, emp: str, key: str) -> str:
        return await self._call(self._press_impl, emp, key)

    async def back(self, emp: str) -> str:
        return await self._call(self._back_impl, emp)

    async def tabs(self, emp: str, switch_to: int = 0) -> dict:
        return await self._call(self._tabs_impl, emp, int(switch_to or 0))

    async def fill_secret(self, emp: str, ref: str, value: str, *, site: str, submit: bool = False) -> str:
        return await self._call(self._fill_impl, emp, ref, value, submit, site)

    async def read_raw(self, emp: str, ref: str) -> tuple[str, str]:
        return await self._call(self._read_impl, emp, ref)

    async def current_url(self, emp: str) -> str:
        return await self._call(self._url_impl, emp)

    async def close(self, emp: str) -> None:
        await self._call(self._close_impl, emp)

    async def list_open(self) -> list[dict]:
        if self._loop is None:
            return []
        return await self._call(self._list_impl)

    async def watch(self, emp: str, viewer: str, sink: Callable[[dict], None]) -> None:
        await self._call(self._watch_impl, emp, viewer, sink)

    async def unwatch(self, emp: str, viewer: str) -> None:
        if self._loop is not None:
            await self._call(self._unwatch_impl, emp, viewer)

    async def send_input(self, emp: str, msg: dict) -> None:
        await self._call(self._input_impl, emp, msg)

    async def ceo_fill(self, emp: str, value: str) -> None:
        await self._call(self._ceo_fill_impl, emp, value)


browser_service = BrowserService()


# ---------------------------------------------------------------------------
# What the CEO is asked to do in a browser
# ---------------------------------------------------------------------------

_asks_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_asks() -> list[dict]:
    try:
        return json.loads(_asks_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        logger.warning("[browser] asks unreadable: {}", exc)
        return []


def _save_asks(asks: list[dict]) -> None:
    path = _asks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asks[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def add_ask(employee_id: str, what: str, url: str = "") -> dict:
    what = " ".join(str(what or "").split())[:500]
    if not what:
        raise BrowserError("Say what the CEO must do, e.g. \"Résoudre le captcha de la page d'inscription OVH\"")
    ask = {"id": uuid.uuid4().hex[:10], "employee_id": str(employee_id), "what": what, "url": mask(str(url or "")),
           "status": "open", "at": _now(), "done_at": "", "note": ""}
    with _asks_lock:
        asks = _load_asks()
        asks.append(ask)
        _save_asks(asks)
    return ask


def open_asks() -> list[dict]:
    with _asks_lock:
        return [a for a in _load_asks() if a.get("status") == "open"]


def close_ask(ask_id: str, note: str = "") -> dict:
    with _asks_lock:
        asks = _load_asks()
        for ask in asks:
            if ask.get("id") == ask_id:
                if ask.get("status") != "open":
                    raise BrowserError("This request is already closed")
                ask.update(status="done", done_at=_now(), note=" ".join(str(note or "").split())[:500])
                _save_asks(asks)
                return ask
    raise BrowserError(f"No browser request {ask_id}")

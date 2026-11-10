"""Employees' browsers: pages as text without secrets, vault values typed only on their own site."""
from __future__ import annotations

import asyncio
import http.server
import re
import socketserver
import threading
import time

import pytest

from onemancompany.core import browser
from onemancompany.core import config as config_mod

KEY = "sk-AbCdEfGhIjKlMnOp1234"
SECRET = "Tr0ub4dor&3-xyz!"


def test_which_site():
    assert browser.site_of("https://console.scaleway.com/login") == "scaleway.com"
    assert browser.site_of("www.ovh.co.uk") == "ovh.co.uk"
    assert browser.site_of("https://compte.ovh.com.au/x") == "ovh.com.au"
    assert browser.site_of("http://127.0.0.1:8123/x") == "127.0.0.1"
    assert browser.site_of("localhost") == "localhost"
    assert browser.site_of("") == ""


def test_only_web_pages_open():
    assert browser.normalize_url("ovh.com") == "https://ovh.com"
    assert browser.normalize_url("http://localhost:8080/a") == "http://localhost:8080/a"
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x", "chrome://settings", ""):
        with pytest.raises(browser.BrowserError):
            browser.normalize_url(bad)


def test_onemancompany_and_the_local_network_are_closed(monkeypatch):
    monkeypatch.setenv("OMC_CONTROL_URL", "http://omc.internal:8000")
    for url in ("http://localhost:8000/api/vault", "http://127.0.0.1:5678", "http://[::1]/", "http://0.0.0.0:8000",
                "http://192.168.1.1/admin", "http://10.0.0.5", "http://169.254.169.254/latest/meta-data",
                "http://nas.local/", "http://omc.internal:8000/"):
        assert browser.is_private(url), url
    for url in ("https://console.scaleway.com", "https://8.8.8.8/", "https://www.ovh.com/manager"):
        assert not browser.is_private(url), url


@pytest.mark.asyncio
async def test_a_page_of_this_machine_does_not_open(chromium, site, tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    monkeypatch.setattr(browser, "_vault_values", lambda: [])
    svc = browser.BrowserService()
    try:
        with pytest.raises(browser.BrowserError, match="closed to employees' browsers"):
            await svc.open("00009", f"{site}/login")
        with pytest.raises(browser.BrowserError):
            await svc.send_input("00009", {"type": "navigate", "url": "http://localhost:8000/"})
    finally:
        await svc.close("00009")


def test_masking_hides_secrets_and_keeps_ids(monkeypatch):
    monkeypatch.setattr(browser, "_vault_values", lambda: [SECRET])
    text = (f"pass {SECRET} encoded Tr0ub4dor%263-xyz%21 key sk-live_AbCdEfGh1234567890XyZ "
            "token ghp_ABCDEFGHIJKLMNOPQRSTuvwxyz123456 id 3f2c1e9a-8b7d-4c6e-9f0a-1b2c3d4e5f60 "
            "hash 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 card 4242 4242 4242 4242 "
            "order 1234567890123 iban FR76 3000 6000 0112 3456 7890 189 random Zx9QwErTyUiOp1AsDfGhJkL2ZxCvBnM34 "
            "bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ "
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
    out = browser.mask(text)
    for leaked in (SECRET, "Tr0ub4dor%26", "sk-live_", "ghp_ABC", "4242 4242", "FR76 3000", "Zx9QwErTy", "eyJhbGci",
                   "AAHdqTcv"):
        assert leaked not in out, leaked
    assert "3f2c1e9a-8b7d-4c6e-9f0a-1b2c3d4e5f60" in out  # an id, not a secret
    assert "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08" in out  # a hash
    assert "1234567890123" in out  # not a card number


def test_the_value_to_keep_from_a_text():
    assert browser.pick_secret(f"Votre clé : {KEY} (copiez-la)") == KEY
    assert browser.pick_secret("Token: Zx9QwErTyUiOp1AsDfGh. Keep it safe") == "Zx9QwErTyUiOp1AsDfGh"
    assert browser.pick_secret("  plain-value  ") == "plain-value"


def test_what_the_ceo_is_asked_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    monkeypatch.setattr(browser, "_vault_values", lambda: [])
    ask = browser.add_ask("00009", "Résoudre le captcha", "https://ovh.com/signup?t=Zx9QwErTyUiOp1AsDfGhJkL2ZxCvBnM34")
    assert "[secret]" in ask["url"] and ask["status"] == "open"
    assert [a["id"] for a in browser.open_asks()] == [ask["id"]]
    done = browser.close_ask(ask["id"], "fait")
    assert done["status"] == "done" and done["note"] == "fait" and browser.open_asks() == []
    with pytest.raises(browser.BrowserError):
        browser.close_ask(ask["id"])
    with pytest.raises(browser.BrowserError):
        browser.add_ask("00009", "  ")
    with pytest.raises(browser.BrowserError):
        browser.profile_dir("../00001")


# ---------------------------------------------------------------------------
# A real Chromium on a local site
# ---------------------------------------------------------------------------

PAGES = {
    "/login": f"""<!doctype html><html lang="fr"><head><title>Connexion</title></head><body>
      <h1>Connexion</h1>
      <form action="/done" method="get">
        <label for="email">E-mail</label><input id="email" name="email" type="email">
        <label for="pwd">Mot de passe</label><input id="pwd" name="pwd" type="password">
        <button type="submit">Se connecter</button>
      </form>
      <p>Votre clé : <code>{KEY}</code></p>
      <p>Project ID: 11111111-2222-4333-8444-555555555555</p>
      <div><span>Secret key</span> <code>3f2c1e9a-8b7d-4c6e-9f0a-1b2c3d4e5f60</code></div>
      <a href="/other" target="_blank">Autre onglet</a>
      <div style="display:none">caché</div>
    </body></html>""",
    "/done": "<!doctype html><html><head><title>Accueil</title></head><body><h2>Bienvenue</h2></body></html>",
    "/other": "<!doctype html><html><head><title>Autre</title></head><body><p>Page de l'autre onglet</p></body></html>",
}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGES.get(self.path.split("?")[0], "<html><body>404</body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def chromium():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright is not installed")
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:
        pytest.skip(f"Chromium cannot start here: {exc}")


@pytest.mark.asyncio
async def test_a_real_page_without_a_secret(chromium, site, tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    monkeypatch.setattr(browser, "_vault_values", lambda: [SECRET])
    svc = browser.BrowserService(block_private=False)  # the test site is on this machine
    try:
        page = await svc.open("00009", f"{site}/login")
        assert "Title: Connexion" in page and "# Connexion" in page
        assert KEY not in page and "[secret]" in page and "caché" not in page
        assert "3f2c1e9a-8b7d" not in page and "11111111-2222-4333-8444-555555555555" in page
        email = re.search(r'\[(e\d+)\] textbox "E-mail"', page).group(1)
        pwd = re.search(r'\[(e\d+)\] password "Mot de passe" = \(empty\)', page).group(1)
        page = await svc.type_text("00009", email, "lea@photonet.app")
        assert '= "lea@photonet.app"' in page
        with pytest.raises(browser.BrowserError, match="password field"):
            await svc.type_text("00009", pwd, "a guess")
        with pytest.raises(browser.BrowserError, match="sign-in page of scaleway.com"):
            await svc.fill_secret("00009", pwd, SECRET, site="scaleway.com")
        page = await svc.fill_secret("00009", pwd, SECRET, site="127.0.0.1")
        assert f'password "Mot de passe" = [hidden]' in page and SECRET not in page
        with pytest.raises(browser.BrowserError, match="no longer on the page|Use a ref"):
            await svc.click("00009", "e999")
        key_ref = re.search(r"\[(t\d+)\] " + re.escape("[secret]"), page).group(1)
        raw, where = await svc.read_raw("00009", key_ref)  # OneManCompany's code only
        assert browser.pick_secret(raw) == KEY and where == "127.0.0.1"

        submit = re.search(r'\[(e\d+)\] button "Se connecter"', page).group(1)
        page = await svc.click("00009", submit)
        assert "Bienvenue" in page and SECRET not in page and "Tr0ub4dor%26" not in page  # the GET form put it in the URL

        page = await svc.back("00009")
        link = re.search(r'\[(e\d+)\] link "Autre onglet"', page).group(1)
        page = await svc.click("00009", link)
        assert "Page de l'autre onglet" in page and "Tabs: 2 (this is tab 2" in page
        tabs = await svc.tabs("00009", 1)
        assert [t["current"] for t in tabs["tabs"]] == [True, False] and "Connexion" in tabs["snapshot"]

        frames = []
        await svc.watch("00009", "ceo", frames.append)
        await svc.send_input("00009", {"type": "navigate", "url": f"{site}/done"})
        deadline = time.monotonic() + 10
        while not frames and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        assert frames and frames[-1]["type"] == "frame" and frames[-1]["data"]
        await svc.unwatch("00009", "ceo")
        assert [b["employee_id"] for b in await svc.list_open()] == ["00009"]
        assert (tmp_path / "browsers" / "00009").is_dir()  # the profile keeps sessions
    finally:
        await svc.close("00009")
    assert await svc.list_open() == []

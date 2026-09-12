from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import webbrowser
from urllib.parse import parse_qs, urlparse

from digikey_list_mcp.config import Settings
from digikey_list_mcp.credentials import default_credential_store
from digikey_list_mcp.digikey.auth import DigiKeyOAuth
from digikey_list_mcp.errors import DigiKeyListError
from digikey_list_mcp.runtime import Runtime
from digikey_list_mcp.server import create_server


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default or ""


def configure(_: argparse.Namespace) -> int:
    current = Settings.load()
    store = default_credential_store()
    print("DigiKey credentials will be stored in Keychain (or a user-only fallback file).")
    client_id = _prompt("DigiKey client ID", store.get("client_id"))
    client_secret = getpass.getpass("DigiKey client secret [leave blank to keep current]: ").strip()
    redirect_uri = _prompt("Registered OAuth callback URI", current.redirect_uri)
    account_id = _prompt("DigiKey account ID (optional)", current.account_id)
    sandbox_text = _prompt("Use sandbox? yes/no", "yes" if current.sandbox else "no")
    settings = current.model_copy(
        update={
            "redirect_uri": redirect_uri,
            "account_id": account_id or None,
            "sandbox": sandbox_text.casefold() in {"y", "yes", "true", "1"},
        }
    )
    settings.save()
    if client_id:
        store.set("client_id", client_id)
    if client_secret:
        store.set("client_secret", client_secret)
    print(f"Saved non-secret settings to {settings.config_path()}")
    return 0


async def _auth_login(no_browser: bool) -> int:
    settings = Settings.load()
    store = default_credential_store()
    oauth = DigiKeyOAuth(settings, store)
    request = oauth.begin_authorization()
    print("Open this DigiKey authorization URL:\n")
    print(request.url)
    if not no_browser:
        webbrowser.open(request.url)
    print("\nAfter approval, paste the full redirected URL here.")
    redirected = (await asyncio.to_thread(input, "Redirected URL: ")).strip()
    values = parse_qs(urlparse(redirected).query)
    if values.get("state", [None])[0] != request.state:
        raise DigiKeyListError("OAuth state did not match; login was not saved.")
    if "error" in values:
        raise DigiKeyListError(f"DigiKey denied authorization: {values['error'][0]}")
    code = values.get("code", [None])[0]
    if not code:
        raise DigiKeyListError("The redirected URL did not contain an authorization code.")
    await oauth.exchange_code(code)
    print("DigiKey login saved securely.")
    return 0


def auth_status(_: argparse.Namespace) -> int:
    oauth = DigiKeyOAuth(Settings.load(), default_credential_store())
    tokens = oauth.load_tokens()
    if not tokens:
        print("Not logged in. Run: digikey-list-mcp auth login")
        return 1
    state = "valid" if tokens.access_is_valid() else "refresh required"
    refresh = "valid" if tokens.refresh_is_valid() else "expired"
    print(f"DigiKey access token: {state}; refresh token: {refresh}")
    return 0


async def _doctor(live: bool) -> int:
    settings = Settings.load()
    store = default_credential_store()
    checks: dict[str, object] = {
        "config_file": settings.config_path().exists(),
        "client_id": bool(store.get("client_id")),
        "client_secret": bool(store.get("client_secret")),
        "oauth_tokens": bool(store.get("oauth_tokens")),
        "sandbox": settings.sandbox,
        "api_base_url": settings.api_base_url,
    }
    if live:
        try:
            async with Runtime(settings, store).services() as services:
                lists = await services.mylists.list_lists(limit=1)
            checks["live_mylists"] = True
            checks["sample_list_count"] = len(lists)
        except DigiKeyListError as exc:
            checks["live_mylists"] = False
            checks["live_error"] = str(exc)
    print(json.dumps(checks, indent=2))
    required = bool(checks["client_id"] and checks["client_secret"] and checks["oauth_tokens"])
    return 0 if required and (not live or checks.get("live_mylists") is True) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digikey-list-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    configure_parser = subparsers.add_parser("configure", help="store DigiKey app settings")
    configure_parser.set_defaults(handler=configure)

    auth_parser = subparsers.add_parser("auth", help="manage DigiKey OAuth")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)
    login_parser = auth_subparsers.add_parser("login")
    login_parser.add_argument("--no-browser", action="store_true")
    login_parser.set_defaults(handler=lambda args: asyncio.run(_auth_login(args.no_browser)))
    status_parser = auth_subparsers.add_parser("status")
    status_parser.set_defaults(handler=auth_status)

    doctor_parser = subparsers.add_parser("doctor", help="check configuration and connectivity")
    doctor_parser.add_argument("--live", action="store_true")
    doctor_parser.set_defaults(handler=lambda args: asyncio.run(_doctor(args.live)))

    serve_parser = subparsers.add_parser("serve", help="run the MCP server")
    serve_parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve_parser.set_defaults(
        handler=lambda args: create_server().run(transport=args.transport) or 0
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    try:
        args = build_parser().parse_args(argv)
        code = args.handler(args)
    except (DigiKeyListError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        code = 2
    raise SystemExit(code)

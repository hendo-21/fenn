"""``fenn auth`` — manage credentials for the Fenn remote service."""

from __future__ import annotations

import argparse
import getpass
import sys

from colorama import Fore, Style

from fenn.remote.credentials import (
    DEFAULT_PROFILE,
    delete_profile,
    load_credentials,
    mask_key,
    write_credentials,
)
from fenn.remote.exceptions import RemoteError


def execute(args: argparse.Namespace) -> None:
    sub = getattr(args, "auth_command", None)
    if sub is None:
        print(
            f"{Fore.RED}Missing auth subcommand. Try: "
            f"{Fore.LIGHTYELLOW_EX}fenn auth login{Style.RESET_ALL}",
            file=sys.stderr,
        )
        sys.exit(1)

    if sub == "login":
        _login(args)
    elif sub == "status":
        _status(args)
    elif sub == "logout":
        _logout(args)
    else:
        print(f"{Fore.RED}Unknown auth subcommand: {sub}{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(1)


def _login(args: argparse.Namespace) -> None:
    profile = args.profile or DEFAULT_PROFILE
    host = args.host

    api_key = args.api_key
    if not api_key:
        if sys.stdin.isatty():
            api_key = getpass.getpass(
                f"Paste Fenn API key for profile [{profile}]: "
            ).strip()
        else:
            api_key = sys.stdin.readline().strip()

    if not api_key:
        print(f"{Fore.RED}No API key provided.{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(1)

    path = write_credentials(api_key, profile=profile, host=host)
    print(
        f"{Fore.GREEN}Saved credentials to "
        f"{Fore.LIGHTYELLOW_EX}{path}{Fore.GREEN} (profile: {profile}).{Style.RESET_ALL}"
    )


def _status(args: argparse.Namespace) -> None:
    profile = args.profile or DEFAULT_PROFILE
    creds = load_credentials(profile)
    if creds is None:
        print(
            f"{Fore.YELLOW}No saved credentials for profile {profile!r}. "
            f"Run {Fore.LIGHTYELLOW_EX}fenn auth login{Fore.YELLOW} to add one.{Style.RESET_ALL}"
        )
        sys.exit(1)

    print(f"{Fore.CYAN}profile : {Fore.LIGHTYELLOW_EX}{creds.profile}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}api_key : {Fore.LIGHTYELLOW_EX}{mask_key(creds.api_key)}{Style.RESET_ALL}")
    if creds.host:
        print(f"{Fore.CYAN}host    : {Fore.LIGHTYELLOW_EX}{creds.host}{Style.RESET_ALL}")

    if creds.host:
        try:
            from fenn.remote.client import RemoteClient

            with RemoteClient(creds.host, creds.api_key) as client:
                me = client.me()
            credits_remaining = me.get("credits")
            plan = me.get("plan")
            print(
                f"{Fore.GREEN}credits : {Fore.LIGHTYELLOW_EX}{credits_remaining}"
                f"{Fore.GREEN}  plan: {plan}{Style.RESET_ALL}"
            )
        except RemoteError as exc:
            print(
                f"{Fore.RED}Could not reach host: {exc}{Style.RESET_ALL}",
                file=sys.stderr,
            )


def _logout(args: argparse.Namespace) -> None:
    profile = args.profile or DEFAULT_PROFILE
    if delete_profile(profile):
        print(
            f"{Fore.GREEN}Removed credentials for profile "
            f"{Fore.LIGHTYELLOW_EX}{profile}{Style.RESET_ALL}"
        )
    else:
        print(
            f"{Fore.YELLOW}No credentials found for profile {profile!r}.{Style.RESET_ALL}"
        )

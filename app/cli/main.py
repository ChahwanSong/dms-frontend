from __future__ import annotations

import argparse
import getpass
import importlib.metadata
import os
import sys
from typing import Protocol

from .client import DmsApiClient, DmsApiError
from .config import CLISettings
from .shell import AdminShell, UserShell, resolve_cli_user_id

CLI_ENV_EPILOG = (
    "Environment: DMS_FRONTEND_URL, DMS_FRONTEND_API_PREFIX, "
    "DMS_CLI_CA_BUNDLE, DMS_CLI_INSECURE, DMS_CLI_TIMEOUT_SECONDS"
)


class InteractiveShell(Protocol):
    intro: str

    def execute_command(self, command: str) -> int:
        ...

    def cmdloop(self, intro: str | None = None) -> None:
        ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dms",
        description="Interactive CLI for dms-frontend user/admin APIs.",
        epilog=CLI_ENV_EPILOG,
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("user", "admin"),
        default="user",
        help="omit for the user shell, or choose admin explicitly",
    )
    parser.add_argument(
        "-c",
        "--command",
        help="execute a single shell command and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {resolve_version()}",
    )
    return parser


def resolve_version() -> str:
    try:
        return importlib.metadata.version("dms-frontend")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def is_root_user() -> bool:
    return os.geteuid() == 0


def prompt_operator_token() -> str:
    return getpass.getpass("Operator token: ")


def enable_tab_completion() -> None:
    try:
        import readline
    except ImportError:
        return
    readline.parse_and_bind("tab: complete")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = CLISettings()
    enable_tab_completion()

    with DmsApiClient(settings) as client:
        if args.mode == "admin":
            if not is_root_user():
                print("Admin mode requires the root account (uid 0).", file=sys.stderr)
                return 1
            token = prompt_operator_token()
            client.set_operator_token(token)
            try:
                client.verify_operator_token()
            except DmsApiError as exc:
                print(f"Admin authentication failed: {exc}", file=sys.stderr)
                return 1
            shell = AdminShell(client=client, settings=settings)
            return run_shell(shell, args.command)

        shell = UserShell(client=client, settings=settings, user_id=resolve_cli_user_id())
        return run_shell(shell, args.command)


def run_shell(shell: InteractiveShell, command: str | None) -> int:
    if command:
        return shell.execute_command(command)

    try:
        shell.cmdloop(shell.intro)
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    return 0


def run() -> None:
    raise SystemExit(main())

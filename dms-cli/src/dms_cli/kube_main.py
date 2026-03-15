from __future__ import annotations

import argparse
from typing import Optional

from .config import CLISettings
from .main import CLI_ENV_EPILOG, enable_tab_completion, resolve_version, run_shell
from .shell import KubeShell


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dms-kube",
        description="Interactive CLI for DMS Kubernetes workflows.",
        epilog=CLI_ENV_EPILOG,
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


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    settings = CLISettings()
    enable_tab_completion()
    return run_shell(KubeShell(settings=settings), args.command)


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()

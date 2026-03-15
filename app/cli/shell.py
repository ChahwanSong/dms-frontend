from __future__ import annotations

import cmd
import json
import os
import pwd
import shlex
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from .client import DmsApiError
from .config import CLISettings

KNOWN_SERVICES = ("sync", "hotcold", "rm", "cp", "chmod")
SERVICE_PARAMETER_HINTS: dict[str, tuple[str, ...]] = {
    "sync": ("src=", "dst=", "options="),
    "cp": ("src=", "dst=", "options="),
    "rm": ("path=", "options="),
    "hotcold": ("path=", "options="),
    "chmod": ("path=", "mode=", "options="),
}


@dataclass(frozen=True)
class CommandHelp:
    summary: str
    usage: tuple[str, ...]
    api_routes: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def resolve_cli_user_id() -> str:
    sudo_user = os.getenv("SUDO_USER")
    if sudo_user:
        return sudo_user
    return pwd.getpwuid(os.getuid()).pw_name


class BaseShell(cmd.Cmd):
    def __init__(
        self,
        *,
        settings: CLISettings,
        client: Any | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        super().__init__(completekey="tab", stdout=stdout)
        self.settings = settings
        self.client = client
        self.stderr = stderr or sys.stderr
        self.last_status = 0
        self.command_help: dict[str, CommandHelp] = self._base_help_topics()
        self.command_help.update(self._shell_help_topics())
        self.prompt = "dms> "
        self.intro = ""

    def execute_command(self, line: str) -> int:
        self.last_status = 0
        self.onecmd(line)
        return self.last_status

    def get_completion_suggestions(self, line: str) -> list[str]:
        parsed = self._parse_completion_request(line)
        if parsed is None:
            return sorted(dict.fromkeys(self.completenames(line)))

        command, text, begidx, endidx = parsed
        completer = getattr(self, f"complete_{command}", None)
        if completer is None:
            return []
        return sorted(dict.fromkeys(completer(text, line, begidx, endidx)))

    def emptyline(self) -> bool:
        return False

    def default(self, line: str) -> None:
        self._error(f"Unknown command: {line}. Use 'help' to list supported commands.")

    def do_exit(self, _: str) -> bool:
        self.last_status = 0
        return True

    def do_quit(self, _: str) -> bool:
        self.last_status = 0
        return True

    def do_EOF(self, _: str) -> bool:
        self._write("")
        self.last_status = 0
        return True

    def do_help(self, arg: str) -> None:
        topic = arg.strip()
        if not topic:
            self._print_general_help()
            self.last_status = 0
            return

        if topic == "env":
            self._print_env_help()
            self.last_status = 0
            return

        command_help = self.command_help.get(topic)
        if command_help is None:
            self._error(f"Unknown help topic: {topic}")
            return

        self._print_command_help(topic, command_help)
        self.last_status = 0

    def complete_help(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del line, begidx, endidx
        return self._match(self._help_topics(), text)

    def do_env(self, _: str) -> None:
        self._print_env_help()
        self.last_status = 0

    def do_health(self, _: str) -> None:
        if self.client is None:
            self._error("Health checks are not available in this shell.")
            return
        self._emit_api_result(lambda: self.client.health())

    def _shell_help_topics(self) -> dict[str, CommandHelp]:
        return {}

    def _base_help_topics(self) -> dict[str, CommandHelp]:
        help_topics = {
            "env": CommandHelp(
                summary="Show the frontend address, TLS settings, and timeout values.",
                usage=("env", "help env"),
                notes=(
                    "Set DMS_FRONTEND_URL to the HTTPS address exposed by dms-frontend.",
                    "Use DMS_CLI_CA_BUNDLE when the cluster uses a private CA certificate.",
                    "Use DMS_CLI_INSECURE=true only for local testing with self-signed certificates.",
                ),
            ),
            "exit": CommandHelp(summary="Exit the current shell.", usage=("exit", "quit")),
            "quit": CommandHelp(summary="Exit the current shell.", usage=("quit", "exit")),
        }
        if self.client is not None:
            help_topics["health"] = CommandHelp(
                summary="Check frontend and Redis health through /healthz.",
                usage=("health",),
                api_routes=("GET /healthz",),
                examples=("health",),
            )
        return help_topics

    def _print_general_help(self) -> None:
        self._write("Available commands:")
        for name in self._ordered_topics():
            self._write(f"  {name:<8} {self.command_help[name].summary}")
        self._write("")
        self._write("Use 'help <command>' for detailed usage and examples.")

    def _print_command_help(self, name: str, topic: CommandHelp) -> None:
        self._write(f"{name}: {topic.summary}")
        self._write("")
        self._write("Usage:")
        for usage in topic.usage:
            self._write(f"  {usage}")
        if topic.api_routes:
            self._write("")
            self._write("API routes:")
            for route in topic.api_routes:
                self._write(f"  {route}")
        if topic.examples:
            self._write("")
            self._write("Examples:")
            for example in topic.examples:
                self._write(f"  {example}")
        if topic.notes:
            self._write("")
            self._write("Notes:")
            for note in topic.notes:
                self._write(f"  {note}")

    def _print_env_help(self) -> None:
        self._write("Environment:")
        for name, value, description in self.settings.describe_environment():
            self._write(f"  {name}={value}")
            self._write(f"    {description}")
        for extra in self._environment_notes():
            self._write(f"  {extra}")

    def _environment_notes(self) -> tuple[str, ...]:
        return ()

    def _emit_api_result(self, request: Any) -> None:
        try:
            payload = request()
        except DmsApiError as exc:
            self._error(str(exc))
            return
        self._write_json(payload)
        self.last_status = 0

    def _parse_key_value_arguments(self, tokens: list[str]) -> dict[str, str] | None:
        parameters: dict[str, str] = {}
        for token in tokens:
            if "=" not in token:
                self._error(f"Expected key=value parameter but received: {token}")
                return None
            key, value = token.split("=", 1)
            if not key:
                self._error(f"Invalid empty parameter name in token: {token}")
                return None
            parameters[key] = value
        return parameters

    def _split_tokens(self, arg: str) -> list[str] | None:
        try:
            return shlex.split(arg)
        except ValueError as exc:
            self._error(f"Unable to parse command arguments: {exc}")
            return None

    def _split_completion_words(self, line: str) -> list[str]:
        argline = line.partition(" ")[2]
        if not argline:
            return []
        try:
            tokens = shlex.split(argline)
        except ValueError:
            return []
        if argline.endswith(" "):
            tokens.append("")
        return tokens

    def _parse_completion_request(self, line: str) -> tuple[str, str, int, int] | None:
        stripped = line.lstrip()
        if not stripped:
            return None
        if " " not in stripped:
            return None
        command, _, remainder = stripped.partition(" ")
        text = "" if line.endswith(" ") else remainder.rsplit(" ", 1)[-1]
        begidx = len(line) - len(text)
        return command, text, begidx, len(line)

    def _ordered_topics(self) -> list[str]:
        return list(dict.fromkeys(self.command_help))

    def _help_topics(self) -> list[str]:
        return self._ordered_topics()

    def _error(self, message: str) -> None:
        self.last_status = 1
        self.stderr.write(f"{message}\n")

    def _write(self, message: str) -> None:
        self.stdout.write(f"{message}\n")

    def _write_json(self, payload: dict[str, Any]) -> None:
        self._write(json.dumps(payload, indent=2, sort_keys=True))

    def _match(self, options: list[str] | tuple[str, ...], text: str) -> list[str]:
        return [option for option in options if option.startswith(text)]


class UserShell(BaseShell):
    def __init__(
        self,
        *,
        client: Any,
        settings: CLISettings,
        user_id: str,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        super().__init__(client=client, settings=settings, stdout=stdout, stderr=stderr)
        self.user_id = user_id
        self.prompt = f"dms[{user_id}]> "
        self.intro = (
            f"DMS user CLI for {user_id}. "
            f"Connected to {settings.api_base_url}. Type 'help' for commands."
        )

    def _shell_help_topics(self) -> dict[str, CommandHelp]:
        return {
            "list": CommandHelp(
                summary="List your tasks across services or within one service.",
                usage=("list", "list mine", "list service <service>"),
                api_routes=(
                    "GET /api/v1/services/users/{user_id}/tasks",
                    "GET /api/v1/services/{service}/users/{user_id}/tasks",
                ),
                examples=(
                    "list",
                    "list service sync",
                ),
                notes=("The CLI always uses the current login user as user_id.",),
            ),
            "run": CommandHelp(
                summary="Submit a new task under the current user scope.",
                usage=("run <service> [key=value ...]",),
                api_routes=("POST /api/v1/services/{service}/users/{user_id}/tasks",),
                examples=(
                    "run sync src=/home/gpu1/data dst=/pvs/archive options='--delete --direct'",
                    "run rm path=/home/gpu1/data/tmp",
                    "run hotcold path=/pvs/projectA options='--dryrun'",
                ),
                notes=(
                    "Each key=value pair becomes a query parameter forwarded to dms-frontend.",
                    "Service examples follow the scheduler API usage and allowed service set.",
                ),
            ),
            "get": CommandHelp(
                summary="Fetch one task's status, logs, and result payload.",
                usage=("get <service> <task_id>",),
                api_routes=("GET /api/v1/services/{service}/tasks/{task_id}?user_id=",),
                examples=("get sync 10",),
            ),
            "cancel": CommandHelp(
                summary="Cancel one task, one service scope, or all of your tasks.",
                usage=("cancel mine", "cancel service <service>", "cancel task <service> <task_id>"),
                api_routes=(
                    "POST /api/v1/services/users/{user_id}/tasks/cancel",
                    "POST /api/v1/services/{service}/users/{user_id}/tasks/cancel",
                    "POST /api/v1/services/{service}/tasks/{task_id}/cancel?user_id=",
                ),
                examples=(
                    "cancel mine",
                    "cancel service sync",
                    "cancel task sync 10",
                ),
            ),
            "delete": CommandHelp(
                summary="Delete one task or clean up task metadata in a broader user scope.",
                usage=("delete mine", "delete service <service>", "delete task <service> <task_id>"),
                api_routes=(
                    "DELETE /api/v1/services/users/{user_id}/tasks",
                    "DELETE /api/v1/services/{service}/users/{user_id}/tasks",
                    "DELETE /api/v1/services/{service}/tasks/{task_id}?user_id=",
                ),
                examples=(
                    "delete mine",
                    "delete service rm",
                    "delete task sync 10",
                ),
                notes=("Delete removes stored task metadata/logs from dms-frontend state.",),
            ),
        }

    def _environment_notes(self) -> tuple[str, ...]:
        return (f"Current user_id: {self.user_id}",)

    def do_list(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if not tokens or tokens == ["mine"]:
            self._emit_api_result(lambda: self.client.list_tasks_by_user(self.user_id))
            return
        if len(tokens) == 2 and tokens[0] == "service":
            self._emit_api_result(lambda: self.client.list_user_tasks(tokens[1], self.user_id))
            return
        self._error("Usage: list | list mine | list service <service>")

    def complete_list(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["mine", "service"], text)
        if words[0] == "service" and len(words) == 2:
            return self._match(self._suggest_services(), text)
        return []

    def do_run(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if not tokens:
            self._error("Usage: run <service> [key=value ...]")
            return
        service = tokens[0]
        parameters = self._parse_key_value_arguments(tokens[1:])
        if parameters is None:
            return
        self._emit_api_result(lambda: self.client.create_task(service, self.user_id, parameters))

    def complete_run(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(self._suggest_services(), text)
        service = words[0]
        return self._match(list(SERVICE_PARAMETER_HINTS.get(service, ("key=",))), text)

    def do_get(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if len(tokens) != 2:
            self._error("Usage: get <service> <task_id>")
            return
        service, task_id = tokens
        self._emit_api_result(lambda: self.client.get_task_status(service, task_id, self.user_id))

    def complete_get(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(self._suggest_services(), text)
        if len(words) == 2:
            return self._match(self._suggest_task_ids(words[0]), text)
        return []

    def do_cancel(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if tokens == ["mine"]:
            self._emit_api_result(lambda: self.client.cancel_tasks_by_user(self.user_id))
            return
        if len(tokens) == 2 and tokens[0] == "service":
            self._emit_api_result(lambda: self.client.cancel_service_user_tasks(tokens[1], self.user_id))
            return
        if len(tokens) == 3 and tokens[0] == "task":
            _, service, task_id = tokens
            self._emit_api_result(lambda: self.client.cancel_task(service, task_id, self.user_id))
            return
        self._error("Usage: cancel mine | cancel service <service> | cancel task <service> <task_id>")

    def complete_cancel(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["mine", "service", "task"], text)
        if words[0] == "service" and len(words) == 2:
            return self._match(self._suggest_services(), text)
        if words[0] == "task":
            if len(words) == 2:
                return self._match(self._suggest_services(), text)
            if len(words) == 3:
                return self._match(self._suggest_task_ids(words[1]), text)
        return []

    def do_delete(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if tokens == ["mine"]:
            self._emit_api_result(lambda: self.client.cleanup_tasks_by_user(self.user_id))
            return
        if len(tokens) == 2 and tokens[0] == "service":
            self._emit_api_result(lambda: self.client.cleanup_service_user_tasks(tokens[1], self.user_id))
            return
        if len(tokens) == 3 and tokens[0] == "task":
            _, service, task_id = tokens
            self._emit_api_result(lambda: self.client.cleanup_task(service, task_id, self.user_id))
            return
        self._error("Usage: delete mine | delete service <service> | delete task <service> <task_id>")

    def complete_delete(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["mine", "service", "task"], text)
        if words[0] == "service" and len(words) == 2:
            return self._match(self._suggest_services(), text)
        if words[0] == "task":
            if len(words) == 2:
                return self._match(self._suggest_services(), text)
            if len(words) == 3:
                return self._match(self._suggest_task_ids(words[1]), text)
        return []

    def _suggest_services(self) -> list[str]:
        services = set(KNOWN_SERVICES)
        try:
            response = self.client.list_tasks_by_user(self.user_id)
        except DmsApiError:
            return sorted(services)
        services.update(
            str(task["service"])
            for task in response.get("tasks", [])
            if isinstance(task, dict) and task.get("service")
        )
        return sorted(services)

    def _suggest_task_ids(self, service: str) -> list[str]:
        try:
            response = self.client.list_user_tasks(service, self.user_id)
        except DmsApiError:
            return []
        task_ids = [
            str(task["task_id"])
            for task in response.get("tasks", [])
            if isinstance(task, dict) and task.get("task_id") is not None
        ]
        return sorted(task_ids, key=self._task_sort_key)

    @staticmethod
    def _task_sort_key(task_id: str) -> tuple[int, int | str]:
        if task_id.isdigit():
            return (0, int(task_id))
        return (1, task_id)


class AdminShell(BaseShell):
    def __init__(
        self,
        *,
        client: Any,
        settings: CLISettings,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        super().__init__(client=client, settings=settings, stdout=stdout, stderr=stderr)
        self.prompt = "dms[admin]> "
        self.intro = (
            f"DMS admin CLI authenticated against {settings.api_base_url}. "
            "Type 'help' for commands."
        )

    def _shell_help_topics(self) -> dict[str, CommandHelp]:
        return {
            "list": CommandHelp(
                summary="List global tasks, service tasks/users, or the next task ID cursor.",
                usage=(
                    "list tasks",
                    "list next-id",
                    "list service <service> tasks",
                    "list service <service> users",
                ),
                api_routes=(
                    "GET /api/v1/admin/tasks",
                    "GET /api/v1/admin/tasks/next-id",
                    "GET /api/v1/admin/services/{service}/tasks",
                    "GET /api/v1/admin/services/{service}/users",
                ),
                examples=(
                    "list tasks",
                    "list next-id",
                    "list service sync tasks",
                    "list service sync users",
                ),
            ),
            "summary": CommandHelp(
                summary="Summarize pending/success/failed task IDs for one service.",
                usage=("summary service <service>",),
                api_routes=("GET /api/v1/admin/services/{service}/tasks/summary",),
                examples=("summary service sync",),
            ),
            "cancel": CommandHelp(
                summary="Cancel one task or all tasks owned by a service.",
                usage=("cancel task <task_id>", "cancel service <service>"),
                api_routes=(
                    "POST /api/v1/admin/tasks/{task_id}/cancel",
                    "POST /api/v1/admin/services/{service}/tasks/cancel",
                ),
                examples=(
                    "cancel task 10",
                    "cancel service hotcold",
                ),
            ),
            "delete": CommandHelp(
                summary="Delete task metadata for one task or for an entire service.",
                usage=("delete task <task_id>", "delete service <service>"),
                api_routes=(
                    "DELETE /api/v1/admin/tasks/{task_id}",
                    "DELETE /api/v1/admin/services/{service}/tasks",
                ),
                examples=(
                    "delete task 10",
                    "delete service rm",
                ),
                notes=(
                    "Deleting an admin task removes metadata immediately after issuing an asynchronous cancel request.",
                ),
            ),
        }

    def _environment_notes(self) -> tuple[str, ...]:
        return ("Admin mode requires root privileges and a verified operator token.",)

    def do_list(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if tokens == ["tasks"]:
            self._emit_api_result(lambda: self.client.list_all_tasks())
            return
        if tokens == ["next-id"]:
            self._emit_api_result(lambda: self.client.get_next_task_id())
            return
        if len(tokens) == 3 and tokens[0] == "service":
            service, target = tokens[1], tokens[2]
            if target == "tasks":
                self._emit_api_result(lambda: self.client.list_service_tasks(service))
                return
            if target == "users":
                self._emit_api_result(lambda: self.client.list_service_users(service))
                return
        self._error("Usage: list tasks | list next-id | list service <service> tasks | list service <service> users")

    def complete_list(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["tasks", "next-id", "service"], text)
        if words[0] == "service":
            if len(words) == 2:
                return self._match(list(KNOWN_SERVICES), text)
            if len(words) == 3:
                return self._match(["tasks", "users"], text)
        return []

    def do_summary(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if len(tokens) == 2 and tokens[0] == "service":
            self._emit_api_result(lambda: self.client.summarize_service_tasks(tokens[1]))
            return
        self._error("Usage: summary service <service>")

    def complete_summary(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["service"], text)
        if words[0] == "service" and len(words) == 2:
            return self._match(list(KNOWN_SERVICES), text)
        return []

    def do_cancel(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if len(tokens) == 2 and tokens[0] == "task":
            self._emit_api_result(lambda: self.client.cancel_admin_task(tokens[1]))
            return
        if len(tokens) == 2 and tokens[0] == "service":
            self._emit_api_result(lambda: self.client.cancel_service_tasks(tokens[1]))
            return
        self._error("Usage: cancel task <task_id> | cancel service <service>")

    def complete_cancel(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["task", "service"], text)
        if words[0] == "service" and len(words) == 2:
            return self._match(list(KNOWN_SERVICES), text)
        return []

    def do_delete(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if len(tokens) == 2 and tokens[0] == "task":
            self._emit_api_result(lambda: self.client.cleanup_admin_task(tokens[1]))
            return
        if len(tokens) == 2 and tokens[0] == "service":
            self._emit_api_result(lambda: self.client.cleanup_service_tasks(tokens[1]))
            return
        self._error("Usage: delete task <task_id> | delete service <service>")

    def complete_delete(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["task", "service"], text)
        if words[0] == "service" and len(words) == 2:
            return self._match(list(KNOWN_SERVICES), text)
        return []


class KubeShell(BaseShell):
    def __init__(
        self,
        *,
        settings: CLISettings,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        super().__init__(client=None, settings=settings, stdout=stdout, stderr=stderr)
        self.prompt = "dms-kube> "
        self.intro = "DMS-kube CLI placeholder. Type 'help' for commands."

    def _shell_help_topics(self) -> dict[str, CommandHelp]:
        return {
            "hello": CommandHelp(
                summary="Placeholder command for the future kube CLI tree.",
                usage=("hello", "hello <name>"),
                examples=("hello", "hello scheduler"),
                notes=("This is a stub so the dms-kube entry point is already reserved.",),
            )
        }

    def do_hello(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        target = tokens[0] if tokens else "dms-kube"
        self._write_json({"message": f"hello {target}", "mode": "kube"})
        self.last_status = 0

    def complete_hello(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del line, begidx, endidx
        return self._match(["scheduler", "cluster", "dms-kube"], text)

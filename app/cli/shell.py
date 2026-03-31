from __future__ import annotations

import cmd
import io
import json
import os
import pwd
import shlex
import sys
from dataclasses import dataclass
from typing import Any, Callable, TextIO

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
        pipeline = self._parse_grep_pipeline(line)
        if pipeline is False:
            return self.last_status
        if pipeline is None:
            self.onecmd(line)
            return self.last_status

        command, keyword = pipeline
        buffered_stdout = io.StringIO()
        original_stdout = self.stdout
        self.stdout = buffered_stdout
        try:
            self.onecmd(command)
        finally:
            self.stdout = original_stdout

        if self.last_status != 0:
            return self.last_status

        for raw_line in buffered_stdout.getvalue().splitlines():
            if keyword in raw_line:
                original_stdout.write(f"{raw_line}\n")
        return self.last_status

    def onecmd(self, line: str) -> bool | None:
        try:
            return super().onecmd(line)
        except Exception as exc:  # noqa: BLE001
            self._error(f"Unexpected error while processing command: {exc}")
            return False

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

    def do_clear(self, _: str) -> None:
        self.stdout.write("\033[2J\033[H")
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
            "clear": CommandHelp(
                summary="Clear the current terminal screen.",
                usage=("clear",),
                examples=("clear",),
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

    def _parse_grep_pipeline(self, line: str) -> tuple[str, str] | None | bool:
        tokens = self._split_tokens(line)
        if tokens is None:
            return False
        if "|" not in tokens:
            return None

        pipe_index = tokens.index("|")
        command_tokens = tokens[:pipe_index]
        filter_tokens = tokens[pipe_index + 1 :]
        if not command_tokens:
            self._error("Command before pipe is required.")
            return False
        if len(filter_tokens) < 2 or filter_tokens[0] != "grep":
            self._error("Only '| grep <keyword>' filtering is supported.")
            return False

        keyword = " ".join(filter_tokens[1:]).strip()
        if not keyword:
            self._error("grep keyword cannot be empty.")
            return False
        return shlex.join(command_tokens), keyword

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

    def _write_task_table(self, tasks: list[dict[str, Any]]) -> None:
        headers = ["task_id", "service", "status", "priority", "created_at", "updated_at", "parameters"]
        max_widths = {
            "task_id": 12,
            "service": 12,
            "status": 12,
            "priority": 10,
            "created_at": 32,
            "updated_at": 32,
            "parameters": 80,
        }

        def _cell(value: Any, *, max_width: int) -> str:
            text = self._stringify_cell_value(value)
            if len(text) > max_width:
                return f"{text[: max_width - 3]}..."
            return text

        rows = [
            {
                "task_id": _cell(task.get("task_id"), max_width=max_widths["task_id"]),
                "service": _cell(task.get("service"), max_width=max_widths["service"]),
                "status": _cell(task.get("status"), max_width=max_widths["status"]),
                "priority": _cell(task.get("priority"), max_width=max_widths["priority"]),
                "created_at": _cell(task.get("created_at"), max_width=max_widths["created_at"]),
                "updated_at": _cell(task.get("updated_at"), max_width=max_widths["updated_at"]),
                "parameters": _cell(task.get("parameters"), max_width=max_widths["parameters"]),
            }
            for task in tasks
            if isinstance(task, dict)
        ]

        widths = {
            header: max((len(row[header]) for row in rows), default=len(header))
            for header in headers
        }
        separator = "+" + "+".join("-" * (widths[header] + 2) for header in headers) + "+"
        header_row = "| " + " | ".join(header.ljust(widths[header]) for header in headers) + " |"

        self._write(separator)
        self._write(header_row)
        self._write(separator)
        for row in rows:
            rendered = "| " + " | ".join(row[header].ljust(widths[header]) for header in headers) + " |"
            self._write(rendered)
        self._write(separator)

    def _stringify_cell_value(self, value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)


    def _parse_task_id_selector(self, selector: str) -> list[str] | None:
        raw = selector.strip()
        if not raw:
            self._error("Task ID selector cannot be empty.")
            return None

        if raw.startswith("[") or raw.endswith("]"):
            if not (raw.startswith("[") and raw.endswith("]")):
                self._error("Invalid task_id selector format. Brackets must wrap the whole selector.")
                return None
            raw = raw[1:-1].strip()
            if not raw:
                self._error("Task ID selector cannot be empty.")
                return None

        task_ids: list[str] = []
        seen: set[str] = set()
        for part in raw.split(","):
            item = part.strip()
            if not item:
                self._error(f"Invalid task_id selector: {selector}")
                return None
            if "-" in item:
                range_parts = item.split("-")
                if len(range_parts) != 2 or not range_parts[0].strip() or not range_parts[1].strip():
                    self._error(f"Invalid task_id range: {item}")
                    return None
                start_text, end_text = range_parts[0].strip(), range_parts[1].strip()
                if not start_text.isdigit() or not end_text.isdigit():
                    self._error(f"Task IDs must be integers: {item}")
                    return None
                start, end = int(start_text), int(end_text)
                if start <= 0 or end <= 0:
                    self._error(f"Task IDs must be positive integers: {item}")
                    return None
                if start > end:
                    self._error(f"Invalid task_id range (start > end): {item}")
                    return None
                for task_id in range(start, end + 1):
                    task_id_text = str(task_id)
                    if task_id_text not in seen:
                        seen.add(task_id_text)
                        task_ids.append(task_id_text)
                continue

            if not item.isdigit():
                self._error(f"Task IDs must be integers: {item}")
                return None
            value = int(item)
            if value <= 0:
                self._error(f"Task IDs must be positive integers: {item}")
                return None
            task_id_text = str(value)
            if task_id_text not in seen:
                seen.add(task_id_text)
                task_ids.append(task_id_text)

        if not task_ids:
            self._error("Task ID selector cannot be empty.")
            return None
        return task_ids

    def _emit_task_id_batch(
        self,
        *,
        task_ids: list[str],
        request_factory: Callable[[str], dict[str, Any]],
    ) -> None:
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for task_id in task_ids:
            try:
                payload = request_factory(task_id)
            except DmsApiError as exc:
                errors.append({"task_id": task_id, "error": str(exc)})
                continue
            results.append({"task_id": task_id, "result": payload})

        response: dict[str, Any] = {
            "requested_task_ids": task_ids,
            "results": results,
        }
        if errors:
            response["errors"] = errors
            self.last_status = 1
        else:
            self.last_status = 0
        self._write_json(response)

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
                usage=(
                    "list",
                    "list mine",
                    "list brief",
                    "list mine brief",
                    "list service <service>",
                    "list service <service> brief",
                ),
                api_routes=(
                    "GET /api/v1/services/users/{user_id}/tasks",
                    "GET /api/v1/services/{service}/users/{user_id}/tasks",
                ),
                examples=(
                    "list",
                    "list brief",
                    "list service sync",
                    "list service sync brief",
                ),
                notes=(
                    "The CLI always uses the current login user as user_id.",
                    "Add 'brief' to render task rows as a compact table instead of raw JSON.",
                ),
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
                usage=("get <service> <task_id|task_id_selector>",),
                api_routes=("GET /api/v1/services/{service}/tasks/{task_id}?user_id=",),
                examples=("get sync 10", "get sync [1-3,8]"),
                notes=("task_id supports selectors like 1,2,3 | [1-3,8] | [1-6].",),
            ),
            "cancel": CommandHelp(
                summary="Cancel one task, one service scope, or all of your tasks.",
                usage=("cancel mine", "cancel service <service>", "cancel task <service> <task_id|task_id_selector>"),
                api_routes=(
                    "POST /api/v1/services/users/{user_id}/tasks/cancel",
                    "POST /api/v1/services/{service}/users/{user_id}/tasks/cancel",
                    "POST /api/v1/services/{service}/tasks/{task_id}/cancel?user_id=",
                ),
                examples=(
                    "cancel mine",
                    "cancel service sync",
                    "cancel task sync 10",
                    "cancel task sync [1-3,5]",
                ),
                notes=("task_id supports selectors like 1,2,3 | [1-3,8] | [1-6].",),
            ),
            "delete": CommandHelp(
                summary="Delete one task or clean up task metadata in a broader user scope.",
                usage=("delete mine", "delete service <service>", "delete task <service> <task_id|task_id_selector>"),
                api_routes=(
                    "DELETE /api/v1/services/users/{user_id}/tasks",
                    "DELETE /api/v1/services/{service}/users/{user_id}/tasks",
                    "DELETE /api/v1/services/{service}/tasks/{task_id}?user_id=",
                ),
                examples=(
                    "delete mine",
                    "delete service rm",
                    "delete task sync 10",
                    "delete task sync [1-3,5]",
                ),
                notes=(
                    "Delete removes stored task metadata/logs from dms-frontend state.",
                    "task_id supports selectors like 1,2,3 | [1-3,8] | [1-6].",
                ),
            ),
        }

    def _environment_notes(self) -> tuple[str, ...]:
        return (f"Current user_id: {self.user_id}",)

    def do_list(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        brief = "brief" in tokens
        filtered_tokens = [token for token in tokens if token != "brief"]

        if not filtered_tokens or filtered_tokens == ["mine"]:
            self._emit_user_list_result(lambda: self.client.list_tasks_by_user(self.user_id), brief)
            return
        if len(filtered_tokens) == 2 and filtered_tokens[0] == "service":
            self._emit_user_list_result(
                lambda: self.client.list_user_tasks(filtered_tokens[1], self.user_id),
                brief,
            )
            return
        self._error("Usage: list [mine] [brief] | list service <service> [brief]")

    def _emit_user_list_result(self, request: Any, brief: bool) -> None:
        try:
            payload = request()
        except DmsApiError as exc:
            self._error(str(exc))
            return
        if brief:
            tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
            if not isinstance(tasks, list):
                self._error("Invalid API response: expected 'tasks' list.")
                return
            self._write_task_table(tasks)
        else:
            self._write_json(payload)
        self.last_status = 0

    def complete_list(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["mine", "service", "brief"], text)
        if words[0] in {"mine", "brief"} and len(words) == 2:
            return self._match([word for word in ["mine", "brief"] if word not in words], text)
        if words[0] == "service" and len(words) == 2:
            return self._match(self._suggest_services(), text)
        if words[0] == "service" and len(words) == 3:
            return self._match(["brief"], text)
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
            self._error("Usage: get <service> <task_id|task_id_selector>")
            return
        service, task_id_selector = tokens
        task_ids = self._parse_task_id_selector(task_id_selector)
        if task_ids is None:
            return
        if len(task_ids) == 1:
            self._emit_api_result(lambda: self.client.get_task_status(service, task_ids[0], self.user_id))
            return
        self._emit_task_id_batch(
            task_ids=task_ids,
            request_factory=lambda task_id: self.client.get_task_status(service, task_id, self.user_id),
        )

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
            _, service, task_id_selector = tokens
            task_ids = self._parse_task_id_selector(task_id_selector)
            if task_ids is None:
                return
            if len(task_ids) == 1:
                self._emit_api_result(lambda: self.client.cancel_task(service, task_ids[0], self.user_id))
                return
            self._emit_task_id_batch(
                task_ids=task_ids,
                request_factory=lambda task_id: self.client.cancel_task(service, task_id, self.user_id),
            )
            return
        self._error("Usage: cancel mine | cancel service <service> | cancel task <service> <task_id|task_id_selector>")

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
            _, service, task_id_selector = tokens
            task_ids = self._parse_task_id_selector(task_id_selector)
            if task_ids is None:
                return
            if len(task_ids) == 1:
                self._emit_api_result(lambda: self.client.cleanup_task(service, task_ids[0], self.user_id))
                return
            self._emit_task_id_batch(
                task_ids=task_ids,
                request_factory=lambda task_id: self.client.cleanup_task(service, task_id, self.user_id),
            )
            return
        self._error("Usage: delete mine | delete service <service> | delete task <service> <task_id|task_id_selector>")

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
                    "list tasks brief",
                    "list next-id",
                    "list service <service> tasks",
                    "list service <service> tasks brief",
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
                    "list tasks brief",
                    "list next-id",
                    "list service sync tasks",
                    "list service sync tasks brief",
                    "list service sync users",
                ),
                notes=("Add 'brief' to render task rows as a compact table instead of raw JSON.",),
            ),
            "summary": CommandHelp(
                summary="Summarize pending/success/failed task IDs for one service.",
                usage=("summary service <service>",),
                api_routes=("GET /api/v1/admin/services/{service}/tasks/summary",),
                examples=("summary service sync",),
            ),
            "metrics": CommandHelp(
                summary="Show admin runtime metrics for Redis listener/reconciler.",
                usage=("metrics",),
                api_routes=("GET /api/v1/admin/metrics",),
                examples=("metrics",),
            ),
            "cancel": CommandHelp(
                summary="Cancel one task or all tasks owned by a service.",
                usage=("cancel task <task_id|task_id_selector>", "cancel service <service>"),
                api_routes=(
                    "POST /api/v1/admin/tasks/{task_id}/cancel",
                    "POST /api/v1/admin/services/{service}/tasks/cancel",
                ),
                examples=(
                    "cancel task 10",
                    "cancel task [1-3,5]",
                    "cancel service hotcold",
                ),
                notes=("task_id supports selectors like 1,2,3 | [1-3,8] | [1-6].",),
            ),
            "delete": CommandHelp(
                summary="Delete task metadata for one task or for an entire service.",
                usage=("delete task <task_id|task_id_selector>", "delete service <service>"),
                api_routes=(
                    "DELETE /api/v1/admin/tasks/{task_id}",
                    "DELETE /api/v1/admin/services/{service}/tasks",
                ),
                examples=(
                    "delete task 10",
                    "delete task [1-3,5]",
                    "delete service rm",
                ),
                notes=(
                    "Deleting an admin task removes metadata immediately after issuing an asynchronous cancel request.",
                    "task_id supports selectors like 1,2,3 | [1-3,8] | [1-6].",
                ),
            ),
        }

    def _environment_notes(self) -> tuple[str, ...]:
        return ("Admin mode requires root privileges and a verified operator token.",)

    def do_list(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        brief = "brief" in tokens
        filtered_tokens = [token for token in tokens if token != "brief"]

        if filtered_tokens == ["tasks"]:
            self._emit_admin_task_list_result(lambda: self.client.list_all_tasks(), brief)
            return
        if filtered_tokens == ["next-id"]:
            if brief:
                self._error("brief is only supported for task list outputs.")
                return
            self._emit_api_result(lambda: self.client.get_next_task_id())
            return
        if len(filtered_tokens) == 3 and filtered_tokens[0] == "service":
            service, target = filtered_tokens[1], filtered_tokens[2]
            if target == "tasks":
                self._emit_admin_task_list_result(lambda: self.client.list_service_tasks(service), brief)
                return
            if target == "users":
                if brief:
                    self._error("brief is only supported for task list outputs.")
                    return
                self._emit_api_result(lambda: self.client.list_service_users(service))
                return
        self._error(
            "Usage: list tasks [brief] | list next-id | list service <service> tasks [brief] | list service <service> users"
        )

    def _emit_admin_task_list_result(self, request: Any, brief: bool) -> None:
        try:
            payload = request()
        except DmsApiError as exc:
            self._error(str(exc))
            return

        if brief:
            tasks = payload.get("tasks", [])
            if not isinstance(tasks, list):
                self._error("Response payload is missing a valid 'tasks' list.")
                return
            self._write_task_table(tasks)
            self.last_status = 0
            return

        self._write_json(payload)
        self.last_status = 0

    def complete_list(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        del begidx, endidx
        words = self._split_completion_words(line)
        if len(words) <= 1:
            return self._match(["tasks", "next-id", "service"], text)
        if words[0] == "tasks" and len(words) == 2:
            return self._match(["brief"], text)
        if words[0] == "service":
            if len(words) == 2:
                return self._match(list(KNOWN_SERVICES), text)
            if len(words) == 3:
                return self._match(["tasks", "users"], text)
            if len(words) == 4 and words[2] == "tasks":
                return self._match(["brief"], text)
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

    def do_metrics(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if tokens:
            self._error("Usage: metrics")
            return
        self._emit_api_result(lambda: self.client.admin_metrics())

    def do_cancel(self, arg: str) -> None:
        tokens = self._split_tokens(arg)
        if tokens is None:
            return
        if len(tokens) == 2 and tokens[0] == "task":
            task_ids = self._parse_task_id_selector(tokens[1])
            if task_ids is None:
                return
            if len(task_ids) == 1:
                self._emit_api_result(lambda: self.client.cancel_admin_task(task_ids[0]))
                return
            self._emit_task_id_batch(
                task_ids=task_ids,
                request_factory=lambda task_id: self.client.cancel_admin_task(task_id),
            )
            return
        if len(tokens) == 2 and tokens[0] == "service":
            self._emit_api_result(lambda: self.client.cancel_service_tasks(tokens[1]))
            return
        self._error("Usage: cancel task <task_id|task_id_selector> | cancel service <service>")

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
            task_ids = self._parse_task_id_selector(tokens[1])
            if task_ids is None:
                return
            if len(task_ids) == 1:
                self._emit_api_result(lambda: self.client.cleanup_admin_task(task_ids[0]))
                return
            self._emit_task_id_batch(
                task_ids=task_ids,
                request_factory=lambda task_id: self.client.cleanup_admin_task(task_id),
            )
            return
        if len(tokens) == 2 and tokens[0] == "service":
            self._emit_api_result(lambda: self.client.cleanup_service_tasks(tokens[1]))
            return
        self._error("Usage: delete task <task_id|task_id_selector> | delete service <service>")

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

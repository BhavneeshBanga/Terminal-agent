# -*- coding: utf-8 -*-
"""
bhavai/tui.py


Replaces the old `while True: Prompt.ask(...)` REPL in main.py's `wake()`
command with a persistent Textual app: a scrollback log on top, a fixed
input box at the bottom.

Key idea: rather than rewriting modes.prompt_and_confirm_plan() and
agent.run_agent_loop() (which use blocking rich Prompt.ask / console.print),
we call them inside `self.suspend()`. Textual hands the real terminal back
for the duration of the call, so all your existing rich-based code keeps
working untouched. When the call returns, Textual repaints and you're back
in the chat UI.

Run with:
    python -m bhavai.tui
or wire it up as the body of `bhav wake up` in main.py (see bottom of file).
"""

from __future__ import annotations

import asyncio
import getpass
import os
from pathlib import Path

from rich.console import Console
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer, Input, RichLog
from textual.reactive import reactive
from textual.widgets import Header, Footer, Input, RichLog, OptionList
from textual.widgets.option_list import Option

from bhavai.config import get_config_summary, CWD, logger
from bhavai.context import get_folder_tree_string
from bhavai.memory import ConversationMemory
from bhavai.modes import AgentMode, prompt_and_confirm_plan
from bhavai.agent import run_agent_loop


from bhavai.scripts.initialize_markdown import scan_and_summarize_project
# ---------------------------------------------------------------------- #
# Same identity as bhavai/banner.py — kept here so the TUI's welcome
# screen matches the standalone banner pixel-for-pixel.
# ---------------------------------------------------------------------- #

# LOGO = [
#     r"░█▀▄░█░█░█▀█░█░█░█▀█░▀█▀",
#     r"░█▀▄░█▀█░█▀█░▀▄▀░█▀█░░█░",
#     r"░▀▀░░▀░▀░▀░▀░░▀░░▀░▀░▀▀▀",
# ]
LOGO = [
    r"░█▀▄░█░█░█▀█░█░█░█▀█░▀█▀",
    r"░█▀▄░█▀█░█▀█░▀▄▀░█▀█░░█░",
    r"░▀▀░░▀░▀░▀░▀░░▀░░▀░▀░▀▀▀",
]
VERSION = "1.0.0"

TIPS = [
    "Run [bold]/init[/bold] to create a BHAVAI.md file with instructions for the agent.",
    "Note: you launched bhavai in this folder. For a fresh workspace, cd first.",
]

WHATS_NEW = [
    "Introducing Plan Mode by default — review steps before execution.",
    "Added persistent conversation memory across sessions.",
    "/release-notes for more",
]

# ---------------------------------------------------------------------- #
# /init — full codebase dump into BHAVAI.md
# ---------------------------------------------------------------------- #

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
    "site-packages", ".eggs", ".tox", "htmlcov",
}

IGNORE_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "BHAVAI.md",  # never re-ingest our own output
}

IGNORE_EXTS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".pdf", ".zip", ".tar", ".gz", ".7z", ".lock", ".db", ".sqlite3",
    ".woff", ".woff2", ".ttf", ".mp4", ".mov", ".bin",
}

MAX_FILE_CHARS = 6000        # cap on how much of a single file we pull in
MAX_TOTAL_CHARS = 150_000    # overall cap so BHAVAI.md doesn't explode



def generate_bhavai_md(root: Path) -> Path:
    """Walk `root`, collect every non-ignored file's path + content, and
    write a single BHAVAI.md snapshot of the codebase at the project root.
    Runs synchronously — call via asyncio.to_thread() from async code.
    """
    scan_and_summarize_project(root_dir=root)

    out_path = Path(root) / "BHAVAI.md"
    # out_path.write_text(header + "".join(sections), encoding="utf-8")
    return out_path


def list_available_commands(limit: int = 5) -> list[tuple[str, str]]:
    """Scan .bhavai/commands/*.md and return up to `limit` (name, description) pairs.
    Description = first non-empty line of the file, stripped of markdown '#'.
    """
    commands_dir = CWD / ".bhavai" / "commands"
    if not commands_dir.exists():
        return []

    results: list[tuple[str, str]] = []
    for path in sorted(commands_dir.glob("*.md")):
        name = path.stem
        try:
            first_line = next(
                (l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()),
                "",
            )
        except Exception:
            first_line = ""
        description = first_line.lstrip("#").strip() or "No description"
        results.append((name, description))
        if len(results) >= limit:
            break
    return results

class LogConsole:
    """Drop-in replacement for rich.Console — writes into the TUI's RichLog
    instead of raw stdout. Same .print()/.status() interface so modes.py
    and agent.py need ZERO changes.
    """
    def __init__(self, log: "RichLog") -> None:
        self._log = log

    def print(self, *args, **kwargs) -> None:
        for arg in args:
            self._log.write(arg)

    def status(self, message: str, spinner: str = "dots"):
        # No real spinner in log mode — just print the status line once.
        self._log.write(message)
        return _NoopStatus()


class _NoopStatus:
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    
class BhavAI(App):
    """Persistent chat-style TUI for the BhavAI agent."""

    CSS = """
    Screen {
        background: $surface;
    }

    #log {
        height: 1fr;
        border: round green;
        padding: 0 1;
        margin: 0 1;
    }

    #input-box {
        dock: bottom;
        height: 3;
        border: round green;
        margin: 0 1 1 1;
    }
    #command-suggestions {
        dock: bottom;
        height: auto;
        max-height: 7;
        border: round green;
        margin: 0 1 4 1;
        display: none;
        background: $surface;
    }

    #command-suggestions.visible {
        display: block;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
    ]

    mode: reactive[AgentMode] = reactive(AgentMode.PLAN)

    def __init__(self) -> None:
        super().__init__()
        self.cfg = get_config_summary()
        self.memory = ConversationMemory()
        self.log_console: "LogConsole | None" = None
        self.awaiting_plan_confirmation = False
        self._pending_user_input: str | None = None
        self._pending_plan_steps: list = []



    # ------------------------------------------------------------------ 
    # Layout
    # ------------------------------------------------------------------ 

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container():
            yield RichLog(id="log", wrap=True, markup=True, highlight=True)
            yield Input(
                placeholder=self._placeholder(),
                id="input-box",
            )
            yield OptionList(id="command-suggestions")
        yield Footer()

    def _placeholder(self) -> str:
        # return f"({self.mode}) \u276f Try \"refactor this file\" or \"run the tests\""
        return f"({self.mode}) ❯ Run /init to create a BHAVAI.md file"

    def on_mount(self) -> None:
        if not self.cfg.get("API_KEY_PRESENT"):
            self.exit(
                message=(
                    "API KEY MISSING — set SARVAM_API_KEY or create a .env file. "
                    "Visit https://dashboard.sarvam.ai/"
                )
            )
            return

        log = self.query_one("#log", RichLog)
        log.write(self._banner())
        log.write(Rule(style="dim"))

        try:
            tree_str = get_folder_tree_string(CWD)
            log.write(tree_str)
            log.write(Rule(style="dim"))
        except Exception as e:  # noqa: BLE001
            log.write(f"[yellow]Warning: Could not build folder tree: {e}[/yellow]")

        log.write(
            Text("? for shortcuts · mode agent / mode plan to switch", style="dim"),
        )
        self.log_console = LogConsole(log)

        self.query_one(Input).focus()



    def on_input_changed(self, event: Input.Changed) -> None:
        suggestions = self.query_one("#command-suggestions", OptionList)
        value = event.value

        if not value.startswith("/") or " " in value:
            suggestions.remove_class("visible")
            return

        query = value[1:].lower()
        matches = [
            (name, desc) for name, desc in list_available_commands(limit=20)
            if name.lower().startswith(query)
        ][:5]

        if not matches:
            suggestions.remove_class("visible")
            return

        suggestions.clear_options()
        for name, desc in matches:
            suggestions.add_option(Option(f"/{name}  [dim]{desc}[/dim]", id=name))
        suggestions.add_class("visible")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "command-suggestions":
            return
        input_box = self.query_one("#input-box", Input)
        input_box.value = f"/{event.option.id}"
        input_box.focus()
        self.query_one("#command-suggestions", OptionList).remove_class("visible")


    def _left_column(self, username: str) -> Table:
        cfg = self.cfg
        col = Table.grid(padding=0)
        col.add_column(justify="center")
        col.add_row(Text(f"Welcome back {username}!", style="bold white"))
        col.add_row(Text(""))
        for line in LOGO:
            col.add_row(Text(line, style="bold green"))
        col.add_row(Text(""))
        col.add_row(
            Text.assemble(
                (cfg.get("MODEL", "unknown-model"), "green"),
                (" · ", "dim"),
                (f"{self.mode} Mode (Default)", "dim white"),
            )
        )
        col.add_row(Text(cfg.get("CWD", os.getcwd()), style="dim"))
        return col

    def _right_column(self) -> Table:
        col = Table.grid(padding=0)
        col.add_column()
        col.add_row(Text("Tips for getting started", style="bold green"))
        for tip in TIPS:
            col.add_row(Text.from_markup(tip, style="dim"))
        col.add_row(Text("─" * 44, style="dim"))
        col.add_row(Text("What's new", style="bold green"))
        for item in WHATS_NEW:
            col.add_row(Text.from_markup(item, style="dim"))
        return col

    def _banner(self) -> Panel:
        username = getpass.getuser()
        layout = Table.grid(expand=True)
        layout.add_column(ratio=1)
        layout.add_column(ratio=1)
        layout.add_row(
            self._left_column(username),
            Padding(self._right_column(), (0, 0, 0, 2)),
        )
        return Panel(
            layout,
            title=f"[bold green]BhavAI v{VERSION}[/bold green]",
            title_align="left",
            border_style="green",
            padding=(1, 2),
        )

    # ------------------------------------------------------------------ #
    # Input handling
    # ------------------------------------------------------------------ #

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        input_box = self.query_one("#input-box", Input)
        input_box.value = ""

        if not user_input:
            return

        log = self.query_one("#log", RichLog)
        log.write(Text.assemble(("\u276f ", "bold green"), (user_input, "bold")))

        low = user_input.lower()
        if self.awaiting_plan_confirmation:
            self.awaiting_plan_confirmation = False
            if low == "y":
                log.write("[bold green]Plan approved. Executing step-by-step...[/bold green]")
                self._start_agent_worker(self._pending_user_input, self._pending_plan_steps)
            elif low in ("n", "no", ""):
                log.write("[yellow]Plan execution cancelled.[/yellow]")
            else:
                log.write(f"[blue]Updating plan based on feedback: '{user_input}'...[/blue]")
                folder_tree = get_folder_tree_string(CWD)
                plan_steps = prompt_and_confirm_plan(
                    self._pending_user_input, folder_tree, self.log_console, feedback=user_input
                )
                self._pending_plan_steps = plan_steps
                self.awaiting_plan_confirmation = True
            return

        if low == "mode agent":
            self.mode = AgentMode.AGENT
            input_box.placeholder = self._placeholder()
            log.write("[yellow]Switched to Agent Mode (tasks execute autonomously).[/yellow]")
            return

        if low == "mode plan":
            self.mode = AgentMode.PLAN
            input_box.placeholder = self._placeholder()
            log.write("[cyan]Switched to Plan Mode (checklist shown before execution).[/cyan]")
            return

        if low in ("exit", "quit"):
            log.write("[green]Goodbye from BhavAI! Waking down...[/green]")
            self.exit()
            return
        if low == "/save":
            save_path = CWD / "bhavai_conversation.md"
            try:
                self.memory.save_to_file(save_path)
                log.write(f"[green]✓ Conversation saved to {save_path}[/green]")
            except Exception as e:
                log.write(f"[red]Failed to save conversation: {e}[/red]")
            return
        if low == "/init":
            log.write("[cyan]Generating BHAVAI.md...[/cyan]")

            try:
                path = await asyncio.to_thread(generate_bhavai_md, CWD)
                log.write(f"[green]✓ Created {path}[/green]")
            except Exception as e:
                log.write(f"[red]Failed to generate BHAVAI.md: {e}[/red]")

            return
        if user_input.startswith("/"):
            command_name = user_input[1:].strip()
            command_path = CWD / ".bhavai" / "commands" / f"{command_name}.md"

            if not command_path.exists():
                log.write(f"[bold red]✗ Error:[/bold red] Command '/{command_name}' exist nahi karti.")
                return

            command_text = command_path.read_text(encoding="utf-8").strip()
            log.write(Panel(
                command_text,
                title=f"[bold cyan]📄 /{command_name}.md[/bold cyan]",
                border_style="cyan",
            ))
            log.write(f"[cyan]▶ Running command:[/cyan] [bold]/{command_name}[/bold]")

            self._run_task(command_text, log)
            return

        if self.mode == AgentMode.PLAN:
            folder_tree = get_folder_tree_string(CWD)
            plan_steps = prompt_and_confirm_plan(user_input, folder_tree, self.log_console)
            self._pending_user_input = user_input
            self._pending_plan_steps = plan_steps
            self.awaiting_plan_confirmation = True
        else:
            self._start_agent_worker(user_input)

    # ------------------------------------------------------------------ #
    # Task execution — hands the real terminal back via suspend()
    # ------------------------------------------------------------------ #
    def _start_agent_worker(self, user_input: str, plan_steps: list | None = None) -> None:
        self.run_worker(
            self._agent_worker(user_input, plan_steps),
            exclusive=True,
            thread=True,
        )

    def _agent_worker(self, user_input: str, plan_steps: list | None) -> None:
        log = self.query_one("#log", RichLog)
        try:
            run_agent_loop(
                user_input=user_input,
                memory=self.memory,
                current_mode=self.mode,
                plan_steps=plan_steps,
                console=self.log_console,
            )
        except Exception as e:  # noqa: BLE001
            log.write(f"[bold red]Unexpected Error:[/bold red] {e}")
            logger.exception("TUI worker encountered unexpected error: %s", e)
        else:
            log.write("[dim]✓ Task complete.[/dim]")

    # def _run_task(self, user_input: str, log: RichLog) -> None:
    #     try:
    #         with self.suspend():
    #             os.system("cls" if os.name == "nt" else "clear")
    #             self.raw_console.rule("[bold green]BhavAI is working[/bold green]")

    #             if self.mode == AgentMode.PLAN:
    #                 folder_tree = get_folder_tree_string(CWD)
    #                 should_proceed, plan_steps = prompt_and_confirm_plan(
    #                     user_input, folder_tree, self.raw_console
    #                 )
    #                 if should_proceed:
    #                     self.raw_console.print(
    #                         "[bold green]Plan approved. Executing step-by-step...[/bold green]"
    #                     )
    #                     run_agent_loop(
    #                         user_input=user_input,
    #                         memory=self.memory,
    #                         current_mode=self.mode,
    #                         plan_steps=plan_steps,
    #                         console=self.raw_console,
    #                     )
    #                 else:
    #                     self.raw_console.print("[yellow]Plan rejected — nothing executed.[/yellow]")
    #             else:
    #                 self.raw_console.print("[bold yellow]Executing task autonomously...[/bold yellow]")
    #                 run_agent_loop(
    #                     user_input=user_input,
    #                     memory=self.memory,
    #                     current_mode=self.mode,
    #                     console=self.raw_console,
    #                 )

    #             self.raw_console.print("\n[dim]Press Enter to return to BhavAI...[/dim]")
    #             input()
    #     except KeyboardInterrupt:
    #         log.write("[yellow]Task interrupted by user.[/yellow]")
    #         logger.info("TUI task execution interrupted via KeyboardInterrupt.")
    #     except Exception as e:  # noqa: BLE001
    #         log.write(f"[bold red]Unexpected Error:[/bold red] {e}")
    #         logger.exception("TUI session encountered unexpected error: %s", e)
    #     else:
    #         log.write("[dim]\u2713 Task complete — back in BhavAI.[/dim]")


def main() -> None:
    BhavAI().run()


if __name__ == "__main__":
    main()
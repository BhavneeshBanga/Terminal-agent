import click
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from bhavai.config import get_config_summary, CWD, logger
from bhavai.context import get_folder_tree_string
from bhavai.memory import ConversationMemory
from bhavai.modes import AgentMode, prompt_and_confirm_plan
from bhavai.agent import run_agent_loop

console = Console()

@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """BhavAI - A production-ready, personal AI agent in your terminal."""
    if ctx.invoked_subcommand is None:
        console.print("[bold red]Error:[/bold red] Missing command. Use [green]bhav wake up[/green] to activate the agent.")
        sys.exit(1)




# @main.command()
# @click.argument("action", default="up")
# def wake(action):
#     """Activates the agent in the current working directory."""
#     if action != "up":
#         console.print(f"[bold red]Error:[/bold red] Invalid action '{action}'. Did you mean [green]bhav wake up[/green]?")
#         sys.exit(1)
        
#     # Load configuration
#     cfg = get_config_summary()
    
#     # Check for API key
#     if not cfg["API_KEY_PRESENT"]:
#         console.print(Panel(
#             "[bold red]API KEY MISSING[/bold red]\n\n"
#             "Please create a [bold].env[/bold] file in this folder or set the [bold]SARVAM_API_KEY[/bold] environment variable.\n"
#             "Visit https://dashboard.sarvam.ai/ to get your subscription key.",
#             title="BhavAI - Setup Required",
#             border_style="red"
#         ))
#         sys.exit(1)
        
#     # Print beautiful activation banner
#     import time
#     R   = "\033[0m"
#     YEL = "\033[1;93m"
#     BOLD= "\033[1m"
#     YEL = "\033[1;93m"
#     GOLD= "\033[33m"

#     def typewrite(text, delay=0.015, color=""):
#         for ch in text:
#             sys.stdout.write(color + ch + R)
#             sys.stdout.flush()
#             time.sleep(delay)
#         print()
#     import os
#     def clear():
#         os.system("cls" if os.name == "nt" else "clear")

#     clear()
#     print(YEL + "▄" * 58 + R)
#     print()
#     # logo = [
#     # r" ██████╗ ██╗  ██╗ █████╗ ██╗   ██╗ █████╗ ██╗    ████████╗███████╗██████╗ ███╗   ███╗██╗███╗   ██╗ █████╗ ██╗",
#     # r" ██╔══██╗██║  ██║██╔══██╗██║   ██║██╔══██╗██║       ██╔══╝██╔════╝██╔══██╗████╗ ████║██║████╗  ██║██╔══██╗██║",
#     # r" ██████╔╝███████║███████║██║   ██║███████║██║       ██║   █████╗  ██████╔╝██╔████╔██║██║██╔██╗ ██║███████║██║",
#     # r" ██╔══██╗██╔══██║██╔══██║╚██╗ ██╔╝██╔══██║██║       ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██║██║╚██╗██║██╔══██║██║",
#     # r" ██████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║  ██║██║       ██║   ███████╗██║  ██║██║ ╚═╝ ██║██║██║ ╚████║██║  ██║███████╗",
#     # r" ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═╝       ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝",
#     # ]
#     logo = [
#         r" ██████╗ ██╗  ██╗ █████╗ ██╗   ██╗ █████╗ ██╗    ████████╗███████╗██████╗ ███╗   ███╗██╗███╗   ██╗ █████╗ ██╗        █████╗  ██████╗ ███████╗███╗   ██╗████████╗",
#         r" ██╔══██╗██║  ██║██╔══██╗██║   ██║██╔══██╗██║       ██╔══╝██╔════╝██╔══██╗████╗ ████║██║████╗  ██║██╔══██╗██║       ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝",
#         r" ██████╔╝███████║███████║██║   ██║███████║██║       ██║   █████╗  ██████╔╝██╔████╔██║██║██╔██╗ ██║███████║██║       ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ",
#         r" ██╔══██╗██╔══██║██╔══██║╚██╗ ██╔╝██╔══██║██║       ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██║██║╚██╗██║██╔══██║██║       ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ",
#         r" ██████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║  ██║██║       ██║   ███████╗██║  ██║██║ ╚═╝ ██║██║██║ ╚████║██║  ██║██████╗   ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ",
#         r" ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═╝       ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═════╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ",
#     ]
#     for line in logo:
#         print(GOLD + BOLD + line + R)
#     print()
#     typewrite("  ⚡  Terminal Mode — Bhavneesh ke liye  ⚡", delay=0.022, color=GOLD + BOLD)
#     print(YEL + "▀" * 58 + R)
#     print()

#     banner_text = (
#         f"🚀 [bold green]BhavAI Activated Successfully![/bold green]\n\n"
#         f"📍 [bold]Location:[/bold] {cfg['CWD']}\n"
#         f"⚙️ [bold]Model:[/bold] {cfg['MODEL']}\n"
#         f"🛡️ [bold]Initial Mode:[/bold] [bold cyan]Plan Mode[/bold cyan] (Default)\n"
#         f"📝 [bold]Logs Path:[/bold] {cfg['LOG_FILE']}\n\n"
#         f"[dim]Type your requests below. Use 'mode agent' or 'mode plan' to toggle modes, 'exit' or 'quit' to close.[/dim]"
#     )
#     console.print(Panel(banner_text, title="BhavAI Personal Terminal Agent", border_style="green"))
    
#     # Print initial folder tree
#     console.print("\n[bold]Current Directory Structure:[/bold]")
#     try:
#         tree_str = get_folder_tree_string(CWD)
#         console.print(tree_str)
#     except Exception as e:
#         console.print(f"[yellow]Warning: Could not build folder tree: {e}[/yellow]")
#     console.print()
    
#     # Initialize session state
#     current_mode = AgentMode.PLAN
#     memory = ConversationMemory()
    
#     # Interactive REPL Loop
#     while True:
#         try:
#             # Styled prompt input
#             mode_color = "cyan" if current_mode == AgentMode.PLAN else "yellow"
#             prompt_label = f"[bold {mode_color}]({current_mode})[/bold {mode_color}] > "
#             user_input = Prompt.ask(prompt_label).strip()
            
#             if not user_input:
#                 continue
                
#             # Mode switching command
#             if user_input.lower() == "mode agent":
#                 current_mode = AgentMode.AGENT
#                 console.print("[yellow]Switched to Agent Mode (Tasks will execute autonomously).[/yellow]")
#                 continue
#             elif user_input.lower() == "mode plan":
#                 current_mode = AgentMode.PLAN
#                 console.print("[cyan]Switched to Plan Mode (Tasks will show a checklist plan first).[/cyan]")
#                 continue
                
#             # Exit conditions
#             if user_input.lower() in ("exit", "quit"):
#                 console.print("[green]Goodbye from BhavAI! Waking down...[/green]")
#                 break
                
#             # Task Execution
#             if current_mode == AgentMode.PLAN:
#                 # 1. Generate and confirm plan
#                 folder_tree = get_folder_tree_string(CWD)
#                 should_proceed, plan_steps = prompt_and_confirm_plan(user_input, folder_tree, console)
                
#                 # 2. Run agent loop if approved
#                 if should_proceed:
#                     console.print("[bold green]Plan approved. Executing step-by-step...[/bold green]")
#                     run_agent_loop(
#                         user_input=user_input,
#                         memory=memory,
#                         current_mode=current_mode,
#                         plan_steps=plan_steps,
#                         console=console
#                     )
#             else: # Agent Mode (autonomous execution)
#                 console.print("[bold yellow]Executing task autonomously...[/bold yellow]")
#                 run_agent_loop(
#                     user_input=user_input,
#                     memory=memory,
#                     current_mode=current_mode,
#                     console=console
#                 )
                
#             console.print() # Print trailing spacing after task complete
            
#         except KeyboardInterrupt:
#             console.print("\n[yellow]Task interrupted by user. Returning to prompt...[/yellow]")
#             logger.info("REPL session task execution interrupted via KeyboardInterrupt.")
#         except Exception as e:
#             console.print(f"[bold red]Unexpected Error:[/bold red] {e}")
#             logger.exception("REPL session encountered unexpected error: %s", e)

# if __name__ == "__main__":
#     main()



from bhavai.tui import BhavAI

@main.command()
@click.argument("action", default="up")
def wake(action):
    if action != "up":
        console.print(f"[bold red]Error:[/bold red] Invalid action '{action}'.")
        sys.exit(1)
    BhavAI().run()
import json
import re
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from bhavai.config import logger
from bhavai.llm import query_llm

class AgentMode:
    PLAN = "plan"
    AGENT = "agent"

def generate_plan(user_input: str, folder_tree: str, feedback: str = None) -> list:
    """
    Queries Sarvam-105B to generate a step-by-step plan for the user task.
    Supports feeding back refinement instructions.
    """
    system_prompt = (
        "You are BhavAI, a planning assistant. Your job is to break down the user's task into a sequential, "
        "numbered plan of action. Do not run any tools yet. Show what tools you intend to use at each step.\n\n"
        "You MUST reply in a strict JSON format containing a single key 'plan' which is a list of step strings. "
        "Do not include any text, headers, or markdown formatting before or after the JSON payload.\n"
        "Example output:\n"
        "{\n"
        '  "plan": [\n'
        '    "Read README.md using read_file to check existing installation instructions",\n'
        '    "Add Installation section using update_file with pip install instructions"\n'
        "  ]\n"
        "}"
    )
    
    user_prompt = f"Current folder structure:\n{folder_tree}\n\nUser task: {user_input}"
    if feedback:
        user_prompt += f"\n\nUser feedback to adjust the plan: {feedback}"
        
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    raw_response = ''
    
    try:
        raw_response = query_llm(messages)
        # Parse JSON from response
        # Strip markdown formatting just in case
        clean_json = raw_response.strip()
        if clean_json.startswith("```"):
            # Try to extract content inside code block
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", clean_json, re.DOTALL)
            if match:
                clean_json = match.group(1).strip()
                
        # If no markdown blocks, find first { and last }
        if not (clean_json.startswith("{") and clean_json.endswith("}")):
            start_idx = clean_json.find("{")
            end_idx = clean_json.rfind("}")
            if start_idx != -1 and end_idx != -1:
                clean_json = clean_json[start_idx:end_idx+1]
                
        plan_data = json.loads(clean_json)
        return plan_data.get("plan", [f"Execute user request: {user_input}"])
    except Exception as e:
        logger.error("Failed to generate or parse plan: %s. Raw response: %s", e, raw_response)
        # Fallback plan if LLM parsing fails
        return [
            f"Analyze folder tree and context.",
            f"Execute requested task: {user_input}"
        ]

def prompt_and_confirm_plan(user_input: str, folder_tree: str, console: Console) -> tuple[bool, list]:
    """
    Shows the step-by-step plan to the user in the terminal and waits for approval.
    Allows user to confirm (y), cancel (n), or input feedback to regenerate the plan.
    Returns (should_proceed, plan_steps).
    """
    feedback = None
    while True:
        with console.status("[bold blue]Generating plan...", spinner="dots"):
            plan_steps = generate_plan(user_input, folder_tree, feedback)
            
        console.print("\n[bold cyan]Here's my plan:[/bold cyan]")
        for idx, step in enumerate(plan_steps, 1):
            console.print(f" [bold cyan]{idx}.[/bold cyan] {step}")
        console.print()
        
        ans = Prompt.ask(
            "[bold yellow]Proceed?[/bold yellow] ([green]y[/green] to proceed, [red]n[/red] to cancel, or type feedback to edit the plan)"
        ).strip()
        
        if ans.lower() == 'y':
            return True, plan_steps
        elif ans.lower() in ('n', 'no', ''):
            console.print("[yellow]Plan execution cancelled.[/yellow]")
            return False, []
        else:
            # if  user provided feedback to adjust the plan
            feedback = ans
            console.print(f"[blue]Updating plan based on feedback: '{feedback}'...[/blue]")

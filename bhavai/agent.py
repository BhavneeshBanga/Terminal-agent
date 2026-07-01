"""
agent.py — BhavAI Core ReAct Loop

Architecture for 4096-token LLM output limit
=============================================
The Sarvam-105B model has a hard 4096-token output limit.
This file implements a 5-layer defence (was 4 in v1):

  Layer 1 — System prompt teaches the model to CHUNK large writes
             (never write more than 50 lines per tool call).

  Layer 2 — write_file / append_chunk tools enforce chunked writing.

  Layer 3 — query_llm_with_continuation() in llm.py automatically
             stitches together responses that hit max_tokens.
             THIS IS THE NEW LAYER — directly answers the question:
             "agar 4096 cross kare toh dubara call lagao aur append karo"

  Layer 4 — JSON repair pipeline (_fix_truncated_json) handles any
             remaining partial JSON after continuation.

  Layer 5 — Recovery feedback message tells the model exactly what went
             wrong and how to fix it before the next attempt.
"""

import json
import re
from rich.console import Console
from rich.panel import Panel
from bhavai.config import CWD, logger
from bhavai.context import get_folder_tree_string
from bhavai.llm import query_llm_with_continuation   # ← NEW: use continuation
from bhavai.memory import ConversationMemory
from bhavai.tools import TOOL_DISPATCH

# ─────────────────────────────────────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are BhavAI, a personal AI agent running inside the terminal.
Activated folder: {cwd}

Current folder structure:
{folder_tree}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVAILABLE TOOLS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- list_folder   → {{"path": "string (default '.')"}}
- read_file     → {{"path": "string"}}
- write_file    → {{"path": "string", "content": "string"}}
    Use ONLY for short files (< 60 lines). For larger files use append_chunk.
- append_chunk  → {{"path": "string", "chunk": "string", "done": true|false}}
    Appends one chunk to a file. Set done=true on the LAST chunk only.
    Use this for ANY file > 60 lines by splitting into chunks of ≤50 lines each.
- run_command   → {{"command": "string"}}
    Safe read-only shell commands only (git status, ls, cat …).
- search_code   → {{"query": "string", "path": "string (default '.')", "regex": true|false, "case_sensitive": true|false}}
    Grep-like search across the project. Use this FIRST when asked "where is X
    used/defined" instead of reading files one by one.
- find_files    → {{"pattern": "string (glob, e.g. '*.py')", "path": "string (default '.')"}}
    Locates files by name pattern without reading the whole tree.
- get_outline   → {{"path": "string"}}
    Returns function/class signatures + line numbers for a file WITHOUT its
    full content. Use this before read_file when you just need to navigate.
- list_todos    → {{"path": "string (default '.')"}}
    Scans for TODO / FIXME / HACK / XXX / BUG comments across the project.
- get_diff      → {{"path": "string (optional — omit for whole workspace)"}}
    Shows git diff HEAD — what BhavAI has actually changed so far.
- check_dependencies → {{"path": "string (default '.')"}}
    Parses requirements.txt / pyproject.toml / package.json and reports which
    declared dependencies are missing from the environment, with the install
    command to fix it. Run this before executing code that imports packages.
- rename_path   → {{"source": "string", "destination": "string"}}
    Moves/renames a file or folder. Refuses to overwrite an existing
    destination. This is the ONLY way to reorganize files — there is no
    delete tool, by design.
- fetch_url     → {{"url": "string", "max_chars": "int (default 8000)"}}
    Fetches real documentation/API reference/Stack Overflow pages so you can
    answer from ground truth instead of guessing library APIs from memory.
- get_function_source → {{"path": "string", "function_name": "string"}}
    Returns ONE function's exact source + line numbers, found via AST. Use
    this instead of read_file when you only need to inspect one function.
- insert_function → {{"path": "string", "new_source": "string"}}
    Appends a brand-new top-level function to the end of a Python file.
    new_source must be a complete, syntactically valid function definition.
    Use this only when the function does NOT already exist.
- replace_function → {{"path": "string", "function_name": "string", "new_source": "string"}}
    Replaces an existing top-level function's full source, located precisely
    via AST line numbers. new_source must be a complete, syntactically valid
    replacement function. Use get_function_source first if you need to see
    the current body before rewriting it.
- final_answer  → {{"answer": "string"}}
    Call this when the entire task is complete.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT RULES  (never break these)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. NEVER delete files or directories.
2. Stay inside {cwd} — all paths are sandboxed.
3. Blocked commands: rm, rmdir, del, unlink, shutil.rmtree, os.remove, format, mkfs, drop table.
4. Work step-by-step; show reasoning in "thought".
5. Call final_answer when done.
6. NEVER attempt to read .env, .env.local, .env.example, .env.*, credentials.json or any
   secrets file. These are permanently blocked.
7. Prefer search_code / find_files / get_outline over read_file when you only need to
   locate something — this saves tokens and avoids dumping whole files into context.
8. There is no delete tool, on purpose. To reorganize files use rename_path, never run_command
   with rm/mv shell tricks (they will be blocked anyway).
9. To add or change a SINGLE function in an existing Python file, prefer insert_function /
   replace_function over write_file or append_chunk — they only touch that one function via
   AST, so the rest of the file (and your token budget) is untouched.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠  OUTPUT TOKEN BUDGET — READ CAREFULLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your maximum output is 4096 tokens (~3000 words).
A JSON wrapper costs ~50 tokens, leaving ~3000 tokens for file content.
That is roughly 200 lines of code — but DO NOT write 200 lines at once.

GOLDEN RULE → MAXIMUM 50 LINES OF CODE PER TOOL CALL.

For ANY file longer than 50 lines you MUST use append_chunk like this:

  Step 1:  append_chunk  path="app.py"  chunk="<lines 1-50>"    done=false
  Step 2:  append_chunk  path="app.py"  chunk="<lines 51-100>"  done=false
  Step 3:  append_chunk  path="app.py"  chunk="<lines 101-120>" done=true

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE FORMAT  (raw JSON only — no markdown fences, no extra text)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "thought": "brief reasoning about what you are about to do",
  "tool_name": "one of the tool names above",
  "tool_args": {{
    "arg_name": "arg_value"
  }}
}}

Inside JSON strings:  newline → \\n   quote → \\"   backslash → \\\\
"""


# ─────────────────────────────────────────────────────────────────────────────
# JSON Cleaning Pipeline (unchanged from v1 — still needed as safety net)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json_block(text: str) -> str:
    """Strip <think> tags, markdown fences, and pull the outermost { … }."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1).strip()

    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    return text


def _escape_control_chars(text: str) -> str:
    """
    Walk raw JSON text character-by-character.
    Inside string literals convert bare control chars to escape sequences.
    """
    result    = []
    in_string = False
    i         = 0
    n         = len(text)

    while i < n:
        ch = text[i]

        if in_string:
            if ch == "\\":
                result.append(ch)
                i += 1
                if i < n:
                    result.append(text[i])
                    i += 1
                continue
            elif ch == '"':
                in_string = False
                result.append(ch)
            elif ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            elif ch == "\t":
                result.append("\\t")
            elif ord(ch) < 0x20:
                result.append(f"\\u{ord(ch):04x}")
            else:
                result.append(ch)
        else:
            if ch == '"':
                in_string = True
                result.append(ch)
            else:
                result.append(ch)

        i += 1

    return "".join(result)


def _fix_truncated_json(text: str) -> str:
    """
    Attempt to repair JSON that was cut off mid-string.
    Tries json.loads first; on 'Unterminated string' walks the text to close
    open strings/braces/brackets.
    """
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError as e:
        if "Unterminated string" not in str(e):
            return text

    depth_braces   = 0
    depth_brackets = 0
    in_string      = False
    i              = 0
    n              = len(text)

    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                depth_braces += 1
            elif ch == '}':
                depth_braces -= 1
            elif ch == '[':
                depth_brackets += 1
            elif ch == ']':
                depth_brackets -= 1
        i += 1

    suffix = []
    if in_string:
        suffix.append('"')
    suffix.extend(']' * depth_brackets)
    suffix.extend('}' * depth_braces)

    repaired = text + "".join(suffix)
    try:
        json.loads(repaired)
        logger.info("_fix_truncated_json: successfully repaired truncated JSON.")
        return repaired
    except json.JSONDecodeError:
        return text


def clean_json_text(raw_text: str) -> str:
    """Full pipeline: extract → escape → attempt repair."""
    text = _extract_json_block(raw_text)
    text = _escape_control_chars(text)
    text = _fix_truncated_json(text)
    return text


def parse_llm_json(raw_text: str) -> dict:
    """
    Parses LLM output into a dict.
    Raises ValueError with an actionable message on failure.
    """
    cleaned = clean_json_text(raw_text)
    logger.debug("parse_llm_json cleaned: %r", cleaned[:400])

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("JSON parse failed: %s | cleaned=%r", e, cleaned[:500])
        raise ValueError(
            f"Invalid JSON — {e.msg} at line {e.lineno} col {e.colno}. "
            f"Your response was likely cut off due to the 4096-token output limit. "
            f"FIX: Use append_chunk with ≤50 lines per call instead of one large write."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_args(args: dict) -> str:
    """Short display of tool args — truncates long content values."""
    if not isinstance(args, dict):
        return str(args)
    parts = []
    for k, v in args.items():
        sv = str(v)
        if len(sv) > 60:
            parts.append(f'{k}=<{len(sv)} chars>')
        else:
            parts.append(f'{k}="{sv}"')
    return ", ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Main ReAct Loop
# ─────────────────────────────────────────────────────────────────────────────

def run_agent_loop(
    user_input:   str,
    memory:       ConversationMemory,
    current_mode: str,
    plan_steps:   list = None,
    max_steps:    int  = 30,
    console:      Console = None,
) -> str:
    """
    Executes the ReAct (Reason → Act → Observe) loop.

    Key change from v1
    ------------------
    Uses query_llm_with_continuation() instead of query_llm().
    If the LLM hits the 4096-token wall mid-response, the continuation
    loop in llm.py automatically fetches the rest and stitches it together
    BEFORE we attempt JSON parsing. This means the JSON repair pipeline
    (Layer 4) now only needs to handle edge cases, not the common case.
    """
    # if console is None:
    #     console = Console()

    task_prompt = user_input
    if plan_steps:
        steps_str   = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan_steps))
        task_prompt = (
            f"Task: {user_input}\n\n"
            f"Approved plan:\n{steps_str}\n\n"
            "REMINDER: For any file > 50 lines use append_chunk (≤50 lines per call)."
        )

    memory.add_message("user", task_prompt)

    step_count            = 0
    consecutive_json_errs = 0
    calls = 0
    while step_count < max_steps:
        step_count += 1
        logger.info("ReAct step %d/%d", step_count, max_steps)

        folder_tree   = get_folder_tree_string(CWD)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            cwd=str(CWD),
            folder_tree=folder_tree,
        )

        raw_response = ""
        with console.status("[bold blue]Thinking…[/bold blue]", spinner="dots"):
            try:
                messages     = memory.get_messages(system_prompt)
                # print("messages", messages)
                # ── KEY CHANGE: continuation instead of single-shot ──────── #
                # raw_response = query_llm_with_continuation(messages)
                raw_response = query_llm_with_continuation(messages, calls=calls % 4)
            except Exception as exc:
                err = f"LLM Error: {exc}"
                console.print(f"[bold red]{err}[/bold red]")
                logger.error(err)
                return err

        if not raw_response:
            err = "LLM returned an empty response. Please try again."
            console.print(f"[bold red]{err}[/bold red]")
            logger.error(err)
            return err

        try:
            parsed = parse_llm_json(raw_response)
            consecutive_json_errs = 0
        except ValueError as exc:
            consecutive_json_errs += 1
            explanation = str(exc)
            console.print(
                f"[bold red]JSON Parse Error "
                f"({consecutive_json_errs}/3):[/bold red] {explanation}"
            )
            logger.warning("Malformed JSON step %d: %r", step_count, raw_response[:300])

            if consecutive_json_errs >= 3:
                msg = ("Aborting: 3 consecutive JSON errors. "
                       "Try a simpler task or break it into smaller steps.")
                console.print(f"[bold red]{msg}[/bold red]")
                return msg

            memory.add_message("assistant", raw_response)
            memory.add_message(
                "user",
                f"ERROR: Your response could not be parsed as JSON.\n"
                f"Reason: {explanation}\n\n"
                f"This almost always means your response was cut off at the 4096-token limit.\n"
                f"ACTION REQUIRED:\n"
                f"  • Do NOT retry the same large write_file call.\n"
                f"  • Use append_chunk instead with ≤50 lines per chunk.\n"
                f"  • First chunk: append_chunk path=... chunk='<lines 1-50>' done=false\n"
                f"  • Continue until the file is complete, then set done=true.\n"
                f"Reply with a valid JSON object following the response schema."
            )
            continue

        thought   = parsed.get("thought", "")
        tool_name = parsed.get("tool_name", "")
        tool_args = parsed.get("tool_args", {})

        if thought:
            console.print(Panel(
                f"[dim italic]{thought}[/dim italic]",
                title="[bold]💭 BhavAI Thought[/bold]",
                title_align="left",
                border_style="dim",
            ))

        if not tool_name:
            memory.add_message("assistant", raw_response)
            memory.add_message("user",
                "Error: 'tool_name' is missing from your JSON. "
                "Please include it in your next response.")
            continue

        if tool_name == "final_answer":
            answer = tool_args.get("answer", "Task complete.")
            console.print("\n[bold green]✅ BhavAI Final Answer:[/bold green]")
            console.print(answer)
            console.print()
            memory.add_message("assistant", raw_response)
            return answer

        if tool_name in TOOL_DISPATCH:
            tool_func    = TOOL_DISPATCH[tool_name]
            args_display = _fmt_args(tool_args)
            with console.status(
                f"[bold blue][TOOL][/bold blue] "
                f"[bold green]{tool_name}[/bold green]({args_display})…",
                spinner="dots"
            ):
                try:
                    result = tool_func(**tool_args) if isinstance(tool_args, dict) else tool_func()
                except Exception as exc:
                    result = f"Tool error — {tool_name}: {exc}"
                    logger.error("Tool crash %s: %s", tool_name, exc)
        else:
            result = (f"Error: Unknown tool '{tool_name}'. "
                      f"Available: {list(TOOL_DISPATCH.keys())}")
            logger.warning("Unknown tool: %s", tool_name)

        console.print(Panel(
            str(result),
            title=f"[bold]🔍 Observation — {tool_name}[/bold]",
            title_align="left",
            border_style="blue",
        ))

        memory.add_message("assistant", raw_response)
        memory.add_message("system", f"Observation from {tool_name}:\n{result}")

        calls = calls + 1
        


        from bhavai.core.messages import get_last_n_tools
        last_3_tools = get_last_n_tools(messages)
        if last_3_tools == [
            "read_file",
            "read_file",
            "read_file"
        ]:
            memory.add_message(
                "system",
                "The file is empty. Stop reading it again. Proceed with creating new content."
            )

    timeout_msg = (f"ReAct loop hit {max_steps}-step limit. "
                   "Task may be incomplete — try a more specific request.")
    console.print(f"[bold red]⚠  {timeout_msg}[/bold red]")
    return timeout_msg
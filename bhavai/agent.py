"""
agent.py — BhavAI Core ReAct Loop

Architecture for 4096-token LLM output limit
=============================================
The Sarvam-105B model has a hard 4096-token (~3000 word) output limit.
When the agent tries to write a large file in one shot, the JSON response
gets cut off mid-string → JSONDecodeError: Unterminated string.

This file implements a 4-layer defence:

  Layer 1 — System prompt teaches the model to CHUNK large writes
             (never write more than 60 lines per tool call).
             The model itself avoids the problem.

  Layer 2 — write_file / append_chunk tools in tools.py enforce chunked
             writing. A new `append_chunk` tool is purpose-built for this.

  Layer 3 — JSON repair pipeline (_fix_truncated_json) stitches together
             cut-off responses so a single bad step doesn't abort the task.

  Layer 4 — The recovery feedback message tells the model EXACTLY what
             went wrong and how to fix it before the next attempt.
"""

import json
import re
from rich.console import Console
from rich.panel import Panel
from bhavai.config import CWD, logger
from bhavai.context import get_folder_tree_string
from bhavai.llm import query_llm
from bhavai.memory import ConversationMemory
from bhavai.tools import TOOL_DISPATCH

# ─────────────────────────────────────────────────────────────────────────────
# System Prompt  (token-budget-aware instructions baked in)
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
   secrets file. These are permanently blocked. If you need config info, ask the user instead.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠  OUTPUT TOKEN BUDGET — READ CAREFULLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your maximum output is 4096 tokens (~3000 words).
A JSON wrapper costs ~50 tokens, leaving ~3000 tokens for file content.
That is roughly 200 lines of code — but DO NOT write 200 lines at once.

GOLDEN RULE → MAXIMUM 50 LINES OF CODE PER TOOL CALL.

For ANY file longer than 50 lines you MUST use append_chunk like this:

  Step 1:  append_chunk  path="app.py"  chunk="<lines 1-50>"   done=false
  Step 2:  append_chunk  path="app.py"  chunk="<lines 51-100>" done=false
  Step 3:  append_chunk  path="app.py"  chunk="<lines 101-120>" done=true

Never try to write an entire HTML/CSS/JS file in one call — it WILL be cut off.

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
# JSON Cleaning Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json_block(text: str) -> str:
    """Strip <think> tags, markdown fences, and pull the outermost { … }."""
    # 1. Remove chain-of-thought tags (DeepSeek / some Sarvam variants emit these)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    # 2. Strip ```json … ``` fences
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1).strip()

    # 3. Pull outermost { … }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    return text


def _escape_control_chars(text: str) -> str:
    """
    Walk the raw JSON text character-by-character.
    Inside string literals convert bare control chars to escape sequences
    so json.loads won't choke on literal newlines inside strings.
    Already-valid escape sequences (\\n written by the model) are left alone.
    """
    result    = []
    in_string = False
    i         = 0
    n         = len(text)

    while i < n:
        ch = text[i]

        if in_string:
            if ch == "\\":                    # start of an escape sequence
                result.append(ch)
                i += 1
                if i < n:
                    result.append(text[i])    # escaped char — keep as-is
                    i += 1
                continue
            elif ch == '"':                   # closing quote
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
    *** The core fix for the 4096-token cutoff bug ***

    When the LLM response is cut off mid-string the JSON is syntactically
    broken.  This function:
      1. Tries json.loads — if OK, returns immediately.
      2. On 'Unterminated string' error, walks the text tracking string/brace
         depth, closes the open string with '"', closes open brackets/braces.
      3. Returns repaired (truncated but parseable) JSON.

    The agent loop then feeds a clear recovery message back to the LLM so
    it knows to redo the step with smaller chunks.
    """
    try:
        json.loads(text)
        return text                          # already valid
    except json.JSONDecodeError as e:
        if "Unterminated string" not in str(e):
            return text                      # different error — don't modify

    # Walk to find unclosed string / open braces
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
            elif ch == '"':
                in_string = False
        else:
            if   ch == '"': in_string      = True
            elif ch == "{": depth_braces   += 1
            elif ch == "}": depth_braces   -= 1
            elif ch == "[": depth_brackets += 1
            elif ch == "]": depth_brackets -= 1
        i += 1

    repair = text.rstrip("\\")              # trailing backslash would break \"
    if in_string:
        repair += '"'                        # close the open string
    repair += "]" * max(0, depth_brackets)
    repair += "}" * max(0, depth_braces)

    logger.warning("Repaired truncated JSON (closed %d brace(s), in_string=%s)",
                   depth_braces, in_string)
    return repair


def clean_json_text(text: str) -> str:
    """Full cleaning pipeline: extract → escape → repair."""
    text = _extract_json_block(text)
    text = _escape_control_chars(text)
    text = _fix_truncated_json(text)
    return text


def parse_llm_json(raw_text: str) -> dict:
    """
    Clean and parse LLM output.
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
    max_steps:    int  = 30,           # bumped up — chunked writes use more steps
    console:      Console = None,
) -> str:
    """
    Executes the ReAct (Reason → Act → Observe) loop.

    Each iteration:
      1. Builds the system prompt with a fresh folder tree.
      2. Calls the LLM.
      3. Parses the JSON response (with repair if truncated).
      4. Runs the requested tool.
      5. Feeds the observation back into memory.
      6. Repeats until final_answer or max_steps.
    """
    if console is None:
        console = Console()

    # ── Build initial task message ──────────────────────────────────────── #
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

    while step_count < max_steps:
        step_count += 1
        logger.info("ReAct step %d/%d", step_count, max_steps)

        # ── Build system prompt ─────────────────────────────────────────── #
        folder_tree   = get_folder_tree_string(CWD)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            cwd=str(CWD),
            folder_tree=folder_tree,
        )

        # ── Query LLM ──────────────────────────────────────────────────── #
        raw_response = ""   # initialise so it is always bound even if query fails
        with console.status("[bold blue]Thinking…[/bold blue]", spinner="dots"):
            try:
                messages     = memory.get_messages(system_prompt)
                raw_response = query_llm(messages)
            except Exception as exc:
                err = f"LLM Error: {exc}"
                console.print(f"[bold red]{err}[/bold red]")
                logger.error(err)
                return err

        # Guard: query_llm returned empty string (should not happen, but be safe)
        if not raw_response:
            err = "LLM returned an empty response. Please try again."
            console.print(f"[bold red]{err}[/bold red]")
            logger.error(err)
            return err

        # ── Parse JSON ─────────────────────────────────────────────────── #
        try:
            parsed= parse_llm_json(raw_response)
            consecutive_json_errs = 0          # reset on success
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

            # Tell the LLM exactly what went wrong and how to fix it
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

        # ── Extract fields ─────────────────────────────────────────────── #
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

        # ── final_answer ───────────────────────────────────────────────── #
        if tool_name == "final_answer":
            answer = tool_args.get("answer", "Task complete.")
            console.print("\n[bold green]✅ BhavAI Final Answer:[/bold green]")
            console.print(answer)
            console.print()
            memory.add_message("assistant", raw_response)
            return answer

        # ── Execute tool ───────────────────────────────────────────────── #
        if tool_name in TOOL_DISPATCH:
            tool_func   = TOOL_DISPATCH[tool_name]
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
        memory.add_message("user", f"Observation from {tool_name}:\n{result}")

    timeout_msg = (f"ReAct loop hit {max_steps}-step limit. "
                   "Task may be incomplete — try a more specific request.")
    console.print(f"[bold red]⚠  {timeout_msg}[/bold red]")
    return timeout_msg
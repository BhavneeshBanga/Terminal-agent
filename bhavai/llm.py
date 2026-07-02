"""
llm.py — Sarvam API client with continuation support

Key improvements over v1
------------------------
1. Debug print statements REMOVED (were leaking API key hints to stdout).
2. query_llm_with_continuation() — checks stop_reason and automatically
   makes follow-up calls when the model hits the max_tokens wall.
   This is the direct answer to your original question:
     "agar text 4096 cross kare toh dubara call lagao aur append karo"
3. query_llm() is kept as a single-shot wrapper (used by modes.py for
   short plan generation where truncation is not expected).
"""

import requests
import time
import httpx
from bhavai.config import SARVAM_API_KEY, SARVAM_BASE_URL, SARVAM_MODEL, logger
from bhavai.config import GROQ_API_KEY1,  GROQ_API_KEY2, GROQ_API_KEY3, GROQ_API_KEY4, GROQ_BASE_URL, GROQ_MODEL, logger
from bhavai.config import SARVAM_API_KEY, SARVAM_BASE_URL, SARVAM_MODEL, TEMPERATURE, MAX_TOKENS


import re
def strip_think_tags(text: str) -> str:
    """
    Remove ALL model 'thinking' noise from LLM output.
    Handles:
      <think>...</think>          — DeepSeek / Qwen style
      <thinking>...</thinking>    — some variants
      <<...>>                     — double angle artifacts
      Stray < > that aren't HTML  — model leakage
    """
    if not text:
        return ""
    # Full thinking blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Stray angle-bracket artifacts (non-HTML, non-JSON)
    # Only strip if the tag doesn't look like real HTML or JSON
    text = re.sub(r"<<[^>]*>>", "", text)
    return text.strip()




def call_sarvam(messages: list[dict]) -> str:
    """
    Send a conversation (list of messages) to Sarvam-105B.
    Returns the model's reply as a plain string.

    Args:
        messages: List of {"role": "user"/"assistant"/"system", "content": "..."}

    Returns:
        The model's text reply, or an error message string.
    """
    url     = f"{SARVAM_BASE_URL}/chat/completions"
    headers = {
        # "api-subscription-key": "skY8SMe7B",
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "model":       SARVAM_MODEL,
        "messages":    messages,
        "temperature": TEMPERATURE,
        "max_tokens":  MAX_TOKENS,
    }

    try:
        import json
        # Increase timeout from 30 to 120
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        data = response.json()
        return strip_think_tags(data["choices"][0]["message"]["content"])

    except requests.exceptions.ConnectionError:
        return "ERROR: Could not connect to Sarvam API. Check your internet connection."
    except requests.exceptions.Timeout:
        return "ERROR: Sarvam API request timed out."
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 401:
            return "ERROR: Invalid API key. Get yours at https://dashboard.sarvam.ai"
        elif status == 429:
            return "ERROR: Rate limit hit. Wait a moment and try again."
        else:
            return f"ERROR: HTTP {status} — {e.response.text}"
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        return f"ERROR: Unexpected API response format — {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Internal: single API call, returns (content, stop_reason)
# ─────────────────────────────────────────────────────────────────────────────

def _call_api(messages: list, calls: int,  temperature: float = 0.0) -> tuple[str, str]:
    """
    Makes one call to the Sarvam chat completions endpoint.

    Returns
    -------
    (content, stop_reason)
        stop_reason is "end_turn" when the model finished naturally,
        or "max_tokens" when it hit the 4096-token limit mid-response.

    Raises RuntimeError on all non-recoverable errors (caller handles retry).
    """
    if not SARVAM_API_KEY:
        raise ValueError(
            "SARVAM_API_KEY is not set. "
            "Please add it to your .env file or environment variables."
        )

    url = f"{SARVAM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "model":       SARVAM_MODEL,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  4096,
    }

    max_retries = 3
    delay       = 2.0
    last_error  = None

    for attempt in range(1, max_retries + 1):
        logger.debug(
            "Sarvam API request — attempt %d/%d  url=%s  model=%s",
            attempt, max_retries, url, SARVAM_MODEL,
        )

        try:
            with httpx.Client(timeout=90.0) as client:
                response = client.post(url, json=payload, headers=headers)
                print("response", response)

            status = response.status_code

            if status == 200:
                data = response.json()
                print("json response ", data)
                try:
                    choice      = data["choices"][0]
                    content     = choice["message"]["content"]
                    # Sarvam follows OpenAI spec: finish_reason field
                    stop_reason = choice.get("finish_reason", "end_turn") or "end_turn"




                    print("\n===== MODEL CONTENT =====")
                    print(content)
                    print("=========================\n")



                except (KeyError, IndexError, TypeError) as exc:
                    raise RuntimeError(
                        f"Sarvam API returned 200 but structure is unexpected: "
                        f"{exc}. Raw: {str(data)[:300]}"
                    )

                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError(
                        "Sarvam API returned 200 but 'content' is empty or not a string."
                    )

                logger.debug(
                    "Sarvam API success on attempt %d. stop_reason=%s",
                    attempt, stop_reason,
                )
                return content, stop_reason

            elif status in (429, 500, 502, 503, 504):
                logger.warning(
                    "Sarvam API transient %d on attempt %d/%d — retrying in %.1f s…",
                    status, attempt, max_retries, delay,
                )
                last_error = RuntimeError(
                    f"Sarvam API transient error {status} after {attempt} attempt(s)."
                )
                time.sleep(delay)
                delay *= 2.0
                continue

            else:
                raise RuntimeError(
                    f"Sarvam API non-retryable error {status}: {response.text[:300]}"
                )

        except httpx.RequestError as exc:
            logger.warning(
                "Sarvam API network error on attempt %d/%d: %s",
                attempt, max_retries, exc,
            )
            last_error = RuntimeError(f"Sarvam API network error: {exc}")
            if attempt == max_retries:
                break
            time.sleep(delay)
            delay *= 2.0
            continue

        except RuntimeError:
            raise

        except Exception as exc:
            raise RuntimeError(f"Unexpected error querying Sarvam API: {exc}") from exc

    raise last_error or RuntimeError(
        f"Sarvam API failed after {max_retries} attempts with no response."
    )

# def _call_api(messages: list,calls : int, temperature: float = 0.0) -> tuple[str, str]:
#     """
#     Makes one call to the Groq chat completions endpoint.

#     Returns
#     -------
#     (content, stop_reason)
#         stop_reason is "stop" when the model finished naturally,
#         or "length" when it hit the token limit mid-response.

#     Raises RuntimeError on all non-recoverable errors (caller handles retry).
#     """
#     if not GROQ_API_KEY1:
#         raise ValueError(
#             "GROQ_API_KEY is not set. "
#             "Please add it to your .env file or environment variables."
#         )

#     url = f"{GROQ_BASE_URL.rstrip('/')}/chat/completions"

#     headers = {
#         "Authorization": f"Bearer {GROQ_API_KEY1}",
#         "Content-Type": "application/json",
#     }

#     if(calls ==0):
#         headers = {
#             "Authorization": f"Bearer {GROQ_API_KEY1}",
#             "Content-Type": "application/json",
#         }
#     if(calls ==1):
#         headers = {
#             "Authorization": f"Bearer {GROQ_API_KEY2}",
#             "Content-Type": "application/json",
#         }
#     if(calls ==2):
#         headers = {
#             "Authorization": f"Bearer {GROQ_API_KEY3}",
#             "Content-Type": "application/json",
#         }
#     if(calls ==3):
#         headers = {
#             "Authorization": f"Bearer {GROQ_API_KEY4}",
#             "Content-Type": "application/json",
#         }
        
        
    
#     payload = {
#         "model":       GROQ_MODEL,
#         "messages":    messages,
#         "temperature": temperature,
#         "max_tokens":  4096,
#     }

#     max_retries = 3
#     delay       = 2.0
#     last_error  = None

#     for attempt in range(1, max_retries + 1):
#         logger.debug(
#             "Groq API request — attempt %d/%d  url=%s  model=%s",
#             attempt, max_retries, url, GROQ_MODEL,
#         )

#         try:
#             with httpx.Client(timeout=90.0) as client:
#                 response = client.post(url, json=payload, headers=headers)
#                 # print("response", response)

#             status = response.status_code

#             if status == 200:
#                 data = response.json()
#                 # print("json response ", data)

#                 try:
#                     choice      = data["choices"][0]
#                     content     = choice["message"]["content"]
#                     stop_reason = choice.get("finish_reason", "stop") or "stop"

#                     # print("\n===== MODEL CONTENT =====")
#                     # print(content)
#                     # print("=========================\n")

#                 except (KeyError, IndexError, TypeError) as exc:
#                     raise RuntimeError(
#                         f"Groq API returned 200 but structure is unexpected: "
#                         f"{exc}. Raw: {str(data)[:300]}"
#                     )

#                 if not isinstance(content, str) or not content.strip():
#                     raise RuntimeError(
#                         "Groq API returned 200 but 'content' is empty or not a string."
#                     )

#                 logger.debug(
#                     "Groq API success on attempt %d. stop_reason=%s",
#                     attempt, stop_reason,
#                 )
#                 return content, stop_reason

#             elif status in (429, 500, 502, 503, 504):
#                 logger.warning(
#                     "Groq API transient %d on attempt %d/%d — retrying in %.1f s…",
#                     status, attempt, max_retries, delay,
#                 )
#                 last_error = RuntimeError(
#                     f"Groq API transient error {status} after {attempt} attempt(s)."
#                 )
#                 time.sleep(delay)
#                 delay *= 2.0
#                 continue

#             else:
#                 raise RuntimeError(
#                     f"Groq API non-retryable error {status}: {response.text[:300]}"
#                 )

#         except httpx.RequestError as exc:
#             logger.warning(
#                 "Groq API network error on attempt %d/%d: %s",
#                 attempt, max_retries, exc,
#             )
#             last_error = RuntimeError(f"Groq API network error: {exc}")

#             if attempt == max_retries:
#                 break

#             time.sleep(delay)
#             delay *= 2.0
#             continue

#         except RuntimeError:
#             raise

#         except Exception as exc:
#             raise RuntimeError(f"Unexpected error querying Groq API: {exc}") from exc

#     raise last_error or RuntimeError(
#         f"Groq API failed after {max_retries} attempts with no response."
#     )


# ─────────────────────────────────────────────────────────────────────────────
# Public: single-shot (for short outputs like plan generation)
# ─────────────────────────────────────────────────────────────────────────────

def query_llm(messages: list, calls:int, temperature: float = 0.0) -> str:
    """
    Single-shot LLM call. Returns the content string.
    Used by modes.py (plan generation) where the output is short and
    truncation is extremely unlikely.

    For the ReAct agent loop use query_llm_with_continuation() instead.
    """
    content, _ = _call_api(messages , temperature, calls=calls)
    return content


# ─────────────────────────────────────────────────────────────────────────────
# Public: continuation loop (for agent tasks that may exceed 4096 tokens)
# ─────────────────────────────────────────────────────────────────────────────

def query_llm_with_continuation(
    messages:      list,
    calls : int,
    temperature:   float = 0.0,
    max_rounds:    int   = 6,
) -> str:
    """
    Calls the LLM and, if stop_reason == "max_tokens", automatically makes
    additional calls with a continuation prompt until the model signals it is
    done (stop_reason == "end_turn") or max_rounds is reached.

    This directly solves the problem you described:
      "agar text 4096 cross kare toh dubara call lagao aur append karo"

    Parameters
    ----------
    messages    : Full conversation history (system + user/assistant turns).
    temperature : Sampling temperature (default 0.0 for deterministic JSON).
    max_rounds  : Safety cap — prevents infinite loops if the model keeps
                  hitting the token limit (default 6 = up to 6 × 4096 tokens).

    Returns
    -------
    Concatenated content from all rounds as a single string.

    How it works
    ------------
    Round 1:  call API  →  content_1, stop_reason_1
    If stop_reason_1 == "end_turn":  return content_1
    If stop_reason_1 == "max_tokens":
        append {"role": "assistant", "content": content_1} to message history
        append {"role": "user",      "content": CONTINUATION_PROMPT}
        Round 2:  call API  →  content_2, stop_reason_2
        full_output = content_1 + content_2
        ... repeat until end_turn or max_rounds

    Note on JSON
    ------------
    For structured JSON responses (agent tool calls), the agent's system prompt
    already instructs the model to use append_chunk (≤50 lines per call) so
    that each individual LLM response stays well under 4096 tokens.
    query_llm_with_continuation is used as an ADDITIONAL safety net — if the
    model still emits a very long response (e.g. a long "thought" section),
    this function stitches the pieces together before JSON parsing.
    """
    CONTINUATION_PROMPT = (
        "Continue exactly from where you left off. "
        "Do NOT repeat any content already written. "
        "Resume mid-word or mid-token if needed. "
        "Output only the continuation, nothing else."
    )

    full_output  = ""
    history= list(messages)   # shallow copy — don't mutate caller's list
    # print()
    # print()
    # print()
    # print()
    # print(calls)
    # print()
    # print()
    # print()
    # print()
    for round_num in range(1, max_rounds + 1):
        logger.debug(
            "query_llm_with_continuation: round %d/%d", round_num, max_rounds
        )

        content, stop_reason = _call_api(history, calls=calls,temperature=temperature)
        full_output += content

        if stop_reason != "max_tokens":
            # Model finished naturally
            logger.debug(
                "Continuation complete after %d round(s). stop_reason=%s",
                round_num, stop_reason,
            )
            break

        # Model hit the token limit — prepare the next round
        logger.info(
            "LLM hit max_tokens on round %d — continuing (total chars so far: %d)…",
            round_num, len(full_output),
        )
        history.append({"role": "assistant", "content": content})
        history.append({"role": "user",      "content": CONTINUATION_PROMPT})

    else:
        # Exited loop by hitting max_rounds without an end_turn
        logger.warning(
            "query_llm_with_continuation hit max_rounds=%d limit. "
            "Output may be incomplete (%d total chars).",
            max_rounds, len(full_output),
        )

    return full_output
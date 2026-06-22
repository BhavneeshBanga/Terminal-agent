# import time
# import httpx
# from bhavai.config import SARVAM_API_KEY, SARVAM_BASE_URL, SARVAM_MODEL, logger


# def query_llm(messages: list, temperature: float = 0.0) -> str:
#     """
#     Queries the Sarvam-105B API via the OpenAI-compatible chat completions endpoint.

#     Retry behaviour
#     ---------------
#     • 429 / 5xx  → exponential backoff (2 s, 4 s, 8 s) then retry
#     • Network errors (httpx.RequestError) → same backoff, raise on final attempt
#     • Any other non-200 status → raise immediately (non-retryable)

#     Always raises RuntimeError on total failure so the caller (agent.py) can
#     catch it cleanly and assign raw_response before referencing it.
#     """
#     if not SARVAM_API_KEY:
#         print("sarvam apikey", SARVAM_API_KEY)
#         raise ValueError(
#             "SARVAM_API_KEY is not set. "
#             "Please add it to your .env file or environment variables."
#         )

#     url = f"{SARVAM_BASE_URL.rstrip('/')}/chat/completions"

#     # headers = {
#     #     "api-subscription-key": SARVAM_API_KEY,
#     #     "Content-Type": "application/json",
#     # }


#     headers = {
#         "Authorization": f"Bearer {SARVAM_API_KEY}",
#         "Content-Type": "application/json",
#     }
#     payload = {
#         "model":       SARVAM_MODEL,
#         "messages":    messages,
#         "temperature": temperature,
#         "max_tokens":  4096,
#     }

#     max_retries = 3
#     delay       = 2.0
#     last_error  = None          # track last exception for the final raise

#     for attempt in range(1, max_retries + 1):
#         logger.debug(
#             "Sarvam API request — attempt %d/%d  url=%s  model=%s",
#             attempt, max_retries, url, SARVAM_MODEL,
#         )

#         try:
#             with httpx.Client(timeout=90.0) as client:
#                 response = client.post(url, json=payload, headers=headers)

#             status = response.status_code

#             # ── Success ───────────────────────────────────────────────────── #
#             if status == 200:
#                 data = response.json()
#                 try:
#                     content = data["choices"][0]["message"]["content"]
#                 except (KeyError, IndexError, TypeError) as exc:
#                     # Malformed success response — treat as non-retryable
#                     raise RuntimeError(
#                         f"Sarvam API returned 200 but response structure is unexpected: "
#                         f"{exc}. Raw: {str(data)[:300]}"
#                     )

#                 if not isinstance(content, str) or not content.strip():
#                     raise RuntimeError(
#                         "Sarvam API returned 200 but 'content' is empty or not a string."
#                     )

#                 logger.debug("Sarvam API success on attempt %d.", attempt)
#                 return content

#             # ── Transient error — retry ───────────────────────────────────── #
#             elif status in (429, 500, 502, 503, 504):
#                 logger.warning(
#                     "Sarvam API transient %d on attempt %d/%d — retrying in %.1f s…",
#                     status, attempt, max_retries, delay,
#                 )
#                 last_error = RuntimeError(
#                     f"Sarvam API transient error {status} after {attempt} attempt(s)."
#                 )
#                 time.sleep(delay)
#                 delay *= 2.0
#                 continue            # explicit continue for clarity

#             # ── Non-retryable error ───────────────────────────────────────── #
#             else:
#                 raise RuntimeError(
#                     f"Sarvam API non-retryable error {status}: {response.text[:300]}"
#                 )

#         except httpx.RequestError as exc:
#             logger.warning(
#                 "Sarvam API network error on attempt %d/%d: %s",
#                 attempt, max_retries, exc,
#             )
#             last_error = RuntimeError(
#                 f"Sarvam API network error: {exc}"
#             )
#             if attempt == max_retries:
#                 break
#             time.sleep(delay)
#             delay *= 2.0
#             continue

#         except RuntimeError:
#             raise   # re-raise without wrapping (already descriptive)

#         except Exception as exc:
#             # Unexpected error — wrap and raise immediately
#             raise RuntimeError(f"Unexpected error querying Sarvam API: {exc}") from exc

#     # All retries exhausted
#     raise last_error or RuntimeError(
#         f"Sarvam API failed after {max_retries} attempts with no response."
#     )


from dotenv import load_dotenv
# import httpx
import os

# Load .env file from current working directory or fallback to system environment variables
load_dotenv()

# Configuration Settings
# SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")



import time
from sarvamai import SarvamAI

from bhavai.config import SARVAM_API_KEY, SARVAM_MODEL, logger

client = SarvamAI(
    api_subscription_key=os.getenv("SARVAM_API_KEY")
)

def query_llm(messages: list, temperature: float = 0.0) -> str:
    """
    Query Sarvam LLM using official SDK.
    """

    if not SARVAM_API_KEY:
        raise ValueError(
            "SARVAM_API_KEY is not set. "
            "Please add it to your .env file or environment variables."
        )

    max_retries = 3
    delay = 2.0
    last_error = None

    for attempt in range(1, max_retries + 1):

        try:
            logger.debug(
                "Sarvam SDK request — attempt %d/%d model=%s",
                attempt,
                max_retries,
                SARVAM_MODEL,
            )

            response = client.chat.completions(
                model="sarvam-105b",
                messages=messages,
                temperature=temperature,
                max_tokens=4096,
            )

            content = response.choices[0].message.content

            if not content or not isinstance(content, str):
                raise RuntimeError("Empty response from Sarvam.")

            return content

        except Exception as exc:
            last_error = exc

            logger.warning(
                "Sarvam request failed on attempt %d/%d: %s",
                attempt,
                max_retries,
                exc,
            )

            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2

    raise RuntimeError(
        f"Sarvam API failed after {max_retries} attempts. Last error: {last_error}"
    )
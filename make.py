import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

from bhavai.config import logger, CWD
from bhavai.context import is_env_file, parse_gitignore, should_ignore

from bhavai.tools import validate_path


# ─────────────────────────────────────────────────────────────────────────────
# Tool: fetch_url — ground the agent in real documentation instead of
# letting it guess API signatures, error messages, or library usage from
# (possibly stale) training data. High value for students learning new
# libraries and developers debugging unfamiliar errors.
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_URL_SCHEMES = ("http://", "https://")
_MAX_FETCH_BYTES = 300_000

def fetch_url(url: str, max_chars: int = 8000) -> str:
    """
    Fetches a web page or API endpoint and returns its text content
    (HTML tags stripped) for the agent to read.

    Use this to look up real documentation, error message explanations,
    Stack Overflow answers, or library API references instead of
    guessing — especially for libraries that may have changed since
    the model's training data.

    Truncates output to max_chars (default 8000) to protect the
    4096-token output budget on the NEXT call where the agent
    summarizes what it read.
    """
    logger.info("fetch_url('%s')", url)
    if not url.lower().startswith(_ALLOWED_URL_SCHEMES):
        return "Error: only http:// and https:// URLs are supported."

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "BhavAI-Agent/1.0 (+terminal coding assistant)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(_MAX_FETCH_BYTES)
    except urllib.error.HTTPError as exc:
        return f"Error: HTTP {exc.code} fetching '{url}'."
    except urllib.error.URLError as exc:
        return f"Error: could not reach '{url}': {exc.reason}"
    except Exception as exc:
        return f"Error fetching '{url}': {exc}"

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return f"Error: '{url}' did not return decodable text content."

    if "html" in content_type.lower():
        # Strip script/style blocks, then all remaining tags — good enough
        # for an agent that needs prose, not pixel-perfect rendering.
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

    truncated = len(text) > max_chars
    text = text[:max_chars]
    suffix = f"\n\n[...truncated, {len(raw)} bytes fetched total...]" if truncated else ""
    return f"Content from {url}:\n\n{text}{suffix}"




print(fetch_url("https://www.bing.com/ck/a?!&&p=ab83e791277134a7455c386e23b693b97f91d693551a24e1977e84fec4fa9af1JmltdHM9MTc4MjI1OTIwMA&ptn=3&ver=2&hsh=4&fclid=2c3a7811-fe48-6ff3-3507-6f20ffb06edc&psq=code+with+harry+wikipedia&u=a1aHR0cHM6Ly9lbi5ldmVyeWJvZHl3aWtpLmNvbS9Db2RlV2l0aEhhcnJ5"))
"""Agent-assisted content fetch for Knowledge Library.

Fetches content from URLs using the dedicated URL-fetch LLM pool. The pool worker uses
whatever web/URL-fetch tool its backend exposes (configure the allowed tools
via KIROCREW_KNOWLEDGE_FETCH_TOOLS). If the backend has no fetch tool available,
the fetch fails gracefully and the caller falls back to local readers.

Every URL Kiro Crew itself asks the pool to fetch must pass
:func:`url_fetch_refusal` first: https only, and only a host listed in
``knowledge.doc_ingest_hosts``. That list is empty by default, so a default
config fetches nothing. :func:`fetch_url_content` runs the check itself, so no
caller can reach the pool with a URL the list does not name.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from kiro_crew.security import redact_and_truncate

if TYPE_CHECKING:
    from kiro_crew.knowledge.llm_pool import LLMPool

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 120.0

MAX_URL_LENGTH = 2048


class UrlFetchRefused(RuntimeError):
    """A URL :func:`url_fetch_refusal` will not let Kiro Crew fetch."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def url_fetch_refusal(url: object, allowed_hosts: Iterable[str]) -> tuple[str, str] | None:
    """Return ``(code, message)`` when Kiro Crew must not fetch *url*, else ``None``.

    The host must equal one entry of *allowed_hosts* exactly (case and a
    trailing dot aside); a subdomain of a listed host is a different host. The
    URL is also refused when its parsed host could differ from the host a
    reader sees: credentials before the host, a backslash, whitespace or a
    control character, a port other than 443, or a non-ASCII host. The URL is
    later written into the fetch worker's prompt, so the whitespace rule also
    keeps it one token there.
    """
    if not isinstance(url, str) or not url:
        return "url_invalid", "URL is required"
    if len(url) > MAX_URL_LENGTH:
        return "url_too_long", f"URL too long (max {MAX_URL_LENGTH})"
    if not url.startswith("https://"):
        return "url_not_https", "URI must start with https://"
    if "\\" in url or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
        return "url_invalid", "URL contains a character that is not allowed"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "url_invalid", "URL could not be parsed"
    if parts.username is not None or parts.password is not None:
        return "url_has_credentials", "URL must not carry a user name or password"
    if port not in (None, 443):
        return "url_port_not_allowed", "URL must use the default https port"
    host = _normalize_host(parts.hostname or "")
    if not host or not host.isascii():
        return "url_invalid", "URL has no valid host"
    allowed = {_normalize_host(h) for h in allowed_hosts if isinstance(h, str)}
    if host not in allowed:
        return (
            "url_host_not_allowed",
            f"Host {host} is not in knowledge.doc_ingest_hosts. Add it there to let "
            "Kiro Crew fetch pages from it.",
        )
    return None


FETCH_PROMPT_TEMPLATE = (
    "Fetch the full text content from this URL using any web/URL-fetch tool you "
    "have available: {url}\n\n"
    "Return ONLY the raw document text, no commentary or formatting.\n"
    "If you cannot access the URL or encounter an error, respond with exactly: ERROR: <reason>"
)

# Patterns indicating the LLM returned an error instead of content
_ERROR_INDICATORS = (
    "ERROR:",
    "I don't have access",
    "I cannot access",
    "I'm unable to",
    "permission denied",
    "I don't have permission",
    "tool is not available",
    "not available in this",
)


async def fetch_url_content(url: str, pool: "LLMPool", *, allowed_hosts: Iterable[str]) -> str:
    """Fetch content from a URL using the dedicated URL-fetch pool.

    Refuses, before any worker is acquired, a URL :func:`url_fetch_refusal`
    refuses against *allowed_hosts* (raising :class:`UrlFetchRefused`).
    Otherwise acquires a worker from the caller-supplied URL-fetch pool, sends
    the fetch prompt, and releases the worker. The worker uses whatever
    URL-fetch tool its backend exposes (configurable via
    KIROCREW_KNOWLEDGE_FETCH_TOOLS); if none is available the fetch fails.

    Returns the fetched text content.
    Raises RuntimeError on failure.
    """
    refusal = url_fetch_refusal(url, allowed_hosts)
    if refusal is not None:
        raise UrlFetchRefused(*refusal)
    logger.info(
        "fetch_url_content: starting fetch for %s (pool provider=%s)", url, pool.provider_type
    )
    prompt = FETCH_PROMPT_TEMPLATE.format(url=url)
    response = await pool.send(prompt, timeout=FETCH_TIMEOUT)
    logger.info(
        "fetch_url_content: got response length=%d for %s", len(response) if response else 0, url
    )
    if not response or not response.strip():
        raise RuntimeError(f"LLM pool returned empty content for {url}")
    content = response.strip()
    # Check if the response is an error message rather than actual content
    content_lower = content[:200].lower()
    for indicator in _ERROR_INDICATORS:
        if indicator.lower() in content_lower:
            redacted = redact_and_truncate(content, 300)
            logger.error(
                "fetch_url_content: error indicator '%s' found in response: %s",
                indicator,
                redacted[:200],
            )
            raise RuntimeError(f"Failed to fetch {url}: {redacted[:300]}")
    # Sanity check: real documents should have meaningful length
    if len(content) < 50:
        raise RuntimeError(f"Content too short for {url} ({len(content)} chars) -- likely an error")
    logger.info("fetch_url_content: success for %s (%d chars)", url, len(content))
    return content

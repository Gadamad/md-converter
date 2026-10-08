"""Validate saved queue inputs without opening files or fetching websites."""

from pathlib import Path
import plistlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit
from xml.parsers.expat import ExpatError


def normalize_url(value: str) -> str:
    """Return an HTTP(S) URL with conservative, content-preserving normalization."""
    if not isinstance(value, str) or any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError("Website URLs cannot contain control characters.")
    value = value.strip()
    if not value or any(char.isspace() for char in value) or "\\" in value:
        raise ValueError("Enter a valid website URL without spaces or backslashes.")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("Only http:// and https:// website URLs are supported.")
        if not parsed.hostname:
            raise ValueError("A website URL must include a hostname.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Website URLs with embedded credentials are not supported.")
        host = parsed.hostname.lower()
        port = parsed.port
        if ":" not in host:
            ascii_host = host.encode("idna").decode("ascii")
            if not re.fullmatch(r"[a-zA-Z0-9._-]+", ascii_host):
                raise ValueError("The website URL contains an invalid hostname.")
        else:
            host = f"[{host}]"
        if port is not None and (parsed.scheme.lower(), port) not in {("http", 80), ("https", 443)}:
            host = f"{host}:{port}"
        normalized = urlunsplit((parsed.scheme.lower(), host, parsed.path, parsed.query, ""))
        if not parsed.query and "?" in value.split("#", 1)[0]:
            normalized += "?"
        return normalized
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Invalid website URL: {exc}") from exc


def _looks_like_url(value: str) -> bool:
    """Keep prose such as 'Notes: a thought' separate from URI-like input."""
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?:\S|$)", value))


def sources_from_text(text: str) -> list[dict]:
    """Split a list of URLs, or keep ordinary pasted prose as one text item."""
    if not isinstance(text, str):
        raise ValueError("Paste text or one website URL per line.")
    text = text.strip()
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    url_lines = [_looks_like_url(line) for line in lines]
    # Validate URI-like lines even in a mixed input, so an unsafe or malformed
    # address cannot silently become a text conversion.
    normalized = [normalize_url(line) if is_url else None for line, is_url in zip(lines, url_lines)]
    if all(url_lines):
        return [{"kind": "url", "source": url, "title": url[:80], "group_name": ""} for url in normalized]
    return [{"kind": "text", "source": text, "title": lines[0][:80], "group_name": ""}]


def read_webloc(path: str | Path) -> str:
    """Read the HTTP(S) target of an XML or binary macOS website shortcut."""
    path = Path(path)
    try:
        with path.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, ValueError, TypeError, OverflowError, ExpatError) as exc:
        raise ValueError(f"Could not read the website shortcut {path.name}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("URL"), str):
        raise ValueError(f"The .webloc file {path.name} does not contain a website URL.")
    return normalize_url(data["URL"])

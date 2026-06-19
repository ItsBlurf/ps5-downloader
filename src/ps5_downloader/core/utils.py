from __future__ import annotations

import os
import re
import socket
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

URL_RE = re.compile(r"https?://[^\s<>'\"`]+", re.IGNORECASE)
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
DOWNLOAD_EXTENSIONS = {
    ".001",
    ".7z",
    ".apk",
    ".appimage",
    ".avi",
    ".bin",
    ".bz2",
    ".chd",
    ".cue",
    ".deb",
    ".dmg",
    ".elf",
    ".exe",
    ".flac",
    ".gz",
    ".img",
    ".iso",
    ".json",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".msi",
    ".pdf",
    ".pkg",
    ".pkg.part",
    ".png",
    ".rar",
    ".rpm",
    ".tar",
    ".tgz",
    ".torrent",
    ".txt",
    ".wav",
    ".webm",
    ".wim",
    ".xz",
    ".zip",
    ".zst",
}


def extract_urls(text: str) -> list[str]:
    urls = []
    for match in URL_RE.findall(text or ""):
        url = match.rstrip(").,;]}>\"'")
        urls.append(url)
    return urls


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"unsupported URL: {url}")
    host = parts.hostname.lower() if parts.hostname else parts.netloc.lower()
    if parts.port:
        host = f"{host}:{parts.port}"
    path = quote(unquote(parts.path or "/"), safe="/:@!$&'()*+,;=-._~")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        try:
            normalized = normalize_url(url)
        except ValueError:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def is_noise_url(url: str) -> bool:
    host = host_from_url(url)
    path = urlsplit(url).path.lower()
    if host in {"accounts.google.com", "support.google.com", "policies.google.com"}:
        return True
    if host.endswith(".gstatic.com") or host.endswith(".googleusercontent.com"):
        return True
    if host == "www.google.com" and path in {"/url", "/search"}:
        return True
    return False


def actionable_urls_from_text(text: str) -> list[str]:
    urls = [url for url in dedupe_urls(extract_urls(text)) if not is_noise_url(url)]
    preferred: list[str] = []
    rest: list[str] = []
    for url in urls:
        host = host_from_url(url)
        path = urlsplit(url).path.lower()
        if host == "drive.google.com" and path.startswith("/file/d/"):
            preferred.append(url)
        elif "mediafire.com" in host:
            preferred.append(url)
        else:
            rest.append(url)
    return preferred + rest


def is_likely_download_url(url: str) -> bool:
    path = unquote(urlsplit(url).path).lower()
    if re.search(r"\.part\d+\.rar$", path):
        return True
    return any(path.endswith(ext) for ext in DOWNLOAD_EXTENSIONS)


def ps5_native_http_url(url: str, allow_https_direct: bool = False) -> str:
    """Build a PS5-native plain-HTTP URL with a Host override when useful."""
    parts = urlsplit(normalize_url(url))
    host = parts.hostname or ""
    path = parts.path or "/"
    query = parts.query
    if parts.scheme == "https" and host.startswith("download") and host.endswith(".mediafire.com"):
        scheme = "http"
    elif parts.scheme == "https" and is_likely_download_url(url):
        scheme = "http"
    elif parts.scheme == "https" and allow_https_direct:
        scheme = "http"
    elif parts.scheme == "http":
        scheme = "http"
    else:
        return url
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return urlunsplit((scheme, parts.netloc, path, query, ""))
    if ip == host:
        return urlunsplit((scheme, parts.netloc, path, query, ""))
    native_query = query
    separator = "&" if native_query else ""
    native_query = f"{native_query}{separator}__ps5_host={quote(host)}"
    return urlunsplit((scheme, ip, path, native_query, ""))


def host_from_url(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def sanitize_filename(name: str, fallback: str = "download.bin") -> str:
    name = unquote(name or "").strip()
    name = name.replace("\\", "_").replace("/", "_")
    name = re.sub(r"[\x00-\x1f<>:\"|?*]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    stem = name.split(".")[0].upper()
    if stem in WINDOWS_RESERVED:
        name = f"_{name}"
    return name[:180]


def filename_from_url(url: str) -> str:
    path = urlsplit(url).path
    candidate = Path(path).name
    return sanitize_filename(candidate, "download.bin")


def ensure_directory(path: str | Path) -> Path:
    directory = Path(path).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def ensure_safe_child(base: str | Path, child_name: str) -> Path:
    base_path = ensure_directory(base)
    child = (base_path / sanitize_filename(child_name)).resolve()
    if os.path.commonpath([str(base_path), str(child)]) != str(base_path):
        raise ValueError("path traversal rejected")
    return child


def validate_directory_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise ValueError(f"not a directory: {path}")
    return resolved

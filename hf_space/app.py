"""Bounded, anonymous retrieval over public GitHub repository snapshots."""

import io
import json
import re
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import broker
import kn

# The snapshot is not a Git checkout; avoid invoking Git on untrusted input.
kn.list_files = kn.fallback_list_files

MAX_DOWNLOAD = 20 * 1024 * 1024
MAX_EXPANDED = 40 * 1024 * 1024
MAX_FILES = 2000
MAX_FILE = 1_000_000
TIMEOUT = 30
LOCK = threading.BoundedSemaphore(1)
HOSTS = {"api.github.com", "codeload.github.com"}
REPO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}\Z")


def allowed_url(url):
    parts = urllib.parse.urlsplit(url)
    try:
        return (
            parts.scheme == "https"
            and parts.hostname in HOSTS
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and not parts.fragment
        )
    except ValueError:
        return False


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError("GitHub redirected to an unapproved address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, maximum):
    if not allowed_url(url):
        raise ValueError("Unapproved download address")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), SafeRedirect())
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TokSmart-public-retrieval",
            "Accept": "application/vnd.github+json",
        },
    )
    deadline = time.monotonic() + TIMEOUT
    with opener.open(req, timeout=5) as response:
        if not allowed_url(response.geturl()):
            raise ValueError("Unapproved response address")
        size = response.headers.get("Content-Length")
        if size and int(size) > maximum:
            raise ValueError("Download exceeds limit")
        data = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise ValueError("Download timed out")
            chunk = response.read(min(65536, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > maximum:
                raise ValueError("Download exceeds limit")
        return bytes(data)


def extract(data, root):
    total = 0
    names = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES:
            raise ValueError("Archive has too many entries")
        for entry in entries:
            name = entry.filename
            mode = entry.external_attr >> 16
            parts = PurePosixPath(name).parts
            if (
                not parts
                or name.startswith("/")
                or "\\" in name
                or ".." in parts
                or any(":" in part for part in parts)
                or stat.S_ISLNK(mode)
                or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
            ):
                raise ValueError("Unsafe archive entry")
            if len(parts) < 2 or entry.is_dir():
                continue
            relative = "/".join(parts[1:])
            if relative.casefold() in names:
                raise ValueError("Duplicate archive entry")
            names.add(relative.casefold())
            total += entry.file_size
            if entry.file_size > MAX_FILE or total > MAX_EXPANDED:
                raise ValueError("Archive exceeds extraction limit")
            if not kn.safe_relative(relative):
                continue
            target = root.joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("xb") as dest:
                remaining = entry.file_size
                while remaining:
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        raise ValueError("Incomplete archive entry")
                    dest.write(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise ValueError("Archive entry exceeds declared size")


def public_context(repository: str, task: str) -> dict:
    """Find bounded code metadata in an anonymous public GitHub repository snapshot.

    Args:
        repository: GitHub owner/repository identifier for a public repository.
        task: Describe the coding task, up to 2000 characters.
    """
    if (
        not isinstance(repository, str)
        or not REPO.fullmatch(repository)
        or repository.endswith(".git")
        or repository.split("/")[1] in {".", ".."}
    ):
        return {"error": "Use a public GitHub owner/repository identifier."}
    if not isinstance(task, str) or not task.strip() or len(task) > 2000:
        return {"error": "Task must be non-empty text up to 2000 characters."}
    if not LOCK.acquire(blocking=False):
        return {"error": "Server is busy; retry later."}
    try:
        meta = json.loads(download(f"https://api.github.com/repos/{repository}", 1_000_000))
        if (
            meta.get("private") is not False
            or meta.get("full_name", "").casefold() != repository.casefold()
        ):
            return {"error": "Public repository not found."}
        commit = json.loads(
            download(f"https://api.github.com/repos/{repository}/commits/HEAD", 1_000_000)
        ).get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            return {"error": "Unable to resolve repository snapshot."}
        data = download(f"https://codeload.github.com/{repository}/zip/{commit}", MAX_DOWNLOAD)
        with tempfile.TemporaryDirectory(prefix="lazytoken-public-") as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            extract(data, root)
            conn = kn.connect(Path(temp) / "index.sqlite3")
            try:
                synced = kn.sync(root, conn)
                if synced.get("error") or synced.get("error_count"):
                    return {"error": "Repository indexing failed."}
                result = broker.task_context(
                    kn, {"project": str(root), "task": task, "budget": 1200}, conn
                )
                result["project"] = repository
                result["snapshot"] = commit
                return result
            finally:
                broker._SEARCH_CACHE.clear()
                conn.close()
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        urllib.error.URLError,
    ):
        return {
            "error": "Unable to retrieve or index this public repository within service limits."
        }
    finally:
        LOCK.release()


if __name__ == "__main__":
    import gradio as gr

    gr.Interface(
        fn=public_context,
        inputs=[gr.Textbox(label="Public GitHub owner/repository"), gr.Textbox(label="Task")],
        outputs=gr.JSON(),
        title="TokSmart public repository context",
    ).launch(mcp_server=True)

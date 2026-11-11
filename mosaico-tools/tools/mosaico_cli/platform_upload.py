"""Upload a validated release ZIP as an Agent API draft."""
from __future__ import annotations

from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from .errors import SelectionError
from .ideas_release import validate_release
from .ideas_transport import ReleaseClient
from .platform_client import PlatformError, contains_token, credential, server_url


def public_id(value):
    """Project public IDs are URL segments, unrelated to six-digit app numbers."""
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is not None


def upload_archive(client, package, *, sha256, update=None):
    if update is not None and not public_id(update):
        raise SelectionError("--update requires the project's public_id, without a URL or path.")
    path = "/agent/projects" + ("/" + update if update is not None else "")
    response = client.request("PATCH" if update is not None else "POST", path,
                              {"size": package.stat().st_size, "sha256": sha256}, package=package)
    # Some ProjectDetail serializers expose public_id under the alias `code`.
    identifier = response.get("public_id", response.get("code"))
    if (not public_id(identifier) or contains_token(identifier, client.token)
            or ("code" in response and response["code"] != identifier)
            or (update is not None and identifier != update) or response.get("status") != "draft"):
        raise PlatformError("INVALID_RESPONSE", details={"outcome": "unknown",
            "diagnostic": "The response did not identify the expected draft. Check the website before uploading again."})
    result = {"public_id": identifier, "status": "draft"}
    # A first draft has no app number. Neither device identities nor a custom
    # release receipt are required to finish this interaction.
    title = response.get("title")
    if isinstance(title, str) and len(title) <= 200 and not contains_token(title, client.token):
        result["title"] = title
    number = response.get("app_number")
    if "app_number" in response and not contains_token(number, client.token) and (number is None or
            isinstance(number, str) and re.fullmatch(r"[0-9]{6}", number)):
        result["app_number"] = number
    url = response.get("draft_url")
    if isinstance(url, str) and not contains_token(url, client.token):
        try:
            parsed, origin = urlsplit(url), urlsplit(client.server)
            if (not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                    and not any(ord(c) < 32 for c in url) and "\\" not in url
                    and (url.startswith("/") and not url.startswith("//") or
                         parsed.scheme == origin.scheme and parsed.netloc == origin.netloc)):
                result["draft_url"] = url
        except ValueError:
            pass  # An optional malformed link does not invalidate a saved draft.
    return result


def project_upload(arguments, context):
    if not arguments.create and not arguments.update:
        raise SelectionError("Choose --create or --update PUBLIC_ID explicitly.")
    if arguments.update is not None and not public_id(arguments.update):
        raise SelectionError("--update requires the project's public_id, without a URL or path.")
    if not arguments.yes:
        if arguments.json or not sys.stdin.isatty() or input("Upload this ZIP as an Ideas draft? [y/N] ").strip().lower() != "y":
            raise SelectionError("Use --yes to confirm the explicit draft upload.")
    package = Path(arguments.package).expanduser().resolve()
    release = validate_release(package)
    if "category_id" not in release.manifest["project"]:
        group = release.manifest["project"].get("content_type", "software")
        raise SelectionError(
            "Uploading requires project.category_id. Fetch GET /api/v1/categories?group="
            + group + " from the selected server, choose an enabled category, set its integer id in "
            "mosaico-ideas.json, then run project package again.")
    server = server_url(arguments.server)
    client = ReleaseClient(server, credential(server), ca_file=arguments.ca_file)
    result = upload_archive(client, package, sha256=release.archive_sha256, update=arguments.update)
    return {"command": "project upload", "server": server, "package": str(package),
            "archive_sha256": release.archive_sha256, "version": release.firmware["release"], **result}

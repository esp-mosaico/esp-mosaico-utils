"""Streaming Agent API transport; writes are never automatically replayed."""
from __future__ import annotations

from email.utils import parsedate_to_datetime
import hashlib
import http.client
import json
import random
import re
import ssl
import time
from urllib.parse import urlsplit
import uuid

from .ideas_content import encoded, require
from .platform_client import PlatformError, contains_token, server_url


def retry_after(value, *, default=0.0):
    if not value:
        return default
    try:
        value = value.strip()
        return max(0.0, float(int(value))) if value.isdigit() else max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (ValueError, TypeError, OverflowError):
        return default


class ReleaseClient:
    def __init__(self, server, token, *, ca_file=None):
        self.server, self.token = server_url(server), token
        self.context = ssl.create_default_context(cafile=ca_file)

    def _response_error(self, response, value=None):
        """HTTP rejection semantics survive missing or malformed error JSON."""
        value = value if isinstance(value, dict) else {}
        code = value.get("code", "HTTP_" + str(response.status))
        if (not isinstance(code, str) or not code.replace("_", "").isalnum() or len(code) > 80
                or contains_token(code, self.token)):
            code = "HTTP_" + str(response.status)
        identifier = value.get("request_id", "")
        if (not isinstance(identifier, str) or len(identifier) > 128
                or not all(c.isalnum() or c in "-_.:" for c in identifier)
                or contains_token(identifier, self.token)):
            identifier = ""
        details = {}
        supplied = value.get("details")
        if isinstance(supplied, dict):
            for field in ("path", "field", "reason"):
                item = supplied.get(field)
                if field == "field" and type(item) is int and item > 0:
                    item = str(item)
                if (isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./\[\]-]{0,191}", item)
                        and ".." not in item and not contains_token(item, self.token)):
                    details[field] = item
        delay = retry_after(response.getheader("Retry-After"), default=None)
        if delay is not None:
            details["retry_after_seconds"] = delay
        error = PlatformError(code, response.status, identifier, details=details)
        error.retry_after = delay or 0.0
        return error

    def _send(self, method, path, metadata=None, package=None, budget_deadline=None):
        origin = urlsplit(self.server)
        connection = (http.client.HTTPSConnection(origin.hostname, origin.port, timeout=10, context=self.context)
                      if origin.scheme == "https" else http.client.HTTPConnection(origin.hostname, origin.port, timeout=10))
        deadline = time.monotonic() + (1800 if package else 30)
        if budget_deadline is not None:
            deadline = min(deadline, budget_deadline)
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        prefix = suffix = b""
        if package:
            boundary = "mosaico-" + uuid.uuid4().hex
            prefix = ("--" + boundary + '\r\nContent-Disposition: form-data; name="release"; filename="release.zip"\r\nContent-Type: application/zip\r\n\r\n').encode()
            suffix = ("\r\n--" + boundary + "--\r\n").encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
            headers["Content-Length"] = str(len(prefix) + metadata["size"] + len(suffix))
        elif metadata is not None:
            prefix = encoded(metadata)
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(prefix))

        def budget():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            if connection.sock:
                connection.sock.settimeout(min(60, remaining))

        response = None
        try:
            connection.connect()
            budget()
            connection.putrequest(method, "/api/v1" + path, skip_accept_encoding=True)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            if prefix:
                connection.send(prefix)
            if package:
                check, total = hashlib.sha256(), 0
                with package.open("rb") as source:
                    while block := source.read(65536):
                        budget()
                        total += len(block)
                        require(total <= metadata["size"], "ZIP changed after validation")
                        check.update(block)
                        connection.send(block)
                require(total == metadata["size"] and check.hexdigest() == metadata["sha256"],
                        "ZIP changed after validation")
                budget()
                connection.send(suffix)
            budget()
            response = connection.getresponse()
            success = response.status == (201 if method == "POST" and package else 200)
            data = bytearray()
            while True:
                budget()
                block = response.read1(16384)
                if not block:
                    break
                data.extend(block)
                if len(data) > 2*1024*1024:
                    if not 200 <= response.status < 300:
                        raise self._response_error(response)
                    raise PlatformError("INVALID_RESPONSE", response.status)
            try:
                value = json.loads(data)
            except (ValueError, UnicodeError):
                if not 200 <= response.status < 300:
                    raise self._response_error(response) from None
                raise PlatformError("INVALID_RESPONSE", response.status) from None
            if not success:
                raise self._response_error(response, value)
            if not isinstance(value, dict):
                raise PlatformError("INVALID_RESPONSE", response.status)
            return value
        except (OSError, TimeoutError, http.client.HTTPException):
            if response is not None and not 200 <= response.status < 300:
                raise self._response_error(response) from None
            raise PlatformError("NETWORK_ERROR", response.status if response is not None else 0) from None
        finally:
            connection.close()

    def request(self, method, path, metadata=None, *, package=None, deadline=None):
        for attempt in range(4):
            try:
                return self._send(method, path, metadata, package, deadline)
            except PlatformError as error:
                retryable = error.code == "NETWORK_ERROR" or error.status in (429, 502, 503, 504)
                # No server idempotency contract exists. A delayed PATCH replay
                # could also overwrite a newer explicit upload.
                if not retryable or attempt == 3 or method != "GET":
                    if method != "GET" and (error.status in (0, 408)
                                            or 200 <= error.status < 300 or error.status >= 500):
                        error.details["outcome"] = "unknown"
                        error.details["diagnostic"] = "Check the project on the website before uploading again; this request was not retried."
                    raise
                base = 2**attempt
                pause = max(base + random.uniform(0, base), getattr(error, "retry_after", 0))
                if deadline is not None and time.monotonic() + pause >= deadline:
                    raise
                time.sleep(pause)

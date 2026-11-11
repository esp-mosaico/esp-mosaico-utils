"""Agent API wire contract and conservative write-failure behavior."""
from email.parser import BytesParser
from email.policy import default
from email.utils import formatdate
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mosaico-tools/tools"))
from mosaico_cli.cli import _emit_error, build_parser
from mosaico_cli.errors import SelectionError
from mosaico_cli.ideas_transport import ReleaseClient
from mosaico_cli.platform_client import PlatformError
from mosaico_cli.platform_upload import upload_archive


def connection(monkeypatch, status, body):
    response = Mock(status=status)
    response.read1.side_effect = [json.dumps(body).encode(), b""]
    response.getheader.return_value = None
    conn = Mock()
    conn.getresponse.return_value = response
    monkeypatch.setattr("mosaico_cli.ideas_transport.http.client.HTTPConnection", Mock(return_value=conn))
    return conn


@pytest.mark.parametrize("update,status", [(None, 201), ("project-one", 200)])
def test_single_release_part_and_synchronous_project_detail(monkeypatch, tmp_path, update, status):
    raw = b"frozen zip bytes"
    package = tmp_path / "release.zip"
    package.write_bytes(raw)
    conn = connection(monkeypatch, status, {"public_id": "project-one", "status": "draft", "app_number": None})
    client = ReleaseClient("http://localhost:1234", "private-token")
    result = upload_archive(client, package, sha256=hashlib.sha256(raw).hexdigest(), update=update)
    assert result == {"public_id": "project-one", "status": "draft", "app_number": None}
    conn.putrequest.assert_called_once_with("PATCH" if update else "POST",
        "/api/v1/agent/projects" + ("/project-one" if update else ""), skip_accept_encoding=True)
    headers = dict(call.args for call in conn.putheader.call_args_list)
    assert headers["Authorization"] == "Bearer private-token" and "Idempotency-Key" not in headers
    body = b"".join(call.args[0] for call in conn.send.call_args_list)
    assert len(body) == int(headers["Content-Length"])
    mime = BytesParser(policy=default).parsebytes(("Content-Type: " + headers["Content-Type"] + "\r\n\r\n").encode() + body)
    parts = list(mime.iter_parts())
    assert len(parts) == 1 and parts[0].get_param("name", header="content-disposition") == "release"
    assert parts[0].get_content_type() == "application/zip"
    assert parts[0].get_payload(decode=True) == raw


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("error", [PlatformError("NETWORK_ERROR"), PlatformError("HTTP_503", 503),
                                  PlatformError("HTTP_429", 429), PlatformError("VERSION_ALREADY_PUBLISHED", 409)])
def test_write_errors_never_replay(monkeypatch, method, error):
    client = ReleaseClient("http://localhost:1234", "private-token")
    send = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr("mosaico_cli.ideas_transport.time.sleep", sleep)
    with pytest.raises(PlatformError) as raised:
        client.request(method, "/agent/projects")
    assert raised.value is error
    assert send.call_count == 1 and sleep.call_count == 0
    if error.code == "NETWORK_ERROR" or error.status == 503:
        assert error.details["outcome"] == "unknown"


def test_invalid_json_is_uncertain_without_replay(monkeypatch):
    conn = connection(monkeypatch, 201, {})
    conn.getresponse.return_value.read1.side_effect = [b"not-json", b""]
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "private-token").request("POST", "/agent/projects")
    assert raised.value.code == "INVALID_RESPONSE"
    assert raised.value.details["outcome"] == "unknown"
    assert conn.getresponse.call_count == 1


def test_validation_error_preserves_safe_diagnostics(monkeypatch):
    connection(monkeypatch, 400, {"code": "invalid_release", "request_id": "req-one",
        "message": "private-token https://secret.test/?signed=secret",
        "details": {"reason": "INVALID_PRESENTATION", "path": "device/en/icon.png",
                    "field": "https://secret.test/?token=private-token", "token": "private-token"}})
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "private-token").request("POST", "/agent/projects")
    assert raised.value.code == "invalid_release"
    assert raised.value.details["path"] == "device/en/icon.png"
    assert raised.value.details["reason"] == "INVALID_PRESENTATION"
    assert raised.value.details["request_id"] == "req-one"
    assert "secret" not in str(raised.value) + json.dumps(raised.value.details)
    assert "private-token" not in json.dumps(raised.value.details)


@pytest.mark.parametrize("category_id", [123, "123"])
def test_invalid_category_keeps_id_and_reason_without_replay(monkeypatch, capsys, category_id):
    conn = connection(monkeypatch, 400, {"code": "invalid_category", "request_id": "req-category",
        "details": {"reason": "CATEGORY_GROUP_MISMATCH", "field": category_id}})
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "private-token").request("POST", "/agent/projects")
    assert raised.value.code == "invalid_category"
    assert raised.value.details["field"] == "123"
    _emit_error(raised.value, False, False)
    output = capsys.readouterr().err
    assert "Field: 123" in output and "Reason: CATEGORY_GROUP_MISMATCH" in output
    assert conn.getresponse.call_count == 1


def test_numeric_category_diagnostic_containing_token_is_filtered(monkeypatch):
    connection(monkeypatch, 400, {"code": "invalid_category", "details": {"field": 123456}})
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "123456").request("POST", "/agent/projects")
    assert "field" not in raised.value.details


def test_read_requests_still_honor_retry_after(monkeypatch):
    client = ReleaseClient("http://localhost:1234", "private-token")
    error = PlatformError("HTTP_503", 503)
    error.retry_after = 9
    send = Mock(side_effect=[error, {"user": {"id": 3}}])
    sleep = Mock()
    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr("mosaico_cli.ideas_transport.time.sleep", sleep)
    assert client.request("GET", "/auth/cli/token")["user"]["id"] == 3
    sleep.assert_called_once_with(9)


@pytest.mark.parametrize("body", [
    {"status": "draft"}, {"public_id": "../escape", "status": "draft"},
    {"public_id": "project-one", "status": "approved"},
    {"public_id": "project-one", "code": "different", "status": "draft"},
    {"public_id": "wrong-target", "status": "draft"},
])
def test_malformed_or_wrong_target_receipts_are_not_success(tmp_path, body):
    package = tmp_path / "release.zip"; package.write_bytes(b"zip")
    client = Mock(server="https://example.test")
    client.request.return_value = body
    with pytest.raises(PlatformError) as error:
        upload_archive(client, package, sha256="a"*64, update="project-one")
    assert error.value.code == "INVALID_RESPONSE" and error.value.details["outcome"] == "unknown"
    assert client.request.call_count == 1


def test_code_alias_and_explicit_repeat_are_supported(tmp_path):
    package = tmp_path / "release.zip"; package.write_bytes(b"zip")
    client = Mock(server="https://example.test")
    client.request.return_value = {"code": "project-one", "status": "draft"}
    for _ in range(2):
        assert upload_archive(client, package, sha256="a"*64, update="project-one")["public_id"] == "project-one"
    assert client.request.call_count == 2


def test_target_validation_precedes_network(tmp_path):
    client = Mock()
    with pytest.raises(SelectionError):
        upload_archive(client, tmp_path / "missing.zip", sha256="a"*64, update="../other")
    client.request.assert_not_called()


def test_cli_rejects_obsolete_async_and_cas_options():
    parser = build_parser()
    for option in ("--expected-project-version", "--wait-timeout"):
        with pytest.raises(SystemExit):
            parser.parse_args(["project", "upload", "release.zip", "--update", "project-one", option, "1"])


@pytest.mark.parametrize("url,expected", [
    ("/projects/project-one", "/projects/project-one"),
    ("https://example.test/projects/project-one", "https://example.test/projects/project-one"),
    ("https://[broken", None), ("//elsewhere.test", None),
    ("https://example.test/path?token=secret", None),
])
def test_optional_draft_links_do_not_break_success(tmp_path, url, expected):
    package = tmp_path / "release.zip"; package.write_bytes(b"zip")
    client = Mock(server="https://example.test")
    client.request.return_value = {"public_id": "project-one", "status": "draft", "draft_url": url}
    result = upload_archive(client, package, sha256="a"*64)
    assert result["status"] == "draft" and result.get("draft_url") == expected


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("header,seconds", [("30", 30), ("0", 0),
    (formatdate(1700000030, usegmt=True), 30), (None, None), ("invalid", None)])
def test_retry_after_is_visible_in_all_error_outputs(monkeypatch, capsys, status, header, seconds):
    conn = connection(monkeypatch, status, {"code": "RATE_LIMITED"})
    conn.getresponse.return_value.getheader.return_value = header
    monkeypatch.setattr("mosaico_cli.ideas_transport.time.time", lambda: 1700000000)
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "private-token").request("POST", "/agent/projects")
    assert conn.getresponse.call_count == 1
    assert raised.value.details.get("retry_after_seconds") == seconds
    for json_output, verbose in ((False, False), (True, False), (False, True)):
        _emit_error(raised.value, json_output, verbose)
        output = capsys.readouterr().err
        if json_output:
            assert json.loads(output)["details"].get("retry_after_seconds") == seconds
        elif seconds is not None:
            assert f"Retry-After: wait at least {seconds} seconds." in output
        else:
            assert "Retry-After:" not in output


def test_default_error_output_includes_filtered_validation_location(monkeypatch, capsys):
    connection(monkeypatch, 400, {"code": "invalid_release", "request_id": "req-one",
        "message": "private-token", "details": {"reason": "INVALID_PRESENTATION",
        "path": "device/en/icon.png", "field": "device.presentations[1].assets"}})
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "private-token").request("PATCH", "/agent/projects/project-one")
    _emit_error(raised.value, False, False)
    output = capsys.readouterr().err
    assert "Reason: INVALID_PRESENTATION" in output
    assert "Path: device/en/icon.png" in output
    assert "Field: device.presentations[1].assets" in output
    assert "req-one" in output and "private-token" not in output


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 413, 429])
@pytest.mark.parametrize("body", [b"<html>private-token</html>", b"", b"[]", b"x" * (2*1024*1024+1)],
                         ids=["html", "empty", "array", "oversized"])
def test_rejected_writes_keep_http_status_without_uncertain_outcome(monkeypatch, capsys, status, body):
    conn = connection(monkeypatch, status, {})
    conn.getresponse.return_value.read1.side_effect = [body, b""]
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "private-token").request("POST", "/agent/projects")
    error = raised.value
    assert error.code == f"HTTP_{status}" and error.status == status
    assert "outcome" not in error.details and "diagnostic" not in error.details
    _emit_error(error, True, False)
    output = capsys.readouterr().err
    assert json.loads(output)["error"] == "platform_error"
    assert "private-token" not in output
    assert conn.getresponse.call_count == 1


@pytest.mark.parametrize("status", [200, 201, 408, 503])
def test_malformed_success_timeout_and_server_errors_remain_uncertain(monkeypatch, status):
    conn = connection(monkeypatch, status, {})
    conn.getresponse.return_value.read1.side_effect = [b"<html>invalid</html>", b""]
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "private-token").request("POST", "/agent/projects")
    assert raised.value.details["outcome"] == "unknown"
    assert raised.value.status == status
    assert conn.getresponse.call_count == 1


@pytest.mark.parametrize("status,uncertain", [(401, False), (429, False), (201, True), (503, True)])
def test_body_read_failure_preserves_received_http_status(monkeypatch, status, uncertain):
    conn = connection(monkeypatch, status, {})
    conn.getresponse.return_value.read1.side_effect = OSError("private-token")
    conn.getresponse.return_value.getheader.return_value = "30"
    with pytest.raises(PlatformError) as raised:
        ReleaseClient("http://localhost:1234", "private-token").request("POST", "/agent/projects")
    error = raised.value
    assert error.status == status
    assert (error.details.get("outcome") == "unknown") is uncertain
    if status >= 300:
        assert error.code == f"HTTP_{status}" and error.details["retry_after_seconds"] == 30
    assert "private-token" not in str(error) + json.dumps(error.details)
    assert conn.getresponse.call_count == 1


@pytest.mark.parametrize("field,value,token", [
    ("title", "Echo private-token", "private-token"),
    ("draft_url", "/projects/private-token", "private-token"),
    ("draft_url", "https://example.test/projects/private-token", "private-token"),
    ("draft_url", "/projects/%70rivate-token", "private-token"),
    ("app_number", "234567", "234567"),
])
def test_success_drops_optional_fields_containing_token(tmp_path, field, value, token):
    package = tmp_path / "release.zip"; package.write_bytes(b"zip")
    client = Mock(server="https://example.test", token=token)
    client.request.return_value = {"public_id": "project-one", "status": "draft", field: value}
    result = upload_archive(client, package, sha256="a"*64)
    assert result["public_id"] == "project-one" and result["status"] == "draft"
    assert field not in result
    for indent in (None, 2):
        assert token not in json.dumps(result, indent=indent)


@pytest.mark.parametrize("field", ["public_id", "code"])
def test_identity_containing_token_is_rejected_without_echo(tmp_path, capsys, field):
    package = tmp_path / "release.zip"; package.write_bytes(b"zip")
    client = Mock(server="https://example.test", token="private-token")
    client.request.return_value = {field: "app-private-token", "status": "draft"}
    with pytest.raises(PlatformError) as raised:
        upload_archive(client, package, sha256="a"*64)
    assert raised.value.code == "INVALID_RESPONSE" and raised.value.details["outcome"] == "unknown"
    for json_output, verbose in ((False, False), (True, False), (False, True)):
        _emit_error(raised.value, json_output, verbose)
        assert client.token not in capsys.readouterr().err

"""Real ZIP validators and HTTP/SQLite protocol round-trips, without hardware."""
import copy
from email.parser import BytesParser
from email.policy import default as email_policy
import hashlib
import http.client
import io
import json
from pathlib import Path, PurePosixPath
import socket
import struct
import sys
import threading
import time
import uuid
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mosaico-tools/tools"))
sys.path.insert(0, str(ROOT / "mosaico-tools/tests/fixtures"))
from ideas_release import archive, descriptor, encoded, png, ref, upload
from mosaico_cli.ideas_content import ContentError, read_archive, strict_json
from mosaico_cli.ideas_release import validate_release
from mosaico_cli.ideas_test_server import IdeasServer
from mosaico_cli.ideas_test_store import Store
from mosaico_cli.ideas_transport import ReleaseClient, retry_after
from mosaico_cli.platform_client import PlatformError
from mosaico_cli.platform_upload import upload_archive


def test_full_closure_preserves_every_original_byte():
    _, outer, raw = upload()
    release = validate_release(raw)
    manifest, files = release.device_release("app-one", "042731", "release-one", author="作者 Example")
    assert manifest["schema"] == "mosaico-ideas/device-release/1"
    assert manifest["author"] == "作者 Example"
    assert json.loads(files["manifest.json"])["author"] == "作者 Example"
    for path, data in files.items():
        if path.startswith("device/"): assert data == outer[path]
    inner = read_archive(outer["firmware/application.irisfw"])
    assert files["firmware/manifest.json"] == inner["manifest.json"]
    for component in release.firmware["components"]:
        assert files["firmware/" + component["file"]] == inner[component["file"]]


@pytest.mark.parametrize("author", ["作"*128, "\U00010000"*128])
def test_device_release_accepts_unicode_author_limit(author):
    _, _, raw = upload()
    release = validate_release(raw)
    _, files = release.device_release("app-one", "042731", "release-one", author=author)
    assert json.loads(files["manifest.json"])["author"] == author


@pytest.mark.parametrize("author", [None, {}, 7, "", " \t\n", "作"*129])
def test_device_release_rejects_invalid_author(author):
    _, _, raw = upload()
    release = validate_release(raw)
    with pytest.raises(ContentError):
        release.device_release("app-one", "042731", "release-one", author=author)


@pytest.mark.parametrize("kind", ["extra", "missing", "hash", "size", "locale", "icon-width", "icon-rgb", "glyph", "font", "external-image", "reference", "firmware", "protected"])
def test_package_semantic_rejection(kind):
    manifest, files, _ = upload()
    view = manifest["device"]["presentations"][1]
    if kind == "extra": files["extra.txt"] = b"unlisted"
    if kind == "missing": files.pop("device/en/font.miff")
    if kind == "hash": files["device/en/font.miff"] += b"changed"
    if kind == "size": view["assets"][0]["size"] += 1
    if kind in ("locale", "glyph", "reference"):
        display = json.loads(files["device/en/display.json"])
        if kind == "locale": display["locale"] = "fr"
        if kind == "glyph": display["name"]["glyphs"][0][0] = 999
        if kind == "reference": display["name"]["font"] = "../zh-CN/font.miff"
        files["device/en/display.json"] = encoded(display)
        view["display"] = ref("device/en/display.json", files["device/en/display.json"])
    if kind in ("icon-width", "icon-rgb", "font"):
        path = "device/en/font.miff" if kind == "font" else "device/en/icon.png"
        data = b"bad-font" if kind == "font" else png(63)
        if kind == "icon-rgb":
            from PIL import Image
            output = io.BytesIO(); Image.new("RGB", (64, 64)).save(output, format="PNG"); data = output.getvalue()
        files[path] = data
        view["assets"] = [ref(a["path"], files[a["path"]]) for a in view["assets"]]
    if kind == "external-image":
        files["website/readme.md"] = b"![external](https://example.com/image.png)"
        manifest["website"]["readme"] = ref("website/readme.md", files["website/readme.md"])
    if kind in ("firmware", "protected"):
        inner = read_archive(files["firmware/application.irisfw"])
        firmware = json.loads(inner["manifest.json"])
        if kind == "firmware": inner["app.bin"] = b"not-an-app"
        else: firmware["components"][1]["target_offset"] = 0x20000
        inner["manifest.json"] = encoded(firmware)
        files["firmware/application.irisfw"] = archive(inner)
        manifest["firmware"] = ref("firmware/application.irisfw", files["firmware/application.irisfw"])
    files["manifest.json"] = encoded(manifest)
    with pytest.raises(ContentError): validate_release(archive(files))


@pytest.mark.parametrize("name", ["../x", "/x", "a/../b", "a%20b", "a\\b", "a/b/c/d/e", "a"*65, "中文"])
def test_zip_paths_are_checked_before_extraction(name):
    with pytest.raises(ContentError): read_archive(archive({name:b"content"}))


def test_zip_case_collisions_and_links():
    with pytest.raises(ContentError): read_archive(archive({"a":b"one", "A":b"two"}))
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        info = zipfile.ZipInfo("link"); info.create_system = 3; info.external_attr = 0o120777 << 16
        z.writestr(info, b"../target")
    with pytest.raises(ContentError): read_archive(data.getvalue())


def test_zip_byte_budgets_and_directory_parents():
    with pytest.raises(ContentError): read_archive(archive({"big":b"x"*1000}), limit=500)
    with pytest.raises(ContentError): read_archive(archive({"empty/":b""}))
    assert read_archive(archive({"a/":b"", "a/file":b"x"})) == {"a/file":b"x"}


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":"\\u0000"}', b'{"x":"\\ud800"}', b'{"x":"\xff"}', b'[] trailing', b'['*20+b'0'+b']'*20])
def test_json_has_no_ambiguous_decodings(raw):
    with pytest.raises(ContentError): strict_json(raw)


@pytest.fixture
def server(tmp_path):
    store = Store(tmp_path / "state")
    server = IdeasServer(("127.0.0.1", 0), store, "fixture-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield server, ReleaseClient("http://127.0.0.1:" + str(server.server_port), "fixture-token"), store
    server.shutdown(); server.server_close(); thread.join()


def publish_draft(client, directory, version="1.0.0", mode="create", **target):
    _, _, raw = upload(version)
    path = directory / (uuid.uuid4().hex + ".zip"); path.write_bytes(raw)
    metadata = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    result = upload_archive(client, path, sha256=metadata["sha256"], update=target.get("public_id"))
    return result, metadata, path


def get(server, path, accept="application/json", *, device_id=None):
    c = http.client.HTTPConnection("127.0.0.1", server.server_port)
    request_headers = {"If-None-Match":"*", "Accept":accept}
    if device_id is not None:
        request_headers["X-Device-ID"] = device_id
    c.request("GET", path, headers=request_headers)
    response = c.getresponse(); data = response.read(); status = response.status; headers = dict(response.getheaders()); c.close()
    return status, headers, data


CAPS = "?profile=esp-mosaico%2Fv2&chip_id=32&flash_size=16777216&recovery_version=0.2.0"


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_one_response_contains_complete_preview_of_one_snapshot(server, tmp_path, locale):
    http, client, store = server
    result, _, _ = publish_draft(client, tmp_path)
    assert result["app_number"] is None
    assert get(http, "/api/v1/ideas/201000/manifest.json" + CAPS + "&locale=" + locale, "multipart/related")[0] == 404
    result.update(store.publish(result["public_id"], author="联调作者"))
    latest = "/api/v1/ideas/" + result["app_number"] + "/manifest.json"
    query = latest + CAPS + "&locale=" + locale
    status, headers, raw = get(http, query, "multipart/related")
    assert status == 200 and headers["Cache-Control"] == "no-store" and headers["Vary"] == "Accept"
    assert headers["ETag"] == '"' + hashlib.sha256(raw).hexdigest() + '"'
    message = BytesParser(policy=email_policy).parsebytes(
        ("Content-Type: " + headers["Content-Type"] + "\r\n\r\n").encode() + raw)
    assert not message.defects and message.get_content_type() == "multipart/related"
    parts = list(message.iter_parts())
    files = {part["Content-Location"]: part.get_payload(decode=True) for part in parts}
    assert len(files) == len(parts)
    for part in parts:
        assert len(part.get_payload(decode=True)) == int(part["Content-Length"])
    root = json.loads(files["manifest.json"])
    assert root["release_id"] == result["release_id"]
    assert root["author"] == "联调作者"
    view = next(p for p in root["device"]["presentations"] if p["display"]["path"] == f"device/{locale}/display.json")
    refs = [root["firmware"]["manifest"], view["display"], *view["assets"]]
    assert list(files) == ["manifest.json", *[r["path"] for r in refs]]
    for ref in refs:
        assert len(files[ref["path"]]) == ref["size"]
        assert hashlib.sha256(files[ref["path"]]).hexdigest() == ref["sha256"]
    fixed = latest.replace("/manifest.json", "/releases/" + result["release_id"] + "/manifest.json")
    assert get(http, fixed)[2] == files["manifest.json"]
    assert get(http, query, "multipart/related")[2] == raw
    # Product-wide identity metadata must not alter API negotiation or bytes.
    assert get(http, query, "multipart/related", device_id="4553502d495249530100001122334455")[2] == raw
    # Neither a firmware binary nor the other language is needed to render.
    assert not any(path.endswith(".bin") for path in files)
    assert get(http, latest + CAPS, "text/html")[0] == 406
    assert get(http, latest + CAPS, "multipart/related")[0] == 400
    assert get(http, query + "&locale=" + locale, "multipart/related")[0] == 400
    assert get(http, latest + CAPS + "&locale=fr", "multipart/related")[0] == 400
    assert get(http, query)[0] == 400
    assert get(http, query + "&device_id=4553502d495249530100001122334455", "multipart/related")[0] == 400
    assert get(http, fixed, "multipart/related")[0] == 400


def test_preview_rejects_damaged_published_asset(server, tmp_path):
    http, client, store = server
    result, _, _ = publish_draft(client, tmp_path)
    result.update(store.publish(result["public_id"]))
    root, _ = store.manifest(result["app_number"], release_id=result["release_id"])
    ref = json.loads(root)["device"]["presentations"][0]["display"]
    store.blob(ref["sha256"]).write_bytes(b"damaged")
    path = "/api/v1/ideas/" + result["app_number"] + "/manifest.json" + CAPS + "&locale=zh-CN"
    assert get(http, path, "multipart/related")[0] == 503


def test_draft_publication_immutable_get_and_bilingual_download(server, tmp_path):
    http, client, store = server
    result, _, _ = publish_draft(client, tmp_path)
    assert result["status"] == "draft" and result["app_number"] is None
    assert get(http, "/api/v1/ideas/201000/manifest.json" + CAPS)[0] == 404
    result.update(store.publish(result["public_id"]))
    latest = "/api/v1/ideas/" + result["app_number"] + "/manifest.json"
    status, headers, raw = get(http, latest + CAPS)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert headers["ETag"] == '"' + hashlib.sha256(raw).hexdigest() + '"'
    fixed = latest.replace("/manifest.json", "/releases/" + result["release_id"] + "/manifest.json")
    assert get(http, fixed)[2] == raw
    root = json.loads(raw)
    assert root["author"] == "Mosaico Test Account"
    refs = [root["firmware"]["manifest"]]
    for p in root["device"]["presentations"]: refs += [p["display"]] + p["assets"]
    for f in refs:
        status, headers, content = get(http, "/api/v1/ideas/files/" + f["sha256"])
        assert status == 200 and len(content) == f["size"] and hashlib.sha256(content).hexdigest() == f["sha256"]
    assert get(http, latest)[0] == 400
    assert get(http, latest + CAPS + "&chip_id=32")[0] == 400
    assert get(http, latest + CAPS.replace("16777216", "8388608"))[0] == 409
    assert get(http, fixed + CAPS)[0] == 400


def test_file_device_identity_preserves_published_bytes(server, tmp_path):
    http, client, store = server
    result, _, _ = publish_draft(client, tmp_path)
    result.update(store.publish(result["public_id"]))
    raw, _ = store.manifest(result["app_number"], release_id=result["release_id"])
    ref = json.loads(raw)["firmware"]["manifest"]
    path = "/api/v1/ideas/files/" + ref["sha256"]
    status, headers, expected = get(http, path)
    assert status == 200
    assert get(http, path, device_id="4553502d495249530100001122334455")[2] == expected
    for identity in ("4553502d495249530100001122334455", "4553502d495249530100aabbccddeeff", "x" * 128):
        status, identified_headers, actual = get(http, path + "?device_id=" + identity)
        assert status == 200 and actual == expected
        assert identified_headers["Cache-Control"] == headers["Cache-Control"]
        assert hashlib.sha256(actual).hexdigest() == ref["sha256"]
    for query in ("device_id=", "device_id=" + "x" * 129,
                  "device_id=a&device_id=b", "unknown=a", "device_id=a&unknown=b"):
        assert get(http, path + "?" + query)[0] == 400


def test_draft_reuploads_are_last_write_wins_without_allocating_app_numbers(server, tmp_path):
    _, client, store = server
    result, _, _ = publish_draft(client, tmp_path)
    for version in ("2.0.0", "2.0.0", "1.0.0"):
        updated, _, _ = publish_draft(client, tmp_path, version, public_id=result["public_id"])
        assert updated == result
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM agent_projects").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM agent_releases").fetchone()[0] == 0
    published = store.publish(result["public_id"])
    raw, _ = store.manifest(published["app_number"])
    root = json.loads(raw)
    manifest = json.loads(store.blob(root["firmware"]["manifest"]["sha256"]).read_bytes())
    assert manifest["release"] == "1.0.0"


def test_published_version_is_unique_per_application_and_snapshot_is_immutable(server, tmp_path):
    _, client, store = server
    result, _, _ = publish_draft(client, tmp_path)
    published = store.publish(result["public_id"], author="First Author")
    original = store.manifest(published["app_number"], release_id=published["release_id"])
    assert json.loads(original[0])["author"] == "First Author"
    with pytest.raises(PlatformError) as error:
        publish_draft(client, tmp_path, public_id=result["public_id"])
    assert error.value.code == "VERSION_ALREADY_PUBLISHED" and error.value.status == 409
    updated, _, _ = publish_draft(client, tmp_path, "2.0.0", public_id=result["public_id"])
    assert updated["app_number"] == published["app_number"]
    assert store.manifest(published["app_number"]) == original
    second = store.publish(result["public_id"], author="Second Author")
    assert second["release_id"] != published["release_id"]
    assert json.loads(store.manifest(published["app_number"])[0])["author"] == "Second Author"
    assert store.manifest(published["app_number"], release_id=published["release_id"]) == original
    # A separate application is allowed to use the same release string.
    other, _, _ = publish_draft(client, tmp_path)
    assert store.publish(other["public_id"])["app_number"] != published["app_number"]


def test_publish_command_freezes_author_and_invalid_author_preserves_draft(tmp_path, capsys):
    from mosaico_cli.ideas_test_server import main
    store = Store(tmp_path / "state")
    _, _, raw = upload()
    draft = store.save_draft("owner", raw)
    args = ["--state", str(store.root), "publish", draft["public_id"], "--author"]
    with pytest.raises(ContentError):
        main([*args, " \t"])
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM agent_releases").fetchone()[0] == 0
        assert db.execute("SELECT app_number FROM agent_projects").fetchone()[0] is None
    main([*args, "测试作者"])
    published = json.loads(capsys.readouterr().out)
    root, sha = Store(store.root).manifest(published["app_number"])
    assert json.loads(root)["author"] == "测试作者"
    assert hashlib.sha256(root).hexdigest() == sha


def test_draft_survives_restart_and_failed_validation_preserves_previous_content(tmp_path):
    store = Store(tmp_path / "state")
    _, _, raw = upload()
    result = store.save_draft("owner", raw)
    with pytest.raises(ContentError): store.save_draft("owner", b"invalid", result["public_id"])
    with pytest.raises(ContentError): store.save_draft("another-owner", raw, result["public_id"])
    published = Store(store.root).publish(result["public_id"])
    assert published["app_number"] == "201000"
    assert Store(store.root).manifest(published["app_number"])[0]


def test_retry_after_seconds_and_date():
    from email.utils import formatdate
    assert retry_after("15") == 15
    assert 0 < retry_after(formatdate(time.time() + 30, usegmt=True)) <= 30
    assert retry_after("nonsense") == 0


@pytest.mark.parametrize("category_id", [None, 123])
def test_prebuilt_packaging_is_deterministic_and_preserves_display_bytes(tmp_path, category_id):
    from mosaico_cli.ideas_archive import package_project
    root, files, _ = upload()
    if category_id is not None:
        root["project"]["category_id"] = category_id
    for name, raw in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    config = dict(schema="mosaico-ideas/project-release/1", project=root["project"],
                  firmware=root["firmware"]["path"], website=dict(readme="website/readme.md"),
                  device=dict(default_locale="zh-CN", presentations={
                      locale: dict(mode="prebuilt", display="device/"+locale+"/display.json") for locale in ("zh-CN", "en")}))
    (tmp_path / "mosaico-ideas.json").write_bytes(encoded(config))
    one, two = tmp_path / "one.zip", tmp_path / "two.zip"
    assert package_project(tmp_path, one)["sha256"] == package_project(tmp_path, two)["sha256"]
    assert one.read_bytes() == two.read_bytes()
    result = validate_release(one)
    assert result.manifest["project"] == config["project"]
    for locale in ("zh-CN", "en"):
        path = "device/"+locale+"/display.json"
        assert result.files[path] == files[path]
    config["device"]["presentations"]["en"]["name"] = "Mixed input is forbidden"
    (tmp_path / "mosaico-ideas.json").write_bytes(encoded(config))
    with pytest.raises(ContentError): package_project(tmp_path, two)
    assert one.read_bytes() == two.read_bytes(), "Failed packaging must preserve an existing archive"


def test_account_identity_survives_token_rotation_and_restart(server, tmp_path):
    http, client, store = server
    owner = client.request("GET", "/auth/cli/token")["user"]["id"]
    result, request, package = publish_draft(client, tmp_path)
    http.token = "rotated-token"
    rotated = ReleaseClient(client.server, "rotated-token")
    assert rotated.request("GET", "/auth/cli/token")["user"]["id"] == owner
    with pytest.raises(PlatformError) as error: client.request("GET", "/auth/cli/token")
    assert error.value.status == 401
    update, _, _ = publish_draft(rotated, tmp_path, mode="update",
        public_id=result["public_id"])
    assert update["public_id"] == result["public_id"] and update["app_number"] is None
    assert Store(store.root).account_id("a-new-token-hash") == str(owner)


@pytest.mark.parametrize("description", ["Clear skies.", "", None])
def test_generated_packaging_uses_shared_resources_and_is_repeatable(tmp_path, description):
    from ctypes.util import find_library
    if not find_library('raqm'):
        pytest.skip('Native text shaping requires libraqm')
    from mosaico_cli.ideas_archive import package_project
    from shared.ideas import generate_resources
    root, files, _ = upload()
    for name in (root['firmware']['path'], 'website/readme.md'):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[name])
    font = tmp_path / 'font.ttf'
    font.write_bytes((ROOT / 'mosaico-tools/templates/hello_world/components/app_hello/ui/fonts/DejaVuSans.ttf').read_bytes())
    text = dict(name='Weather')
    if description is not None:
        text['description'] = description
    config = dict(schema='mosaico-ideas/project-release/1', project=root['project'],
                  firmware=root['firmware']['path'], website=dict(readme='website/readme.md'),
                  device=dict(default_locale='zh-CN', presentations={
                      locale: dict(mode='generate', font='font.ttf', **text) for locale in ('zh-CN', 'en')}))
    (tmp_path / 'mosaico-ideas.json').write_bytes(encoded(config))
    one, two = tmp_path / 'one.zip', tmp_path / 'two.zip'
    assert package_project(tmp_path, one)['sha256'] == package_project(tmp_path, two)['sha256']
    result = validate_release(one)
    for locale in ('zh-CN', 'en'):
        for name, data in generate_resources(locale=locale, font=font, name=text['name'], description=description or '').items():
            assert result.files['device/' + locale + '/' + name] == data


@pytest.mark.parametrize("content_type", [None, "software", "hardware"])
def test_minimal_metadata_empty_description_and_no_icon_pass_upload(server, tmp_path, content_type):
    _, client, store = server
    manifest, files, _ = upload()
    manifest["project"] = {"title": "Minimal project"}
    if content_type is not None:
        manifest["project"]["content_type"] = content_type
    for view in manifest["device"]["presentations"]:
        path = view["display"]["path"]
        display = json.loads(files[path])
        icon = str(PurePosixPath(path).parent / display["icon"])
        files.pop(icon)
        display["icon"] = ""
        display["description"]["text"] = ""
        display["description"]["glyphs"] = []
        files[path] = encoded(display)
        view["display"] = ref(path, files[path])
        view["assets"] = [a for a in view["assets"] if a["path"] != icon]
    files["manifest.json"] = encoded(manifest)
    package = tmp_path / "minimal.zip"; package.write_bytes(archive(files))
    validated = validate_release(package)
    result = upload_archive(client, package, sha256=validated.archive_sha256)
    assert result["status"] == "draft" and result["app_number"] is None
    published = store.publish(result["public_id"])
    root = json.loads(store.manifest(published["app_number"])[0])
    assert len(root["device"]["presentations"]) == 2
    for view in root["device"]["presentations"]:
        assert len(view["assets"]) == 1
        display = json.loads(store.blob(view["display"]["sha256"]).read_bytes())
        assert display["description"]["text"] == display["icon"] == ""


def test_project_upload_does_not_require_account_lookup_or_cloud_app_id(server, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from mosaico_cli.platform_upload import project_upload
    _, client, _ = server
    manifest, files, _ = upload()
    manifest["project"]["category_id"] = 123
    files["manifest.json"] = encoded(manifest)
    raw = archive(files)
    package = tmp_path / "release.zip"; package.write_bytes(raw)
    monkeypatch.setenv("MAKER_SPARK_TOKEN", "fixture-token")
    args = SimpleNamespace(create=True, update=None, yes=True, json=True,
                           package=str(package), server=client.server, ca_file=None)
    result = project_upload(args, None)
    assert result["status"] == "draft" and result["app_number"] is None
    assert result["version"] == "1.0.0" and result["archive_sha256"] == hashlib.sha256(raw).hexdigest()
    args.create, args.update = False, result["public_id"]
    assert project_upload(args, None)["public_id"] == result["public_id"]


@pytest.mark.parametrize("category_id", [None, True, False, 0, -1, 1.5, "123", [], {}])
def test_release_and_author_schemas_reject_invalid_category_ids(category_id):
    from jsonschema import Draft202012Validator
    manifest, files, _ = upload()
    manifest["project"]["category_id"] = category_id
    files["manifest.json"] = encoded(manifest)
    with pytest.raises(ContentError):
        validate_release(archive(files))
    schema = json.loads((ROOT / "mosaico-tools/mosaico-ideas.schema.json").read_text())
    # Author and ZIP metadata use the same category ID contract.
    project_schema = schema["properties"]["project"]
    assert list(Draft202012Validator(project_schema).iter_errors(manifest["project"]))


@pytest.mark.parametrize("content_type", [None, "hardware"])
@pytest.mark.parametrize("update", [None, "existing-draft"])
def test_upload_without_category_stops_before_credentials_or_network(tmp_path, monkeypatch, content_type, update):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from mosaico_cli.errors import SelectionError
    from mosaico_cli.platform_upload import project_upload
    manifest, files, _ = upload()
    manifest["project"] = {"title": "Uncategorized"}
    if content_type is not None:
        manifest["project"]["content_type"] = content_type
    files["manifest.json"] = encoded(manifest)
    package = tmp_path / "release.zip"
    package.write_bytes(archive(files))
    credential = Mock()
    client = Mock()
    monkeypatch.setattr("mosaico_cli.platform_upload.credential", credential)
    monkeypatch.setattr("mosaico_cli.platform_upload.ReleaseClient", client)
    args = SimpleNamespace(create=update is None, update=update, yes=True, json=True,
                           package=str(package), server="https://example.test", ca_file=None)
    with pytest.raises(SelectionError, match="project.category_id") as raised:
        project_upload(args, None)
    assert "group=" + (content_type or "software") in str(raised.value)
    credential.assert_not_called()
    client.assert_not_called()

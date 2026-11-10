# Complete preview in a single response

After code entry, one successful HTTP request must return every file needed for complete details. This changes
HTTP representation only, not upload ZIP, device-release/1, display/1 or NAND directory formats.
Cancellation, error responses and validation failures must neither write NAND nor fall back to per-file GETs to repair previews.

## Request and response

```http
GET /api/v1/ideas/042731/manifest.json?profile=esp-mosaico%2Fv2&chip_id=32&flash_size=16777216&recovery_version=0.2.0&locale=zh-CN HTTP/1.1
Accept: multipart/related
Accept-Encoding: identity
```

Device capabilities and compatible-release selection retain the main protocol's semantics. Locale must appear exactly once as zh-CN or en.
Language selects presentation resources only, without changing release selection, root manifest or release_id. Success returns
200, Cache-Control: no-store, Vary: Accept and multipart/related.
There is no resolve, redirect, preview-URL lookup or other preliminary request. Accept allows at most one value; unknown representations
return 406 NOT_ACCEPTABLE. Weighted media-type lists are unsupported.

```http
Content-Type: multipart/related; type="application/json"; boundary="BOUNDARY"
Content-Length: <total-response-body-bytes>
ETag: "<64-character-lowercase-SHA-256-of-entire-response-body>"
```

Uses a restricted [RFC 2387](https://www.rfc-editor.org/rfc/rfc2387.html) profile: the server sends
type=application/json, root manifest first, without start. Boundary is 1–70
ASCII letters, digits, underscores or hyphens; parameter order is irrelevant and quoting is allowed. Devices read only
boundary, requiring exactly one occurrence, and ignore type/other parameters to permit future CDN/server additions.
The server ensures the chosen boundary does not collide with body content.

Requests retain the manifest's 30-second total budget. Transient network faults allow at most three additional retries. One successful
attempt has exactly one preview HTTP request; retries are not extra dependency-file requests. Each retry clears the previous
incomplete manifest, resources and parser state; bytes from different attempts must not be mixed.

## Part order and constraints

Send exactly 4–6 parts in this order:

1. manifest.json: original published device root manifest.
2. firmware/manifest.json: original firmware-installation manifest referenced by the root.
3. device/<selected-locale>/display.json: original presentation descriptor for that language.
4. Every file in that language's presentations[].assets, strictly in array order.

Root `author` is the author's display name; see the [download schema](download-manifest.schema.json).
New releases must include it; historical frozen releases may omit it. It freezes with the root, independent of locale,
without a separate MIME part. JSON representation and the first multipart part use identical original root bytes.

Servers send these three headers per part, case-insensitive and in any order. Devices require
exactly one Content-Location and Content-Length, ignoring Content-Type and other headers:

```http
--BOUNDARY
Content-Type: application/json
Content-Location: manifest.json
Content-Length: <positive-integer-part-body-bytes>

<original-file-bytes>
```

Illustrated newlines must be CRLF on the wire. The first three parts use Content-Type
application/json; font/icon parts use application/octet-stream with raw
binary, not Base64 or Content-Transfer-Encoding. Content-Location is the exact collection
path, not a download URL. Each header line is at most 255 bytes including CRLF.

Before the first part, send `--BOUNDARY\r\n`. Headers end in `\r\n\r\n`; bodies are followed by
`\r\n--BOUNDARY\r\n`, or final `\r\n--BOUNDARY--\r\n`. Reject preamble,
epilogue, nested multipart, extra parts, unknown files, other-language files and firmware-component binaries.
Read bodies using lengths from validated manifests and verify following boundaries; arbitrary
newlines inside binary data do not mark file endings.

| Scope | Byte limit |
| --- | ---: |
| Root manifest | 65536 |
| Firmware manifest | 3072 |
| Selected-language display, fonts and icon combined | 1048576 |
| All part headers, boundaries and separator CRLF combined | 4096 |
| Entire response body | 1121280 |

Display's 32 KiB and icon's 64 KiB/64×64 content rules still apply. The complete collection must
contain both languages within 32 MiB/32 files; preview is a fixed verifiable subset.
HTTP Content-Length may be omitted, using actual streamed byte counts; if supplied, it must be accurate.
Per-part Content-Length is required and must match manifest declarations; the first part also obeys the root limit.

## Integrity, caching and display

HTTP ETag covers the complete response including headers/boundaries, not the root digest.
CDNs may rewrite it as weak ETag; devices do not validate it. HTTPS/TLS and per-part lengths/
SHA-256 provide integrity.
Devices separately compute root_sha256 over the first part's original bytes for release pinning, same-release_id content
conflict detection and local transactions. Languages/MIME boundaries may yield different ETags, but one release's
root_sha256 must match. Roots omit their own digest; trust still comes from HTTPS/TLS.

Root references validate actual firmware-manifest/display/resource lengths and SHA-256. Parse firmware
manifests for version, full component index and sizes, then validate target compatibility, display, fonts and icons.
Publish a confirmable complete preview only after the entire response and every file pass.
Stream each file directly into PSRAM preview caches, with no extra whole-response copy and no NAND writes.

After confirmation, save original root bytes and reuse verified firmware manifests/current-language resources,
requesting only firmware components and the other language. Never refetch latest or save multipart wrapping
as manifest.json. Cancellation frees every cache; leave preview before switching system language.

Diagnostics may request application/json from the same endpoint (omitted Accept or */* is equivalent),
omitting locale; response is the original root with ETag over its bytes. Pinned-release endpoints
offer only this JSON representation. These are neither legacy compatibility nor preview-failure fallbacks.

## Acceptance

- Normal Chinese/English previews each use one HTTP request and fully show icon, text, version and size.
- Before confirmation: no file GET, NAND write, firmware install or boot-target change.
- Confirmation reuses caches; publication changes after preview cannot mix releases.
- Single-byte network fragments and headers/boundaries spanning reads parse correctly.
- Reject truncation, missing/duplicate/extra parts, wrong paths/languages/order/lengths, digests, excessive sizes, duplicate
  Content-Location/Content-Length and duplicate boundary. Ignore unknown part headers/MIME parameters;
  failed validation cannot append GETs to repair responses.
- Midstream cancellation/retry clears partial state; later normal requests succeed and downloaded bilingual resources work offline.

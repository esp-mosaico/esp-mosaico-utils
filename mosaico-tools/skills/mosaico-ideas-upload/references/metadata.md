# Author configuration and display resources

Application-root `mosaico-ideas.json` uses `mosaico-ideas/project-release/1`.
It is packaging input; the output ZIP root manifest uses `mosaico-ideas/release/1`, while the inner `.irisfw`
uses `esp-iris-system-update/0.2`. These manifests serve different purposes.

| Input | Requirement |
| --- | --- |
| `project.title` | Actual application title, 1–200 characters |
| `project.content_type` | Optional `hardware` or `software`; cloud treats omission as software |
| `project.category_id` | Required for upload: positive integer category ID from the target site; category must exist, be enabled and match content_type |
| `project.boards` | Optional camera, ethernet, battery; at most two entries |
| `project.tags` | At most 20 unique tags, 1–50 characters each |
| `project.external_links` | At most 10 entries with label, HTTP(S) url and platform; platform is github, oshwhub, makerworld or other |
| `firmware` | Application-relative path to a built `.irisfw`; may also be supplied with `project package --bundle` |
| `website.readme` | Required relative path to a nonempty UTF-8 Markdown file |
| `website.changelog` | Optional Markdown file path, not inline text |
| `website.covers/resources/attachments` | Arrays of relative paths to website materials, not firmware resource-partition images |
| `device.default_locale` | zh-CN or en |
| `device.presentations` | Must contain both zh-CN and en |

Do not supply `categories` or `license`; remove those two publishing fields from old configurations. Do not delete the application's
LICENSE file or meaningful README licensing text. Do not add platform APP IDs, six-digit codes or release-identity fields.

## Choose a site category

Before packaging, fetch categories from the upload target's public endpoint (no token required):

```bash
curl --fail --silent --show-error "$IDEAS_SERVER/api/v1/categories?group=software"
# For hardware applications, use ?group=hardware and set project.content_type to hardware.
```

`IDEAS_SERVER` must use the same Origin as upload `--server`; the default is `https://mosaico.ai`.
Select an item by actual functionality from returned `{id, name, name_en}` entries. Write its integer `id` to
`project.category_id` in `mosaico-ideas.json`, then run `project package`.
Replace template `category_id: null` with a real ID. Do not guess IDs or substitute category names or legacy `categories` arrays.
Category IDs belong to the target site; recheck them when changing server or content_type.

The API and local schema permit omitted categories for offline packaging/validation, but the current CLI upload flow requires one.
The packager copies this field into ZIP `manifest.json/project`; upload adds no separate multipart category field
and does not modify an existing ZIP. The cloud validates existence, enabled state and group; select one category per application.
PATCH replaces metadata as a whole, so draft replacements must include category too.

## Bilingual descriptions and icons

Each language defaults to generated mode: `name` and `font` are required; `description` may be absent/empty,
and `icon` may be absent/empty. Prefer bilingual descriptions based on real functionality and a reused or generated suitable icon,
but packaging/upload may proceed without assets or reliable text. Never invent features to fill a description.

Names are nonempty and at most 128 UTF-8 bytes; descriptions at most 512 UTF-8 bytes. The packager generates MIFF subsets,
glyph positions and display.json. Name regions are 328×84 and descriptions 416×176; actual glyphs must fit.
Text permits newline as the only control character. Website titles, README content and other-language text are not automatic fallbacks.

Source icons may be single-frame JPEG, PNG, GIF or WebP, at most 10 MiB and 4096 px per dimension.
The packager scales proportionally and adds transparent padding to create 64×64 RGBA PNG. Both languages may reference one source file.
Output must be 8-bit RGBA, non-interlaced, non-animated PNG, at most 64 KiB. Invalid images are still rejected.
Without an icon, output display.json uses an empty icon string; no placeholder PNG is required.

Advanced input supports `{"mode":"prebuilt","display":"device/en/display.json"}`,
with fonts and optional icons beside display. This mode validates unchanged files without reflow or image repair.
Even an empty description requires a finished description object and valid font reference.
One language cannot mix generated and prebuilt fields.

## Files and versions

Paths are application-relative; reject escapes, symlinks, spaces, percent encoding and paths exceeding protocol depth.
README-embedded resources must be explicitly declared in the ZIP; there is no automatic scan, supplemental upload or rewrite of author files.
README: at most 100000 characters / 400000 bytes; changelog: at most 10000 characters / 40000 bytes.
Bilingual device resources: at most 1 MiB per language. Complete device set: at most 32 files / 32 MiB.

Firmware version comes from `.irisfw` manifest.release: 1–64 characters, starting with an ASCII letter/digit,
containing only letters, digits, dots, underscores, pluses and hyphens. Change the project's actual version source and rebuild.
Do not edit ZIP manifests to impersonate a new firmware version. The cloud rejects an already-published release for the same application;
an unpublished draft of the same version can be replaced repeatedly. The CLI does not determine whether a cloud version is published.

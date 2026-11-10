---
name: mosaico-ideas-upload
description: "Prepare bilingual Mosaico Ideas release ZIPs, validate Iris firmware and display resources, and create or replace cloud drafts through the ESP-Mosaico CLI. Use for metadata preparation, Iris packaging, project uploads, version updates and upload diagnostics; not for device flashing or submitting reviews."
---

# Mosaico Ideas draft uploads

Prepare `mosaico-ideas.json` in the consuming application repository, package one release ZIP offline, then
create or replace a draft through the Agent API. Upload success means a saved draft only; review and publication happen on the website.

## Scope and entry points

- Use the consuming workspace's `mosaico.py` and pinned utils/ESP-Iris versions. This tools repository is not the application to upload.
- If the user requests only metadata or packaging, finish locally. If upload is authorized, proceed directly; clarify only missing targets or required inputs.
- Create with `--create`; replace using the cloud project's `public_id`. Never infer the target from a title, directory name or six-digit APP code.
- This flow excludes device writes, review submission and publication. Do not call `iris system-update` for packaging.

## Prepare content

Follow the [metadata rules](references/metadata.md) and [configuration template](assets/mosaico-ideas.json).
Preserve user content in existing configuration. Replace template titles, category ID, firmware paths, both language names and font paths with real values.
Before upload, fetch the target site's categories, select one matching `content_type` and put its integer ID in
`project.category_id`; see the metadata rules. Do not supply legacy `categories` or `license` fields,
or place account, project identity or APP codes in the upload ZIP.

Provide Chinese/English descriptions and a suitable icon where possible:

- Derive concise bilingual descriptions from code, existing READMEs and actual behavior; do not invent features or test results.
- Prefer an existing application icon. If absent, generate a suitable icon when the current task permits it and tools are available.
  Both languages may use the same source image, normalized by the packager into device format.
- This is best-effort content improvement, not an upload gate. Use an empty string when a description cannot be drafted reliably,
  and omit icon when none is suitable. Do not stop or repeatedly request assets solely for these omissions.
- Both language names and required fonts must remain valid. Changing another language's locale is not translation.

## Build and upload

1. Obtain the current `.irisfw` following [packaging and image checks](references/bundle.md).
2. Generate and validate the ZIP with `project package --project "$PROJECT" --output "$RELEASE_ZIP"`.
3. Independently recheck with `project validate "$RELEASE_ZIP" --json` if needed.
4. Only when upload is in scope, follow [login and upload](references/upload.md) to authenticate and create/replace a draft.

`project upload` reads an existing ZIP only; it neither builds nor generates resources, and has no `--skip-build`,
`--version`, `--expected-project-version` or upload-task polling arguments.

## Verify and hand off

Record `public_id`, `status: draft`, local version and archive SHA-256; include a draft link when the server supplies one.
Version and digest are local-artifact checks by the tool, not a server-issued verification receipt.
APP ID, six-digit code and device-release identity are cloud-generated; a draft without a code is still successful.

Every explicit replacement sends PATCH; the latest valid upload replaces the unsubmitted draft. If the cloud rejects an already-published application version,
report the error and have the author change the actual version and rebuild. Do not switch projects, fall back to create or edit the package version automatically.
If the response is lost, inspect the website first; repeating create is not a recovery mechanism. Report actual validation and cloud outcomes at handoff.

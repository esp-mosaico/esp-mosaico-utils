# Login and synchronous draft upload

Run these commands in the consuming workspace. The server is an HTTPS Origin without `/api/v1`.
Precedence: `--server`, `MOSAICO_IDEAS_SERVER`, `MAKER_SPARK_SERVER`, then default `https://mosaico.ai`.

First follow [category selection](metadata.md#choose-a-site-category), fetch the target site's categories and populate
`project.category_id` in author configuration. Repackage and validate before uploading. The CLI rejects old ZIPs missing this field before sending requests.
The category belongs inside the ZIP; do not add `--category` or extra multipart fields.

```bash
python mosaico.py account status --server "$IDEAS_SERVER"
python mosaico.py account login --server "$IDEAS_SERVER" --open-browser
python mosaico.py project upload "$RELEASE_ZIP" --server "$IDEAS_SERVER" --create --yes --json
python mosaico.py project upload "$RELEASE_ZIP" --server "$IDEAS_SERVER" --update "$PUBLIC_ID" --yes --json
```

Start the device-code flow only when login is needed; the user completes browser authorization. Environment variable `MAKER_SPARK_TOKEN`
takes precedence over the privately stored token. Never put credentials in command arguments, packages or logs. Private credentials reside in
`state_root("esp-mosaico")/0.2/mosaico-ideas/<server-hash>/`; old-version state is not imported automatically.
`account logout` revokes the selected token.

Choose create or replace explicitly; do not repeatedly reconfirm existing authorization. `--yes` supports authorized unattended upload;
`--json` is not a dry run. Update targets are server project public_id values, not six-digit APP codes.
Never infer the target from a matching title. If unknown, confirm it on the website and use its public_id.

The tool validates the existing ZIP, then sends it as one multipart `release` file: POST `/agent/projects` for creation,
PATCH `/agent/projects/{public_id}` for replacement. Success is 201 for creation and, under the supplementary contract, 200 for replacement,
returning ProjectDetail. `public_id` is the preferred field; the current client also accepts alias `code`.
Unsubmitted drafts may be replaced repeatedly; the latest valid upload wins without requiring a draft version number.

Success output includes public_id, draft status and local version/archive_sha256; app_number may be null or absent.
Show draft_url if supplied; otherwise report public_id and direct the user to the website without guessing routes.
There is no task ID, asynchronous polling or local-receipt shortcut. Every explicit invocation sends a new request.

## Failure handling

- POST/PATCH are not automatically retried; the server has no idempotency contract. A lost creation response may still have created a draft.
  Inspect the website after network failure or uncertain responses before deciding to explicitly replace or create.
- `VERSION_ALREADY_PUBLISHED`: report the published application version; the author must change the actual version and rebuild.
- 401/403 or a project state prohibiting replacement: resolve account/site state, without switching to create or withdrawing review automatically.
- `invalid_release`: fix content using the package path and reason, then repackage and validate. A missing icon or empty description is not itself an error.
- `invalid_category`: category missing, disabled or incompatible with content_type. Use reason/field to
  fetch target-site categories again, correct `project.category_id` (and content_type if necessary), then repackage/upload.
  Do not automatically remove category, change groups or retry another ID.
- 429/5xx: retain the archive, wait as instructed and inspect the website; do not loop write requests.
- Retain machine error codes, request_id and filtered path/field/reason; never expose credentials or URLs from raw server messages.

Upload does not submit for review. Subsequent code allocation, APP ID completion, published-version uniqueness and device-release artifacts belong to the cloud.

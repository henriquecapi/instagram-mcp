# Instagram Graph (custom.instagram-graph)

Publish Instagram feed photos and carousels through the **official
Instagram Graph API**, from a Python MCP server (Streamable HTTP).
Built for the Rotina Culinária routine: publish the 6-card carousels
(1080×1350, 4:5) to @josehenriquecapibaribe, a professional
Business/Creator account linked to a Facebook Page.

This is the official API route — not username/password automation.
No password is used anywhere, and no credential lives in this project.

## Server

- Entry point: `server.py` (Python 3.12, `mcp` 2.x SDK).
- Transport: Streamable HTTP, default `http://127.0.0.1:8765/mcp`
  (override with `MCP_HOST`, `MCP_PORT`, `MCP_PATH`).
- Run: `python3 server.py` (or `uvicorn` via `tests/run_tls.py`
  for the TLS test setup). Install deps first:
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- The server publishes NOTHING on its own. Every publish is a tool
  call made with the user's approval.

## Authentication

- The Graph API access token is resolved per call, in order, from:
  1. The `Authorization: Bearer <token>` header of the MCP request
     (how Muse's secure connection flow hands the token to a hosted
     server — the client sends it as a bearer token).
  2. The `IG_ACCESS_TOKEN` environment variable (local runs only).
- The token is never logged, never written to disk, and never put in
  chat, code, or docs. The IG Business Account id comes from the
  `ig_user_id` argument or the `IG_USER_ID` environment variable.
- Register the connection in Muse as provider
  `custom.instagram-graph` through the secure connection flow; the
  client (`bin/client.py`) sends the surrogate as a bearer header.
- Required token scopes: `instagram_basic`,
  `instagram_content_publish`, `pages_show_list`,
  `pages_read_engagement`. Long-lived user token (~60 days, refresh
  before expiry).

## Client

- `bin/client.py` is the template MCP client, configured with
  `PROVIDER = "custom.instagram-graph"` and
  `ENDPOINT = "https://YOUR-SERVER-HOST/mcp"` — replace
  `YOUR-SERVER-HOST` with the host the server is deployed on (HTTPS,
  port 443). The template refuses any other scheme/port.
- `tests/client_local.py` is a test-only copy pointed at
  `https://127.0.0.1/mcp` with a dummy bearer header (no authd
  credential exists yet); it is not part of the deliverable path.

```text
python3 bin/client.py list-tools
python3 bin/client.py call-tool --name <tool> --arguments-file <args.json>
```

## Allowed tools

Only these three operations are allowed. Anything the server adds
later stays blocked until reviewed and added to `ALLOWED_TOOLS`.

| Tool | Read / Write | Inputs | Output |
|---|---|---|---|
| `account_status` | Read | `ig_user_id?` (string, optional) | `ig_user_id`, `username`, `name`, `profile_picture_url`, `followers_count`, `follows_count`, `media_count`; or `linked_accounts[]` (Page + IG id + username) when discovering from `/me/accounts` |
| `publish_photo` | Write (publishes) | `image_url` (required, public https URL), `caption?`, `ig_user_id?` | `media_id`, `permalink`, `media_url`, `caption` |
| `publish_carousel` | Write (publishes) | `images` (required, 2–10 public https URLs, in display order), `caption?`, `ig_user_id?` | `media_id`, `permalink`, `media_url`, `caption`, `children[]`, `child_container_ids[]` |

How `publish_carousel` works: for each image, create an item
container (`is_carousel_item=true`) and poll until `FINISHED`; then
create the carousel container (`media_type=CAROUSEL`,
`children=<ids>`, `caption`), poll until `FINISHED`, then publish
(`media_publish`). Container polling waits up to 120 s. All images
must share one aspect ratio (Rotina cards: 1080×1350, 4:5).

## Limits and failure modes

- Instagram fetches media from a **public https URL**. A local file
  path is rejected before any network call with: "Not a public image
  URL … host the image first and pass its URL."
- A carousel needs 2–10 images; anything else is rejected up front.
- Graph API errors are surfaced verbatim, e.g.
  `Instagram Graph API error (400): Invalid OAuth access token -
  Cannot parse access token` (verified with a fake token).
- Instagram enforces a daily publishing limit per account. A failed
  or uncertain publish may already have published — check with
  `account_status` / the returned permalink before retrying.
- Container `ERROR`/`EXPIRED` or a poll timeout raises a clear error
  naming the container id and last status.

## Verification (done 2026-11-23)

- `python3 -m py_compile server.py bin/client.py` — OK.
- In-process `list_tools`: all 3 tools, schemas confirmed
  (see README for the exact schemas).
- End-to-end over local TLS (`https://127.0.0.1/mcp`, self-signed
  test CA in `tests/tls/`): the template test client ran
  `list-tools` and returned all 3 tools with correct input schemas.
- Error paths verified live: local-path rejection (no network call),
  carousel count validation (1 and 0 images), and a fake token
  reaching graph.facebook.com and returning Meta's real 400
  OAuthException, surfaced verbatim.
- Two real bugs found and fixed during verification (both in
  `server.py`, documented in README): httpx crashing on the VM's
  bracketed-IPv6 `NO_PROXY` entries, and TLS verification failing
  against the egress proxy's CA.

## Untested (needs the real token — nothing published)

- Any call against the real @josehenriquecapibaribe account:
  `account_status`, `publish_photo`, `publish_carousel` end to end.
- The hosted client (`bin/client.py` with the real `ENDPOINT` and
  the registered `custom.instagram-graph` credential).
- Token refresh/rotation for the long-lived token.

## Related skills

- [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md)
- [MCP-backed CLIs](/opt/muse/skills/custom-connector-setup/references/mcp-cli.md)

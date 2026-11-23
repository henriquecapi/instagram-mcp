# Instagram Graph MCP — README

Python + MCP software that connects to the Instagram professional
account **@josehenriquecapibaribe** and publishes the Rotina
Culinária 6-card carousels, using the official Instagram Graph API.
No password is used. Nothing is published by building this.

## What was built

- `server.py` — MCP server (Streamable HTTP) with 3 tools:
  `account_status`, `publish_photo`, `publish_carousel`.
- `bin/client.py` — MCP client (template copy) for the hosted server.
- `CONNECTOR.md` — full setup, tool, and verification documentation.
- `requirements.txt`, `.env.example` — deps and local-run settings.
- `tests/` — TLS test runner + test-only client copy used for the
  local end-to-end verification (self-signed test certs, local only).

Tool input schemas (verified via `list-tools`):

```json
account_status:    {"ig_user_id": "string | null (optional)"}
publish_photo:     {"image_url": "string (required)",
                    "caption": "string | null",
                    "ig_user_id": "string | null"}
publish_carousel:  {"images": ["string", "..."] (required, 2-10),
                    "caption": "string | null",
                    "ig_user_id": "string | null"}
```

## What YOU still have to do (only you can do these)

1. **Confirm the Meta app and the IDs.**
   - In Meta Business Suite, confirm the Facebook Page linked to
     @josehenriquecapibaribe and copy its Page ID.
   - Confirm the Instagram Business Account ID (Business Suite >
     Settings > Instagram accounts). It is the `ig_user_id` the tools
     need. (Also noted in `IG_USER_ID` for local runs.)
   - If there is no Meta app yet: create one at
     developers.facebook.com (type: Business), add the Instagram
     Graph API product to it, and use it to issue the token below.
2. **Get the long-lived access token** (valid ~60 days, refresh
   before it expires) with scopes `instagram_basic`,
   `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`. Do it in Meta's own flow (Graph API
   Explorer or the app dashboard), then exchange the short-lived
   token for a long-lived one.
3. **Grant the token through Muse's secure connection flow** for
   provider `custom.instagram-graph`. Muse will ask you on a secure
   page. **Never paste the token (or any password) in chat, in a
   file, or in code** — the server reads it only from the request's
   `Authorization: Bearer` header or the `IG_ACCESS_TOKEN`
   environment variable.
4. **Host the server** (or run it locally): install the deps
   (`pip install -r requirements.txt`), run `python3 server.py`,
   and put it behind HTTPS on port 443. Then set `ENDPOINT` in
   `bin/client.py` to your real `https://YOUR-SERVER-HOST/mcp`.
5. **Say the word to verify live.** I will then run
   `account_status` (read-only) to confirm the link, and only after
   your approval per post, publish a carousel.

## Two things to know before going live

- **Images must be public URLs.** Instagram fetches each card from
  a public `https://` URL. The 6 PNGs generated for the email are
  local files — before publishing, they have to be hosted somewhere
  public (for example the artifact page's public share) and their
  URLs passed to `publish_carousel`, in order 01 to 06.
- **Facebook Page is link-only.** Nothing is ever posted to the
  Facebook Page; it exists only because the Instagram API requires
  the professional account to be linked to one. Publishing scope is
  Instagram only.

## Bugs found and fixed while verifying (2026-11-23)

- httpx crashed on this VM's `NO_PROXY` list (bracketed IPv6
  entries) — the server now takes the egress proxy explicitly from
  `HTTPS_PROXY` with `trust_env=False`.
- TLS verification failed against the egress proxy's CA — the server
  now verifies against the system CA bundle (`SSL_CERT_FILE` wins
  when set).

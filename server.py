#!/usr/bin/env python3
"""Instagram Graph API MCP server (Streamable HTTP).

Exposes the official Instagram Graph API for a professional
(Business/Creator) Instagram account linked to a Facebook Page:
account_status, publish_photo and publish_carousel.

Authentication
--------------
No credential lives in this file or in any file in this project.
The Graph API access token is resolved, in order, from:

1. The ``Authorization: Bearer <token>`` header of the incoming MCP
   request (this is how Muse's credential flow hands the token to a
   hosted MCP server — the template client sends it as a bearer token).
2. The ``IG_ACCESS_TOKEN`` environment variable (local runs / tests).

The token is never logged and never written to disk.

Images
------
Instagram fetches carousel/photo media from a public HTTPS URL, so
``publish_photo`` and ``publish_carousel`` accept public ``https://``
image URLs only. A local file path is rejected with an actionable
error telling the caller to host the image first (for example via the
project's own public share) and pass the URL.

This server publishes NOTHING on its own: every publish is a tool
call the user (or their agent, with the user's approval) makes.
"""

from __future__ import annotations

import asyncio
import os
import re
import time

import httpx
from mcp.server.mcpserver import Context, MCPServer

GRAPH_BASE = "https://graph.facebook.com/v21.0"
# How long to wait, in seconds, for an Instagram media container to
# become FINISHED before giving up (containers usually finish in seconds).
CONTAINER_TIMEOUT_SECS = 120
CONTAINER_POLL_SECS = 3

mcp = MCPServer("instagram-graph")


# --------------------------------------------------------------------------
# Token + Graph API helpers
# --------------------------------------------------------------------------

def _resolve_token(ctx: Context | None) -> str:
    """Return the Graph API token for this call, or raise a clear error."""
    token = None
    if ctx is not None:
        try:
            headers = ctx.headers or {}
            auth = headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
        except Exception:
            token = None
    if not token:
        token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "No Instagram access token available. Provide it as the "
            "Authorization: Bearer header of the MCP request, or set the "
            "IG_ACCESS_TOKEN environment variable. Never put a token in "
            "chat, in a file, or in code."
        )
    return token


def _resolve_ig_user_id(ctx: Context | None, ig_user_id: str | None) -> str:
    """Return the IG Business Account id, or raise a clear error."""
    if ig_user_id:
        return ig_user_id.strip()
    env_id = os.environ.get("IG_USER_ID", "").strip()
    if env_id:
        return env_id
    raise RuntimeError(
        "No Instagram Business Account id available. Pass ig_user_id, or "
        "set the IG_USER_ID environment variable. Find it in Meta Business "
        "Suite (Settings > Instagram accounts) or via account_status "
        "discovery after linking the Facebook Page."
    )


def _http_client(timeout: float) -> httpx.AsyncClient:
    """httpx client that uses the runtime egress proxy from the environment.

    trust_env=False: the VM's NO_PROXY list contains bracketed IPv6
    entries that httpx cannot parse (it crashes in normalize_port), so
    the proxy is taken explicitly from HTTPS_PROXY instead of the
    environment. No proxy value is ever stored in code or files.

    verify: the egress proxy terminates TLS with its own CA, which is
    in the system bundle but not in certifi's, so verify against the
    system bundle (or SSL_CERT_FILE when set).
    """
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or None
    )
    system_bundle = "/etc/ssl/certs/ca-certificates.crt"
    verify = os.environ.get("SSL_CERT_FILE") or (
        system_bundle if os.path.exists(system_bundle) else True
    )
    return httpx.AsyncClient(
        timeout=timeout, proxy=proxy, trust_env=False, verify=verify
    )


async def _graph(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
) -> dict:
    """One Graph API call. Raises RuntimeError with Instagram's message."""
    body = dict(params or {})
    if method.upper() == "GET":
        resp = await client.request(
            method, f"{GRAPH_BASE}{path}", params={**body, "access_token": token}
        )
    else:
        resp = await client.request(
            method,
            f"{GRAPH_BASE}{path}",
            data={**body, **(data or {}), "access_token": token},
        )
    try:
        payload = resp.json()
    except Exception:
        payload = {}
    if resp.status_code >= 400 or "error" in payload:
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        raise RuntimeError(
            "Instagram Graph API error "
            f"({resp.status_code}): {err.get('message', resp.text[:300])}"
        )
    return payload if isinstance(payload, dict) else {}


async def _wait_container(
    client: httpx.AsyncClient, token: str, creation_id: str
) -> dict:
    """Poll a media container until FINISHED/ERROR, or time out."""
    deadline = time.monotonic() + CONTAINER_TIMEOUT_SECS
    while True:
        info = await _graph(
            client, token, "GET", f"/{creation_id}",
            params={"fields": "id,status_code,status"},
        )
        status = info.get("status_code")
        if status == "FINISHED":
            return info
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(
                f"Instagram media container {creation_id} failed with "
                f"status {status}: {info.get('status', '')}"
            )
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"Timed out waiting for Instagram media container "
                f"{creation_id} (last status: {status})."
            )
        await asyncio.sleep(CONTAINER_POLL_SECS)


def _check_image_url(url: str) -> str:
    """Validate a public https image URL; reject local paths plainly."""
    url = (url or "").strip()
    if not re.match(r"^https://[^/\s]+/\S+$", url):
        raise RuntimeError(
            f"Not a public image URL: {url!r}. Instagram fetches media "
            "from a public https:// URL, so host the image first (for "
            "example via the project's public share) and pass its URL. "
            "Local file paths cannot be published."
        )
    if not re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.IGNORECASE):
        raise RuntimeError(
            f"Image URL does not look like a JPEG/PNG/WebP file: {url!r}."
        )
    return url


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

@mcp.tool()
async def account_status(
    ctx: Context,
    ig_user_id: str | None = None,
) -> dict:
    """Check the linked Instagram professional account.

    Returns the IG user id, username, display name, profile picture URL,
    follower/following counts and media count. With no ig_user_id it uses
    IG_USER_ID, or discovers the first Instagram Business Account linked
    to the Facebook Pages this token can see.
    """
    token = _resolve_token(ctx)
    async with _http_client(30) as client:
        if ig_user_id or os.environ.get("IG_USER_ID"):
            uid = _resolve_ig_user_id(ctx, ig_user_id)
            info = await _graph(
                client, token, "GET", f"/{uid}",
                params={
                    "fields": "id,username,name,profile_picture_url,"
                    "followers_count,follows_count,media_count"
                },
            )
            return {
                "ig_user_id": info.get("id"),
                "username": info.get("username"),
                "name": info.get("name"),
                "profile_picture_url": info.get("profile_picture_url"),
                "followers_count": info.get("followers_count"),
                "follows_count": info.get("follows_count"),
                "media_count": info.get("media_count"),
            }
        # Discovery: Pages -> instagram_business_account.
        pages = await _graph(
            client, token, "GET", "/me/accounts",
            params={"fields": "id,name,instagram_business_account{id,username}"},
        )
        found = []
        for page in pages.get("data", []):
            ig = page.get("instagram_business_account") or {}
            if ig.get("id"):
                found.append(
                    {
                        "page_id": page.get("id"),
                        "page_name": page.get("name"),
                        "ig_user_id": ig.get("id"),
                        "username": ig.get("username"),
                    }
                )
        if not found:
            raise RuntimeError(
                "No Instagram Business Account found on the Pages this "
                "token can see. Link the Instagram professional account "
                "to a Facebook Page in Meta Business Suite first, then "
                "retry (or pass ig_user_id directly)."
            )
        return {"linked_accounts": found}


@mcp.tool()
async def publish_photo(
    ctx: Context,
    image_url: str,
    caption: str | None = None,
    ig_user_id: str | None = None,
) -> dict:
    """Publish one photo to the Instagram feed.

    Creates the image container, waits until it is FINISHED, then
    publishes it. Returns the published media id and permalink.
    """
    token = _resolve_token(ctx)
    uid = _resolve_ig_user_id(ctx, ig_user_id)
    url = _check_image_url(image_url)
    async with _http_client(60) as client:
        container = await _graph(
            client, token, "POST", f"/{uid}/media",
            data={"image_url": url, **({"caption": caption} if caption else {})},
        )
        creation_id = container.get("id")
        if not creation_id:
            raise RuntimeError(f"Instagram did not return a container id: {container}")
        await _wait_container(client, token, creation_id)
        published = await _graph(
            client, token, "POST", f"/{uid}/media_publish",
            data={"creation_id": creation_id},
        )
        media_id = published.get("id")
        info = await _graph(
            client, token, "GET", f"/{media_id}",
            params={"fields": "id,permalink,media_url,caption"},
        )
        return {
            "media_id": media_id,
            "permalink": info.get("permalink"),
            "media_url": info.get("media_url"),
            "caption": info.get("caption"),
        }


@mcp.tool()
async def publish_carousel(
    ctx: Context,
    images: list[str],
    caption: str | None = None,
    ig_user_id: str | None = None,
) -> dict:
    """Publish a carousel (2-10 images) to the Instagram feed.

    For each image, in order: create an item container
    (is_carousel_item=true) and wait until FINISHED. Then create the
    carousel container (media_type=CAROUSEL, children=container ids,
    caption), wait until FINISHED, and publish it. Returns the published
    media id and permalink. All images must share the same aspect ratio
    (the Rotina Culinaria cards are 1080x1350, 4:5).
    """
    token = _resolve_token(ctx)
    uid = _resolve_ig_user_id(ctx, ig_user_id)
    urls = [_check_image_url(u) for u in (images or [])]
    if len(urls) < 2 or len(urls) > 10:
        raise RuntimeError(
            f"A carousel needs 2-10 images; got {len(urls)}. Pass the 6 "
            "card URLs in display order (01 to 06)."
        )
    async with _http_client(60) as client:
        child_ids: list[str] = []
        for url in urls:
            container = await _graph(
                client, token, "POST", f"/{uid}/media",
                data={"image_url": url, "is_carousel_item": "true"},
            )
            creation_id = container.get("id")
            if not creation_id:
                raise RuntimeError(
                    f"Instagram did not return a container id for {url}: {container}"
                )
            await _wait_container(client, token, creation_id)
            child_ids.append(creation_id)
        carousel = await _graph(
            client, token, "POST", f"/{uid}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                **({"caption": caption} if caption else {}),
            },
        )
        carousel_id = carousel.get("id")
        if not carousel_id:
            raise RuntimeError(
                f"Instagram did not return a carousel container id: {carousel}"
            )
        await _wait_container(client, token, carousel_id)
        published = await _graph(
            client, token, "POST", f"/{uid}/media_publish",
            data={"creation_id": carousel_id},
        )
        media_id = published.get("id")
        info = await _graph(
            client, token, "GET", f"/{media_id}",
            params={"fields": "id,permalink,media_url,caption,children{id}"},
        )
        return {
            "media_id": media_id,
            "permalink": info.get("permalink"),
            "media_url": info.get("media_url"),
            "caption": info.get("caption"),
            "children": [c.get("id") for c in info.get("children", {}).get("data", [])],
            "child_container_ids": child_ids,
        }


# --------------------------------------------------------------------------
# Entry point: Streamable HTTP
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Instagram Graph MCP server")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8765")))
    parser.add_argument("--path", default=os.environ.get("MCP_PATH", "/mcp"))
    parser.add_argument(
        "--allowed-hosts",
        default=os.environ.get("MCP_ALLOWED_HOSTS", "127.0.0.1,localhost"),
        help="Comma-separated hosts the server accepts (DNS-rebinding "
        "protection). Set to the server's public hostname when hosted.",
    )
    args = parser.parse_args()
    from mcp.server.transport_security import TransportSecuritySettings

    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[h.strip() for h in args.allowed_hosts.split(",") if h.strip()]
        ),
    )

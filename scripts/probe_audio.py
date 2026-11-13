import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

REF_DIR = os.environ.get("REF_DIR", "refAudio").strip().strip("/") or "refAudio"
ORIGIN = os.environ.get("PROBE_ORIGIN", "https://audio.com").rstrip("/")
QUERY = os.environ.get("PROBE_QUERY", "lofi")
API = "https://api.audio.com"
OUT = Path(REF_DIR) / urlparse(ORIGIN).netloc
OUT.mkdir(parents=True, exist_ok=True)

SKIP_HEADERS = {"authorization", "cookie", "set-cookie"}
MEDIA_RE = re.compile(r"\.(mp3|m4a|aac|ogg|opus|wav|flac|m3u8|mpd|ts|m4s)(\?|$)", re.I)
AUDIO_PAGE_RE = re.compile(r"^/[^/]+/audio/[^/?#]+")

records = []
saved_js = {}


def clean(headers):
    return {k: v for k, v in headers.items() if k.lower() not in SKIP_HEADERS}


def interesting(url, ctype):
    host = urlparse(url).netloc
    if host.endswith("api.audio.com"):
        return True
    if ctype.startswith("audio/") or "mpegurl" in ctype or "dash+xml" in ctype:
        return True
    return bool(MEDIA_RE.search(urlparse(url).path))


async def on_response(resp):
    try:
        url = resp.url
        ctype = resp.headers.get("content-type", "")
        if "/_next/static/" in url and url.endswith(".js") and urlparse(url).netloc.endswith("audio.com"):
            if url not in saved_js:
                body = await resp.body()
                saved_js[url] = body
            return
        if not interesting(url, ctype):
            return
        req = resp.request
        rec = {
            "url": url,
            "method": req.method,
            "status": resp.status,
            "request_headers": clean(req.headers),
            "post_data": req.post_data,
            "response_headers": clean(resp.headers),
            "content_type": ctype,
        }
        if "json" in ctype or "text" in ctype or "mpegurl" in ctype or "xml" in ctype:
            text = await resp.text()
            rec["body"] = text[:40000]
            rec["body_bytes"] = len(text)
        else:
            rec["body"] = None
        records.append(rec)
    except Exception as exc:
        records.append({"url": resp.url, "error": str(exc)})


async def api_probe(ctx, client_id, client_secret):
    results = []

    async def call(method, path, **kw):
        url = path if path.startswith("http") else f"{API}/{path.lstrip('/')}"
        try:
            r = await ctx.request.fetch(url, method=method, timeout=20000, **kw)
            text = await r.text()
            results.append({"method": method, "url": url, "kw": {k: v for k, v in kw.items() if k != "headers"}, "status": r.status, "content_type": r.headers.get("content-type", ""), "body": text[:6000]})
            try:
                return r.status, json.loads(text)
            except Exception:
                return r.status, None
        except Exception as exc:
            results.append({"method": method, "url": url, "error": str(exc)})
            return 0, None

    token = None
    attempts = [
        ("oauth/token", {"form": {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}}),
        ("oauth/token", {"data": json.dumps({"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}), "headers": {"content-type": "application/json"}}),
        ("oauth2/token", {"form": {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}}),
        ("auth/token", {"data": json.dumps({"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}), "headers": {"content-type": "application/json"}}),
    ]
    for path, kw in attempts:
        status, body = await call("POST", path, **kw)
        if isinstance(body, dict):
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            nested = body.get("token") if isinstance(body.get("token"), dict) else {}
            tok = body.get("access_token") or data.get("access_token") or nested.get("accessToken")
            if tok:
                token = tok
                break

    headers = {"authorization": f"Bearer {token}"} if token else {}
    for path in [
        f"search/suggest?q={QUERY}",
        f"search?q={QUERY}",
        f"search/profile?q={QUERY}",
        f"search/audio?q={QUERY}",
        f"search/category/music?q={QUERY}",
        f"search/suggest?query={QUERY}",
        "discover",
        "audio-of-the-day",
        "audios",
    ]:
        await call("GET", path, headers=headers)
    return token, results


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 900},
        )
        page = await ctx.new_page()
        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))

        nav = []

        async def visit(url, wait=5000):
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(wait)
                nav.append({"url": url, "status": resp.status if resp else None, "final": page.url})
            except Exception as exc:
                nav.append({"url": url, "error": str(exc)})

        await visit(ORIGIN)
        links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
        audio_links = []
        for href in links:
            p = urlparse(href or "").path
            if AUDIO_PAGE_RE.match(p) and p not in audio_links:
                audio_links.append(p)

        await visit(f"{ORIGIN}/search?q={QUERY}")
        await visit(f"{ORIGIN}/search/category/music?q={QUERY}")
        links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
        for href in links:
            p = urlparse(href or "").path
            if AUDIO_PAGE_RE.match(p) and p not in audio_links:
                audio_links.append(p)

        try:
            box = page.locator("input[type=search], input[placeholder*=earch i]").first
            await box.fill(QUERY, timeout=8000)
            await page.wait_for_timeout(3000)
        except Exception as exc:
            nav.append({"search_box_error": str(exc)})

        for p in audio_links[:2]:
            await visit(ORIGIN + p, wait=4000)
            for sel in ["button[aria-label*=play i]", "[data-testid*=play i]", "button:has-text('Play')"]:
                try:
                    await page.locator(sel).first.click(timeout=4000)
                    await page.wait_for_timeout(8000)
                    break
                except Exception:
                    continue

        client_id = os.environ.get("AUDIO_CLIENT_ID", "")
        client_secret = os.environ.get("AUDIO_CLIENT_SECRET", "")
        if not client_id:
            for body in saved_js.values():
                m = re.search(rb'NEXT_PUBLIC_CLIENT_ID:"(\d+)",NEXT_PUBLIC_CLIENT_SECRET:"([A-Za-z0-9]+)"', body)
                if m:
                    client_id, client_secret = m.group(1).decode(), m.group(2).decode()
                    break
        token, api_results = await api_probe(ctx, client_id, client_secret)

        for url, body in saved_js.items():
            rel = urlparse(url).path.lstrip("/")
            dest = OUT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)

        endpoints = sorted({
            urlparse(r["url"]).path for r in records
            if "url" in r and urlparse(r["url"]).netloc.endswith("api.audio.com")
        })
        media = sorted({r["url"] for r in records if "url" in r and not urlparse(r["url"]).netloc.endswith("api.audio.com")})

        (OUT / "_net.json").write_text(json.dumps({"nav": nav, "audio_links": audio_links, "records": records, "api_probe": api_results, "got_token": bool(token)}, indent=2))
        (OUT / "_api.json").write_text(json.dumps({
            "api_base": API,
            "client_id": client_id,
            "client_secret": client_secret,
            "token_obtained": bool(token),
            "endpoints": endpoints,
            "media_urls": media[:50],
            "js_files_saved": len(saved_js),
        }, indent=2))
        print("nav", json.dumps(nav))
        print("records", len(records), "endpoints", endpoints)
        print("token", bool(token), "js", len(saved_js))
        await browser.close()


asyncio.run(main())

import os, sys, json, tempfile, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
os.environ["CRAWL_URL"] = "https://soundcloud.com"
c = importlib.import_module("crawl_ref")
def test_extract_api():
    d = tempfile.mkdtemp(); c.ROOT = d
    p = os.path.join(d, "a.js")
    open(p, "w").write('x={client_id:"' + "A1b2" * 8 + '"};fetch("https://api-v2.soundcloud.com/search/tracks");k="/search/users"')
    r = c.extract_api([{"file": "a.js"}])
    assert list(r["client_ids"]) == ["A1b2" * 8]
    assert "https://api-v2.soundcloud.com/search/tracks" in r["api_urls"]
    assert "/search/users" in r["search_paths"]
if __name__ == "__main__": test_extract_api(); print("ok")

def test_ref_dir_env():
    import subprocess
    out = subprocess.run([sys.executable, "-c", "import crawl_ref as c;print(c.REF.rsplit('/',1)[-1])"], cwd=os.path.join(os.path.dirname(__file__), "..", "scripts"), env={**os.environ, "REF_DIR": "refAudio", "CRAWL_URL": "https://audio.com"}, capture_output=True, text=True).stdout.strip()
    assert out == "refAudio", out

def test_http_falls_back_to_cffi_on_403():
    import urllib.error, io
    c.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError("u", 403, "Forbidden", {"server": "cloudflare"}, io.BytesIO(b"")))
    c._cffi = lambda url, method, h, body: (url, "text/html", b"<html>ok</html>")
    assert c.http("https://audio.com")[2] == b"<html>ok</html>"

def test_skips_images():
    assert c.is_image_url("https://audio.com/a/b.PNG?x=1") and c.is_image_url("https://x.com/i.svg")
    assert not c.is_image_url("https://audio.com/app.js") and not c.is_image_url("https://audio.com/page")

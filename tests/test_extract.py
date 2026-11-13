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

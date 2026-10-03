"""xmol.py — search XMOL and harvest the qualifying candidate pool.

XMOL's search backend (`/spaceApi/next/paper/doc/search`) answers 401 to a plain HTTP client
and its search page sits behind an Aliyun captcha, but the *page itself* can call it. So we let
the driven browser fetch it and read rows back over CDP.

    python xmol.py search  "Altermagnetism"     # advanced search in the visible window (real typing)
    python xmol.py harvest "Altermagnetism"     # pull every API page, filter, save candidates
    python xmol.py list                         # show the saved candidate pool

Filtering: impact factor >= threshold, minus excluded journals (PRB / PRM / APL by default).
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa
import driven  # noqa
from cdp import WS  # noqa

CFG = config.load()


def page_ws(needle="x-mol", tries=12):
    for _ in range(tries):
        try:
            tabs = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{CFG['port']}/json/list", timeout=8).read())
            pages = [t for t in tabs if t.get("type") == "page"]
            hit = [t for t in pages if needle in t.get("url", "")] or pages
            if hit:
                return WS(hit[0]["webSocketDebuggerUrl"])
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("no page target on port " + str(CFG["port"]))


def js(ws, expr, timeout=180000):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                timeout=timeout)
    if r.get("exceptionDetails"):
        raise RuntimeError(json.dumps(r["exceptionDetails"])[:300])
    return r["result"].get("value")


HARVEST_JS = r"""
(async (keyword, maxPages) => {
  const out = {pages: [], errors: []};
  for (let page = 1; page <= maxPages; page++) {
    const url = 'https://www.x-mol.com/spaceApi/next/paper/doc/search?option='
      + encodeURIComponent(keyword) + '&pageNo=' + page + '&pageSize=30';
    try {
      const r = await fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}});
      const t = await r.text();
      if (r.status !== 200 || !t.startsWith('{"jsonType')) { out.errors.push(page + ':' + r.status); break; }
      const j = JSON.parse(t);
      const pr = j.obj && j.obj.pageResults;
      if (!pr || !pr.results) { out.errors.push(page + ':no-results'); break; }
      out.pages.push({page, total: pr.totalRecord, rows: pr.results});
      if (page >= (pr.totalPage || 1)) break;
    } catch (e) { out.errors.push(page + ':' + String(e).slice(0, 80)); break; }
    await new Promise(r => setTimeout(r, 400));
  }
  return JSON.stringify(out);
})
"""


def clean(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def search_visible(keyword):
    """Type the keyword into the advanced-search form with real input and submit it."""
    import oswin
    ws = page_ws()
    ws.call("Page.enable")
    ws.call("Runtime.enable")
    js(ws, "location.href='https://www.x-mol.com/paper/search/qadv'")
    time.sleep(7)
    fields = json.loads(js(ws, r"""JSON.stringify(Array.from(document.querySelectorAll('input')).map((el,idx)=>{
      const b=el.getBoundingClientRect();
      return {idx, type:el.type, ph:el.placeholder||'', w:Math.round(b.width),
              x:Math.round(b.left+b.width/2), y:Math.round(b.top+b.height/2), vis:b.width>0&&b.height>0};}).filter(o=>o.vis))""") or "[]")
    kw = next((f for f in fields if f["ph"] == "输入关键词"), None)
    if not kw:
        raise RuntimeError("advanced-search keyword field not found (XMOL layout changed)")
    rect = driven.rect()
    if not rect:
        raise RuntimeError("driven window not found")
    driven.focus()
    oswin.click(rect["left"] + kw["x"], rect["top"] + kw["y"])
    time.sleep(0.6)
    oswin.press("CTRL+A")
    oswin.type_text(keyword, per_char=0.06)
    time.sleep(0.8)
    btn = json.loads(js(ws, r"""JSON.stringify((()=>{
      for (const b of document.querySelectorAll('button,a,div,span')) {
        const t=(b.innerText||'').trim(); const r=b.getBoundingClientRect();
        if ((t==='立即搜索'||t==='搜 索') && r.width>40 && r.height>15 && r.top>=0)
          return {t, x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};} return null;})())""") or "null")
    if btn:
        oswin.click(rect["left"] + btn["x"], rect["top"] + btn["y"])
    else:
        oswin.press("ENTER")
    time.sleep(9)
    return js(ws, "location.href"), (js(ws, "document.body.innerText.slice(0,400)") or "")


def harvest(keyword, max_pages=10):
    ws = page_ws()
    ws.call("Page.enable")
    ws.call("Runtime.enable")
    cur = js(ws, "location.href") or ""
    if "x-mol.com/paper/search" not in cur:
        js(ws, "location.href='https://www.x-mol.com/paper/search/qadv'")
        time.sleep(7)
    data = json.loads(js(ws, f"({HARVEST_JS})({json.dumps(keyword)}, {max_pages})"))
    rows = []
    for p in data["pages"]:
        rows.extend(p["rows"])
    total = data["pages"][0]["total"] if data["pages"] else 0
    unique = {}
    for r in rows:
        unique[r.get("paperId")] = {
            "paperId": r.get("paperId"), "title": clean(r.get("title")),
            "journal": r.get("journalName"), "journalShort": r.get("journalShortName"),
            "if": r.get("impactFactor"), "doi": r.get("doi"), "pubDate": r.get("pubDate"),
            "oaStatus": r.get("oaStatus"), "author": r.get("author"),
            "abstract": clean(r.get("summary"))[:900],
        }
    excl = [e.lower() for e in CFG["excludeJournals"]]
    cands = [v for v in unique.values()
             if (v["if"] or 0) >= CFG["minImpactFactor"]
             and not any(e in (v["journal"] or "").lower() for e in excl)]
    cands.sort(key=lambda x: -(x["if"] or 0))
    payload = {"keyword": keyword, "reportedTotal": total, "rowsFetched": len(rows),
               "apiNote": "XMOL caps the API at 300 rows (10 pages x 30); reportedTotal may be larger",
               "filters": {"minImpactFactor": CFG["minImpactFactor"], "excludeJournals": CFG["excludeJournals"]},
               "all": list(unique.values()), "candidates": cands}
    os.makedirs(CFG["workDir"], exist_ok=True)
    with open(CFG["xmolResults"], "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return payload


def load_results():
    if not os.path.exists(CFG["xmolResults"]):
        return None
    with open(CFG["xmolResults"], encoding="utf-8") as f:
        return json.load(f)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "search":
        kw = sys.argv[2] if len(sys.argv) > 2 else "Altermagnetism"
        url, text = search_visible(kw)
        print("url:", url)
        print(text[:600])
        return 0
    if cmd == "harvest":
        kw = sys.argv[2] if len(sys.argv) > 2 else "Altermagnetism"
        pages = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        p = harvest(kw, pages)
        print(f"reported total: {p['reportedTotal']} | fetched rows: {p['rowsFetched']} "
              f"| unique: {len(p['all'])}")
        print(f"qualifying (IF>={p['filters']['minImpactFactor']}, "
              f"excluding {', '.join(p['filters']['excludeJournals'])}): {len(p['candidates'])}")
        for c in p["candidates"][:40]:
            print(f"  IF={c['if']:<6} {c['journal'][:32]:<32} {c['pubDate']} {c['doi']}")
        print("saved:", CFG["xmolResults"])
        return 0
    # list
    p = load_results()
    if not p:
        print("no saved results yet; run: python xmol.py harvest \"<keyword>\"")
        return 1
    print(f"keyword={p['keyword']} candidates={len(p['candidates'])} rows={p['rowsFetched']}")
    for c in p["candidates"]:
        print(f"  IF={c['if']:<6} {c['journal'][:30]:<30} {c['pubDate']} {c['doi']:<30} {c['title'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

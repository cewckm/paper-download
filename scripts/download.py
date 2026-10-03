"""download.py — fetch the official publisher PDF for every qualifying paper.

Four escalating routes, all legitimate (open access or the user's own subscription):
  1. direct HTTP of a known-good PDF URL      -> fastest, works for OA (Nature Comms, npj, Elsevier OA)
  2. browser session fetch (page's own fetch) -> carries cookies/entitlement, survives bot walls
  3. publisher landing page -> its own PDF link, opened in the browser (native download)
  4. genuine OS mouse click on the page's "Download PDF" control

Everything lands in the download dir and is validated with pypdf. Nothing from arXiv or mirrors.

    python download.py run [--limit N] [--min-if X]
    python download.py status
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa
import driven  # noqa
import oswin  # noqa
import paperlib as pl  # noqa
from cdp import WS  # noqa

CFG = config.load()

APS_CODE = {"physical review letters": "prl", "physical review x": "prx",
            "physical review research": "prresearch", "physical review applied": "prapplied",
            "physical review b": "prb", "physical review materials": "prm"}

# DOI prefix -> landing page builder (suffix = DOI part after the slash)
LANDINGS = {
    "10.1038/": lambda s: f"https://www.nature.com/articles/{s}",
    "10.1103/": None,  # needs journal code, handled separately
    "10.1002/": lambda s: f"https://advanced.onlinelibrary.wiley.com/doi/{s}",
    "10.1021/": lambda s: f"https://pubs.acs.org/doi/{s}",
    "10.1039/": lambda s: f"https://pubs.rsc.org/en/content/articlelanding/2026/cs/{s}",
    "10.1088/": lambda s: f"https://iopscience.iop.org/article/{s}",
    "10.1007/": lambda s: f"https://link.springer.com/article/{s}",
    "10.21468/": lambda s: f"https://scipost.org/{s}",
    "": lambda s: f"https://doi.org/{s}",
}

DIRECT = {
    "10.1038/": lambda s: [f"https://www.nature.com/articles/{s}.pdf"],
    "10.1002/": lambda s: [f"https://advanced.onlinelibrary.wiley.com/doi/pdfdirect/10.1002/{s}?download=true"],
    "10.1021/": lambda s: [f"https://pubs.acs.org/doi/pdf/10.1021/{s}?download=true"],
    "10.1039/": lambda s: [f"https://pubs.rsc.org/en/content/articlepdf/2026/cs/{s}"],
    "10.1088/": lambda s: [f"https://iopscience.iop.org/article/10.1088/{s}/pdf"],
    "10.1007/": lambda s: [f"https://link.springer.com/content/pdf/10.1007/{s}.pdf"],
    "10.21468/": lambda s: [f"https://scipost.org/{s}/pdf"],
}


def safe(s, n=66):
    return re.sub(r"[^\w\-]+", "_", s)[:n].strip("_")


def canonical_name(rec):
    return f"{safe(rec['journal'], 22)}_IF{rec['if']}_{safe(rec['title'])}.pdf"


def page_ws(tries=12):
    for _ in range(tries):
        try:
            tabs = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{CFG['port']}/json/list", timeout=8).read())
            pages = [t for t in tabs if t.get("type") == "page"]
            if pages:
                return WS(pages[0]["webSocketDebuggerUrl"])
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("no page target; run launch.py first")


def js(ws, expr, timeout=90000):
    try:
        r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                    timeout=timeout)
        return r["result"].get("value")
    except Exception:
        return None


def wait_ready(ws, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = js(ws, "document.readyState + '|' + location.href")
        if st and st.startswith("complete"):
            return st.split("|", 1)[1]
        time.sleep(0.8)
    return None


def wait_file(before, timeout=45):
    dest = CFG["downloadDir"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        for f in set(os.listdir(dest)) - before:
            if not f.lower().endswith(".pdf"):
                continue
            p = os.path.join(dest, f)
            if os.path.exists(p + ".crdownload") or os.path.getsize(p) < 60_000:
                continue
            time.sleep(0.5)
            ok, pages, _ = pl.score_pdf(open(p, "rb").read())
            if ok:
                return f, pages
            os.remove(p)
        time.sleep(1.5)
    return None, 0


def rename_to_canonical(rec, fname):
    dest = CFG["downloadDir"]
    canon = canonical_name(rec)
    if fname != canon:
        src, dst = os.path.join(dest, fname), os.path.join(dest, canon)
        if os.path.exists(dst):
            os.remove(dst)
        os.rename(src, dst)
    return canon


def landing_for(rec):
    doi = (rec.get("doi") or "").strip()
    low = doi.lower()
    if low.startswith("10.1103/"):
        code = APS_CODE.get((rec.get("journal") or "").lower())
        return f"https://journals.aps.org/{code}/abstract/{doi}" if code else None
    for pref, fn in LANDINGS.items():
        if pref and low.startswith(pref):
            return fn(doi.split("/", 1)[1])
    return f"https://doi.org/{doi}" if doi else None


def direct_urls(rec):
    doi = (rec.get("doi") or "").strip()
    low = doi.lower()
    if low.startswith("10.1103/"):
        code = APS_CODE.get((rec.get("journal") or "").lower())
        # APS is case sensitive about the DOI tail: use the canonical capitalisation
        tail = doi.split("/", 1)[1]
        tail = re.sub(r"^physrev", "PhysRev", tail, flags=re.I)
        return [f"https://journals.aps.org/{code}/pdf/10.1103/{tail}"] if code else []
    for pref, fn in DIRECT.items():
        if low.startswith(pref):
            return fn(doi.split("/", 1)[1])
    return []


JS_FETCH = r"""
(async (urls) => {
  const out = [];
  for (const u of urls) {
    try {
      const r = await fetch(u, {credentials:'include', redirect:'follow'});
      const buf = await r.arrayBuffer();
      const head = Array.from(new Uint8Array(buf.slice(0,5))).map(c=>String.fromCharCode(c)).join('');
      if (r.status === 200 && head === '%PDF-' && buf.byteLength > 40000) {
        let bin=''; const b=new Uint8Array(buf); const CH=8192;
        for (let i=0;i<b.length;i+=CH) bin += String.fromCharCode.apply(null, b.subarray(i,i+CH));
        return JSON.stringify([{url:u, bytes:buf.byteLength, b64:btoa(bin)}]);
      }
      out.push({url:u, status:r.status, ct:r.headers.get('content-type'), bytes:buf.byteLength});
    } catch(e) { out.push({url:u, err:String(e).slice(0,100)}); }
  }
  return JSON.stringify(out);
})
"""


def route_direct(rec):
    """1) plain HTTP against a known-good URL."""
    for u in direct_urls(rec):
        st, hdrs, data = pl.get(u, timeout=90, maxbytes=60_000_000,
                                accept="application/pdf,*/*;q=0.8")
        ok, pages, note = pl.score_pdf(data)
        if ok:
            path = os.path.join(CFG["downloadDir"], canonical_name(rec))
            with open(path, "wb") as f:
                f.write(data)
            return {"file": os.path.basename(path), "pages": pages, "route": "direct",
                    "url": u, "bytes": len(data)}
    return None


def route_session_fetch(ws, rec, land):
    """2) let the page itself fetch the PDF (cookies + entitlement, small payloads only)."""
    urls = direct_urls(rec)[:2]
    if not urls:
        return None
    cur = js(ws, "location.href") or ""
    if land and cur != land:
        js(ws, f"location.href={json.dumps(land)}")
        wait_ready(ws, 25)
    raw = js(ws, f"({JS_FETCH})({json.dumps(urls)})", timeout=120000)
    try:
        arr = json.loads(raw or "[]")
    except Exception:
        return None
    for item in arr:
        if not item.get("b64"):
            continue
        data = base64.b64decode(item["b64"])
        ok, pages, _ = pl.score_pdf(data)
        if not ok:
            continue
        path = os.path.join(CFG["downloadDir"], canonical_name(rec))
        with open(path, "wb") as f:
            f.write(data)
        return {"file": os.path.basename(path), "pages": pages, "route": "session-fetch",
                "url": item["url"], "bytes": len(data)}
    return None


def route_landing_link(ws, rec, land):
    """3) read the landing page's own PDF link and open it in the browser."""
    if not land:
        return None
    js(ws, f"location.href={json.dumps(land)}")
    wait_ready(ws, 25)
    info = None
    for _ in range(4):
        time.sleep(2)
        raw = js(ws, r"""JSON.stringify((()=>{
          const c=[]; const m=document.querySelector('meta[name="citation_pdf_url"]');
          if(m&&m.content) c.push(m.content);
          for(const a of document.querySelectorAll('a[href]')){
            const h=a.getAttribute('href')||'';
            if(!/\.pdf(\?|$)/i.test(h) && !/article-pdf|pdfdirect|\/pdf\/|articlepdf/i.test(h)) continue;
            const t=(a.innerText||a.getAttribute('aria-label')||a.title||'').replace(/\s+/g,' ').trim();
            if(/supp|support/i.test(t)||/suppl|supporting|_si_/i.test(h)) continue;
            try{ c.push(new URL(h,location.href).href);}catch(e){}
          }
          return {url:location.href, ct:document.contentType, c:[...new Set(c)].slice(0,5)};
        })())""")
        try:
            info = json.loads(raw or "null")
        except Exception:
            info = None
        if info and (info.get("c") or info.get("ct") == "application/pdf"):
            break
    if not info:
        return None
    cands = ([info["url"]] if info.get("ct") == "application/pdf" else []) + list(info.get("c") or [])
    for u in cands[:3]:
        before = set(os.listdir(CFG["downloadDir"]))
        js(ws, f"location.href={json.dumps(u)}")
        time.sleep(2.5)
        fname, pages = wait_file(before, 40)
        if fname:
            canon = rename_to_canonical(rec, fname)
            return {"file": canon, "pages": pages, "route": "landing-link", "url": u}
    return None


def route_click(ws, rec, land):
    """4) click the page's PDF control with a genuine OS mouse click."""
    if not land:
        return None
    js(ws, f"location.href={json.dumps(land)}")
    wait_ready(ws, 30)
    time.sleep(3)
    rect = driven.rect()
    if not rect:
        return None
    driven.focus()
    controls = []
    for _ in range(4):
        raw = js(ws, r"""JSON.stringify((()=>{
          const out=[];
          for (const e of document.querySelectorAll('a,button,[role=button],span,div')){
            const t=(e.innerText||e.getAttribute('aria-label')||e.title||'').replace(/\s+/g,' ').trim();
            const h=e.getAttribute('href')||''; const blob=(t+' '+h).toLowerCase();
            if(!/(download pdf|view pdf|^pdf$|全文|下载|article-pdf|pdfdirect|\.pdf)/.test(blob)) continue;
            if(/supp|support/i.test(t)||/suppl|supporting|_si_/i.test(h)) continue;
            const r=e.getBoundingClientRect();
            if(r.width<8||r.height<8||r.top<0||r.top>innerHeight-6) continue;
            out.push({t:t.slice(0,36), x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2),
                      area:Math.round(r.width*r.height)});
          }
          out.sort((a,b)=>a.area-b.area); return out.slice(0,8);})())""")
        try:
            controls = json.loads(raw or "[]")
        except Exception:
            controls = []
        if controls:
            break
        time.sleep(2.5)
    for c in controls[:4]:
        before = set(os.listdir(CFG["downloadDir"]))
        oswin.click(rect["left"] + c["x"], rect["top"] + c["y"],
                    glide_from=(rect["left"] + max(20, c["x"] - 120), rect["top"] + c["y"] + 60))
        fname, pages = wait_file(before, 40)
        if fname:
            canon = rename_to_canonical(rec, fname)
            return {"file": canon, "pages": pages, "route": "os-click", "url": land}
        js(ws, f"location.href={json.dumps(land)}")
        wait_ready(ws, 25)
        time.sleep(2)
    return None


def run(limit=None, min_if=None, routes=None):
    import xmol
    payload = xmol.load_results()
    if not payload:
        print("no XMOL results; run: python xmol.py harvest \"<keyword>\"")
        return 1
    cands = payload["candidates"]
    if min_if is not None:
        cands = [c for c in cands if (c["if"] or 0) >= min_if]
    os.makedirs(CFG["downloadDir"], exist_ok=True)
    os.makedirs(CFG["workDir"], exist_ok=True)
    status = {}
    if os.path.exists(CFG["statusFile"]):
        try:
            with open(CFG["statusFile"], encoding="utf-8") as f:
                status = {r["paperId"]: r for r in json.load(f)}
        except Exception:
            status = {}

    ws = None
    if routes is None:
        routes = ["direct", "session-fetch", "landing-link", "os-click"]
    need_browser = any(r in routes for r in ("session-fetch", "landing-link", "os-click"))
    if need_browser:
        ws = page_ws()
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        try:
            ws.call("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": CFG["downloadDir"]})
        except Exception:
            pass

    todo = [c for c in cands if not (status.get(c["paperId"], {}) or {}).get("ok")]
    if limit:
        todo = todo[:limit]
    print(f"candidates: {len(cands)} | already ok: {len(cands) - len(todo)} | this run: {len(todo)}")
    added = 0
    for i, rec in enumerate(todo, 1):
        row = dict(rec)
        row.setdefault("file", None)
        row["ok"] = False
        land = landing_for(rec)
        print(f"[{i}/{len(todo)}] IF={rec['if']} {rec['journal'][:24]} | {rec['title'][:50]}", flush=True)
        result = None
        try:
            if "direct" in routes:
                result = route_direct(rec)
            if not result and "session-fetch" in routes and ws:
                result = route_session_fetch(ws, rec, land)
            if not result and "landing-link" in routes and ws:
                result = route_landing_link(ws, rec, land)
            if not result and "os-click" in routes and ws:
                result = route_click(ws, rec, land)
        except Exception as e:
            print("    error:", str(e)[:120], flush=True)
        if result:
            row.update({"ok": True, **result})
            added += 1
            print(f"    saved {result['file']} ({result['pages']}p) via {result['route']}", flush=True)
        else:
            row["why"] = "blocked or unavailable"
            print("    not obtained", flush=True)
        status[rec["paperId"]] = row
        with open(CFG["statusFile"], "w", encoding="utf-8") as f:
            json.dump(list(status.values()), f, ensure_ascii=False, indent=1)
    ok = sum(1 for r in status.values() if r.get("ok"))
    print(f"\n=== this run added {added}; total {ok}/{len(cands)} ===")
    return 0


def status_cmd():
    payload = json.load(open(CFG["xmolResults"], encoding="utf-8")) if os.path.exists(CFG["xmolResults"]) else None
    rows = []
    if os.path.exists(CFG["statusFile"]):
        rows = json.load(open(CFG["statusFile"], encoding="utf-8"))
    total = len(payload["candidates"]) if payload else len(rows)
    ok = [r for r in rows if r.get("ok")]
    print(f"qualifying: {total} | downloaded: {len(ok)} | missing: {max(0, total - len(ok))}")
    from collections import Counter
    missing = Counter(r["journal"] for r in rows if not r.get("ok"))
    if missing:
        print("missing by journal:")
        for j, n in missing.most_common():
            print(f"  {n:>3}  {j}")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "run":
        limit = None
        min_if = None
        args = sys.argv[2:]
        for i, a in enumerate(args):
            if a == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
            if a == "--min-if" and i + 1 < len(args):
                min_if = float(args[i + 1])
        return run(limit=limit, min_if=min_if)
    return status_cmd()


if __name__ == "__main__":
    sys.exit(main())

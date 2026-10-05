"""xmol_adv.py — XMOL advanced search the way the site itself does it (full pagination).

The public /paper/doc/search endpoint is a dead end: it returns only the first 30 rows, ignores
pageNo, and silently drops date/IF conditions. The UI uses a different flow, captured live:

    1. fill the 高级检索 form (keyword + 出版时间 + IF) and submit
       -> the browser POSTs /spaceApi/next/paper/doc/createPaperAdvancedSearch, which STORES the
          criteria server-side and returns a searchLogId
    2. GET /spaceApi/next/paper/doc/searchPaperAdvancedById?searchLogId=..&pageNo=N
       -> that stored query, properly paginated (totalRecord / totalPage are real)

Measured: keyword "Altermagnetism" + 出版时间 2026 + IF 5  =>  196 hits, 7 pages, all retrieved.

    python xmol_adv.py "Altermagnetism" 2026 5 [out.json]
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa
import download as D  # noqa

CFG = config.load()

FILL = r"""
(kw, year, ifMin) => {
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const fire = (el, v) => { if (!el) return false; set.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true}));
    return true; };
  const all = Array.from(document.querySelectorAll('input'));
  const kwEl = document.querySelector('input[name="keywordList[0].option"]');
  fire(kwEl, kw);
  const dates = all.filter(e => Math.round(e.getBoundingClientRect().width) === 99)
                   .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
  fire(dates[0], String(year));                    // 出版时间：起始年
  const nums = all.filter(e => e.type === 'number')
                  .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
  fire(nums[0], String(ifMin));                    // IF：下限
  return JSON.stringify({keyword: kwEl?.value, yearFrom: dates[0]?.value, ifFrom: nums[0]?.value});
}
"""

SUBMIT = r"""
() => {
  const b = Array.from(document.querySelectorAll('button,a,div,span'))
    .find(x => (x.innerText || '').trim() === '立即搜索' && x.getBoundingClientRect().width > 40);
  if (!b) return 'no-button';
  const r = b.getBoundingClientRect();
  for (const t of ['mouseover','mousedown','mouseup','click'])
    b.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window,
      clientX: r.left + r.width / 2, clientY: r.top + r.height / 2}));
  return 'clicked';
}
"""

PAGE = r"""
async (logId, pageNo) => {
  const url = '/spaceApi/next/paper/doc/searchPaperAdvancedById?searchLogId=' + encodeURIComponent(logId)
    + '&pageNo=' + pageNo + '&searchSort=score&readMode=en&onlyOA=false';
  const r = await fetch(url, {credentials:'include', headers:{'Accept':'application/json'}});
  const t = await r.text();
  if (r.status !== 200 || !t.startsWith('{"jsonType')) return JSON.stringify({status:r.status});
  const j = JSON.parse(t);
  const pr = j.obj && j.obj.pageResults;
  return JSON.stringify({total: pr ? pr.totalRecord : null, totalPage: pr ? pr.totalPage : null,
                         rows: (pr && pr.results) || []});
}
"""


def clean(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def harvest(keyword="Altermagnetism", year=2026, if_min=5, max_pages=30):
    ws = D.page_ws()
    ws.call("Page.enable")
    ws.call("Runtime.enable")
    if "x-mol.com/paper/search" not in (D.js(ws, "location.href") or ""):
        D.js(ws, "location.href='https://www.x-mol.com/paper/search/qadv'")
        D.wait_ready(ws, 30)
        time.sleep(6)
    print("填表:", D.js(ws, f"({FILL})({json.dumps(keyword)}, {json.dumps(str(year))}, {json.dumps(str(if_min))})"))
    time.sleep(1)
    print("提交:", D.js(ws, f"({SUBMIT})()"))
    time.sleep(10)
    url = D.js(ws, "location.href") or ""
    m = re.search(r"searchLogId=([0-9a-f\-]+)", url)
    if not m:
        raise RuntimeError("没有拿到 searchLogId（提交未生效？）: " + url)
    log_id = m.group(1)
    shown = D.js(ws, r"""(()=>{const t=document.body.innerText;
        const m=t.match(/共有\s*([\d,]+)\s*个结果/); return m?m[1]:null;})()""")
    print(f"页面显示命中: {shown} | searchLogId={log_id}")

    first = json.loads(D.js(ws, f"({PAGE})({json.dumps(log_id)}, 1)", timeout=120000) or "{}")
    total, pages = first.get("total"), first.get("totalPage") or 1
    rows = list(first.get("rows") or [])
    for p in range(2, min(pages, max_pages) + 1):
        res = json.loads(D.js(ws, f"({PAGE})({json.dumps(log_id)}, {p})", timeout=120000) or "{}")
        got = res.get("rows") or []
        if not got:
            break
        rows.extend(got)
        time.sleep(0.25)
    print(f"接口 total={total} totalPage={pages} → 实际抓取 {len(rows)} 行")

    seen = {}
    for r in rows:
        pid = r.get("paperId")
        if not pid:
            continue
        seen[pid] = {
            "paperId": pid, "title": clean(r.get("title")), "journal": r.get("journalName"),
            "journalShort": r.get("journalShortName"), "if": r.get("impactFactor"),
            "doi": r.get("doi"), "pubDate": r.get("pubDate"), "oaStatus": r.get("oaStatus"),
            "isOa": r.get("isOa"), "author": r.get("author"),
            "abstract": clean(r.get("summary"))[:900], "searchKeyword": keyword,
        }
    out = list(seen.values())
    return {"keyword": keyword, "year": year, "ifMin": float(if_min), "searchLogId": log_id,
            "uiReportedTotal": shown, "apiTotal": total, "rowsFetched": len(rows),
            "candidates": sorted(out, key=lambda x: -(x["if"] or 0))}


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "Altermagnetism"
    year = sys.argv[2] if len(sys.argv) > 2 else "2026"
    if_min = sys.argv[3] if len(sys.argv) > 3 else "5"
    out = sys.argv[4] if len(sys.argv) > 4 else os.path.join(CFG["workDir"], "xmol_adv.json")
    payload = harvest(kw, year, if_min)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    n = len(payload["candidates"])
    print(f"\n候选 {n} 条（{year} 年 · IF≥{if_min}）")
    for c in payload["candidates"][:15]:
        print(f"  IF={c['if']:<6} {c['journal'][:26]:<26} {c['pubDate']} {str(c['doi'])[:30]}")
    print("saved:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

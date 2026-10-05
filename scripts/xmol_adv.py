"""xmol_adv.py — XMOL advanced search done the way the site itself does it (full pagination).

The public /paper/doc/search endpoint is a dead end: it returns only the first 30 rows, ignores
pageNo, and silently drops the date / IF conditions. Two better paths exist; this module tries the
API one first because it needs no form interaction.

PATH A (preferred, no form needed) — POST the criteria, then page the stored query:
    POST /spaceApi/next/paper/doc/createPaperAdvancedSearch
    {"keywordList":[{"operator":"AND","option":"<kw>"}],"authorList":[],"affiliation":null,
     "keywordsRange":2,"hasFollowJournal":false,"journals":[],"followJournalGroupList":[],
     "publishDateStart":null|"YYYY","publishDateEnd":null|"YYYY",
     "impactFactorStart":<int>|null,"impactFactorEnd":<int>|null}
      -> {obj:{id:"<searchLogId>"}}
    GET  /spaceApi/next/paper/doc/searchPaperAdvancedById?searchLogId=..&pageNo=N
      -> that stored query, properly paginated (totalRecord / totalPage are real)

  ⚠ publishDateStart/End want a YEAR STRING ("2025"). An ISO date ("2025-12-31") returns HTTP 400.

PATH B (fallback) — drive the 高级检索 form (keyword box + date box + IF box) and press 立即搜索.

Measured with PATH A: keyword "Altermagnetism" + 出版时间 ≤2025 + IF≥5 => 225 hits, 8 pages, all
retrieved; keyword + 2026 + IF≥5 => 196 hits, 7 pages. The legacy endpoint returned 30.

    python xmol_adv.py "Altermagnetism" 2025 5 [out.json] [--start YEAR] [--title-only]
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

CREATE = r"""
async (payload) => {
  const r = await fetch('/spaceApi/next/paper/doc/createPaperAdvancedSearch', {
    method: 'POST', credentials: 'include',
    headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
    body: JSON.stringify(payload)});
  const t = await r.text();
  let j = null; try { j = JSON.parse(t); } catch (e) {}
  const id = (j && j.obj && (j.obj.id || j.obj.searchLogId)) || null;
  return JSON.stringify({status: r.status, ok: !!(j && j.success), id: id, raw: t.slice(0, 200)});
}
"""

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


def harvest(keyword="Altermagnetism", year=2026, if_min=5, max_pages=30, year_start=None,
            title_only=False, use_form=False):
    """Return the full result set for one advanced query.

    year      : upper bound (出版时间 到) — passed as a YEAR STRING
    year_start: optional lower bound (出版时间 从)
    """
    ws = D.page_ws()
    ws.call("Page.enable")
    ws.call("Runtime.enable")
    if "x-mol.com" not in (D.js(ws, "location.href") or ""):
        D.js(ws, "location.href='https://www.x-mol.com/paper/search/qadv'")
        D.wait_ready(ws, 30)
        time.sleep(6)

    def year_str(v):
        if v is None or v == "":
            return None
        v = str(v).strip()
        m = re.match(r"^(\d{4})", v)
        return m.group(1) if m else None          # ISO dates are rejected with HTTP 400

    payload = {
        "keywordList": [{"operator": "AND", "option": keyword}],
        "authorList": [], "affiliation": None,
        "keywordsRange": 1 if title_only else 2, "hasFollowJournal": False,
        "journals": [], "followJournalGroupList": [],
        "publishDateStart": year_str(year_start), "publishDateEnd": year_str(year),
        "impactFactorStart": int(float(if_min)) if if_min else None, "impactFactorEnd": None,
    }
    log_id = None
    if not use_form:
        print("提交检索条件:", json.dumps(payload, ensure_ascii=False))
        res = json.loads(D.js(ws, f"({CREATE})({json.dumps(payload)})", timeout=120000) or "{}")
        print("create 返回:", res.get("status"), res.get("ok"), "id:", res.get("id"))
        log_id = res.get("id")

    shown = None
    if not log_id:                                  # PATH B: drive the form
        print("改用表单提交（填表 + 立即搜索）…")
        print("填表:", D.js(ws, f"({FILL})({json.dumps(keyword)}, {json.dumps(str(year))}, "
                                f"{json.dumps(str(if_min))})"))
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
    return {"keyword": keyword, "yearTo": year, "yearFrom": year_start, "ifMin": float(if_min),
            "keywordsRange": 1 if title_only else 2, "searchLogId": log_id,
            "uiReportedTotal": shown, "apiTotal": total, "rowsFetched": len(rows),
            "candidates": sorted(out, key=lambda x: -(x["if"] or 0))}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    kw = args[0] if len(args) > 0 else "Altermagnetism"
    year = args[1] if len(args) > 1 else "2026"
    if_min = args[2] if len(args) > 2 else "5"
    out = args[3] if len(args) > 3 else os.path.join(CFG["workDir"], "xmol_adv.json")
    year_start = None
    for f in flags:
        if f.startswith("--start="):
            year_start = f.split("=", 1)[1]
    payload = harvest(kw, year, if_min, year_start=year_start,
                      title_only="--title-only" in flags, use_form="--form" in flags)
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

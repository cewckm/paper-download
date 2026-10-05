"""resolve.py — DOI resolution and open-access pre-flight, with no login and no scraping.

Two free, structured sources fill the two gaps XMOL leaves:

  · Crossref  — XMOL sometimes has no DOI at all (a title is all you get). Crossref turns the
                title into the canonical DOI, and also reveals when XMOL's journal label is
                wrong (a "PRL" row that is really PRB).
  · OpenAlex  — says whether the work is open access and where the free PDF lives, so the
                downloader can skip papers that will certainly fail instead of burning ~40s each.

    python resolve.py fill                    # add DOIs to candidates that lack one
    python resolve.py oa                      # annotate candidates with open-access status
    python resolve.py report                  # summarise what is reachable without a subscription
"""
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa
import paperlib as pl  # noqa

CFG = config.load()
UA = {"User-Agent": "paper-download/1.0 (DSH skill; mailto:research@example.org)"}


def _get_json(url, timeout=45):
    st, _h, body = pl.get(url, headers=UA, timeout=timeout, accept="application/json")
    if st != 200:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


def crossref_by_title(title, rows=3):
    """Best Crossref match for a title (fuzzy-verified so a wrong paper is not attached)."""
    q = urllib.parse.quote(re.sub(r"\s+", " ", title)[:150])
    data = _get_json(f"https://api.crossref.org/works?query.bibliographic={q}&rows={rows}"
                     "&select=DOI,title,container-title,issued,type")
    if not data:
        return None
    import difflib
    best, best_score = None, 0.0
    for it in data.get("message", {}).get("items", []):
        t = (it.get("title") or [""])[0]
        score = difflib.SequenceMatcher(None, pl.norm_title(t), pl.norm_title(title)).ratio()
        if score > best_score:
            best, best_score = dict(it), score
    if best and best_score >= 0.80:
        return {"doi": best.get("DOI"), "title": (best.get("title") or [""])[0],
                "journal": (best.get("container-title") or [""])[0], "score": round(best_score, 3),
                "type": best.get("type")}
    return None


def openalex_by_doi(doi):
    if not doi:
        return None
    data = _get_json(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}")
    if not data:
        return None
    best = data.get("best_oa_location") or {}
    return {
        "is_oa": bool(data.get("open_access", {}).get("is_oa")),
        "oa_status": data.get("open_access", {}).get("oa_status"),
        "oa_url": best.get("pdf_url") or best.get("landing_page_url"),
        "cited_by": data.get("cited_by_count"),
        "title": data.get("title"),
        "journal": ((data.get("primary_location") or {}).get("source") or {}).get("display_name"),
    }


def _load():
    if not os.path.exists(CFG["xmolResults"]):
        print("no XMOL results; run: python xmol.py harvest \"<keyword>\"")
        return None
    with open(CFG["xmolResults"], encoding="utf-8") as f:
        return json.load(f)


def _save(payload):
    with open(CFG["xmolResults"], "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


def cmd_fill():
    payload = _load()
    if not payload:
        return 1
    fixed, dropped = 0, 0
    for c in payload["candidates"]:
        if c.get("doi"):
            continue
        hit = crossref_by_title(c["title"])
        if not hit:
            c["doi_source"] = "unresolved"
            print(f"  ? {c['title'][:60]} —  Crossref 也查不到")
            continue
        c["doi"] = hit["doi"]
        c["doi_source"] = f"crossref(score={hit['score']})"
        c["crossref_journal"] = hit["journal"]
        fixed += 1
        excl = [e.lower() for e in CFG["excludeJournals"]]
        if hit["journal"] and any(e in hit["journal"].lower() for e in excl):
            c["excluded_by_crossref"] = hit["journal"]
            dropped += 1
            print(f"  ! {c['title'][:52]} → 实为 {hit['journal']}，按排除规则剔除")
        else:
            print(f"  + {c['title'][:52]} → {hit['doi']}")
        time.sleep(0.3)
    if dropped:
        payload["candidates"] = [c for c in payload["candidates"] if not c.get("excluded_by_crossref")]
    payload.setdefault("filters", {})["crossrefFilled"] = fixed
    payload["filters"]["crossrefDropped"] = dropped
    _save(payload)
    print(f"\n补齐 DOI: {fixed} 篇 | 因期刊不在允许范围剔除: {dropped} 篇")
    return 0


def cmd_oa():
    payload = _load()
    if not payload:
        return 1
    n_oa = 0
    for c in payload["candidates"]:
        info = openalex_by_doi(c.get("doi"))
        if not info:
            c["oa"] = None
            print(f"  ? {c['title'][:58]} — OpenAlex 无记录")
            continue
        c["oa"] = info
        c["reachable_without_subscription"] = bool(info["is_oa"])
        if info["is_oa"]:
            n_oa += 1
        print(f"  {'OA ' if info['is_oa'] else '-- '} {str(info['oa_status']):<10} "
              f"cited={str(info['cited_by']):<5} {c['title'][:50]}")
        time.sleep(0.2)
    payload.setdefault("filters", {})["openAccessCount"] = n_oa
    _save(payload)
    print(f"\n开放获取（无需订阅即可下载）: {n_oa}/{len(payload['candidates'])} 篇")
    return 0


def cmd_report():
    payload = _load()
    if not payload:
        return 1
    cands = payload["candidates"]
    oa = [c for c in cands if (c.get("oa") or {}).get("is_oa")]
    sub = [c for c in cands if c.get("oa") and not (c.get("oa") or {}).get("is_oa")]
    unknown = [c for c in cands if not c.get("oa")]
    print(f"候选 {len(cands)} 篇：")
    print(f"  开放获取（一定能下）      : {len(oa)}")
    print(f"  非 OA（需机构订阅）       : {len(sub)}")
    print(f"  未查（先跑 resolve.py oa）: {len(unknown)}")
    print("\n非 OA 里 IF 最高的 10 篇（这些要靠订阅或手动）:")
    for c in sorted(sub, key=lambda x: -(x["if"] or 0))[:10]:
        print(f"  IF={c['if']:<6} {c['journal'][:26]:<26} {str(c.get('doi'))[:34]}")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "fill":
        return cmd_fill()
    if cmd == "oa":
        return cmd_oa()
    return cmd_report()


if __name__ == "__main__":
    sys.exit(main())

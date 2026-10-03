"""verify.py — validate every PDF, then write the delivery index and a manual-work list.

    python verify.py            # verify + write README.md index and blocked.md
    python verify.py --check    # verification table only
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa

CFG = config.load()
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def pdf_meta(path):
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        first = " ".join((r.pages[0].extract_text() or "").split())
        m = DOI_RE.search(first)
        doi = m.group(0).lower().rstrip(".,;)") if m else None
        return {"pages": len(r.pages), "doi_on_page1": doi, "head": first[:160]}
    except Exception as e:
        return {"pages": 0, "error": str(e)[:120], "head": ""}


def collect():
    dest = CFG["downloadDir"]
    rows = []
    for root, _dirs, files in os.walk(dest):
        for f in sorted(files):
            if not f.lower().endswith(".pdf"):
                continue
            p = os.path.join(root, f)
            meta = pdf_meta(p)
            rows.append({"file": os.path.relpath(p, dest), "bytes": os.path.getsize(p), **meta})
    return rows


def main():
    check_only = "--check" in sys.argv
    dest = CFG["downloadDir"]
    if not os.path.isdir(dest):
        print("download dir does not exist:", dest)
        return 1

    status = []
    if os.path.exists(CFG["statusFile"]):
        with open(CFG["statusFile"], encoding="utf-8") as f:
            status = json.load(f)

    files = collect()
    print(f"PDFs on disk: {len(files)}")
    bad = [r for r in files if r["pages"] < 2 or r["bytes"] < 60_000]
    for r in files:
        flag = "OK " if r not in bad else "!! "
        print(f"{flag}{r['bytes']//1024:>6}KB p{r['pages']:<4} {r['file'][:88]}")
    if bad:
        print(f"\n{len(bad)} suspicious file(s) — likely a cover page or an error page:")
        for r in bad:
            print("   ", r["file"], r.get("error", ""))

    ok = [r for r in status if r.get("ok")]
    missing = [r for r in status if not r.get("ok")]
    if check_only:
        print(f"\nstatus: {len(ok)} ok / {len(missing)} missing")
        return 0

    # delivery index from the XMOL pool + status
    pool = []
    if os.path.exists(CFG["xmolResults"]):
        with open(CFG["xmolResults"], encoding="utf-8") as f:
            pool = json.load(f).get("candidates", [])
    by_id = {r["paperId"]: r for r in status}
    entries = []
    for c in pool:
        s = by_id.get(c["paperId"], {})
        entries.append({**c, "ok": bool(s.get("ok")), "file": s.get("file"), "route": s.get("route"),
                        "pages": s.get("pages"), "url": s.get("url"), "why": s.get("why")})
    entries.sort(key=lambda e: (-(e["if"] or 0), e["journal"] or ""))

    lines = ["# 文献下载清单", ""]
    kw = "Altermagnetism"
    if os.path.exists(CFG["xmolResults"]):
        try:
            with open(CFG["xmolResults"], encoding="utf-8") as f:
                kw = json.load(f).get("keyword", kw)
        except Exception:
            pass
    lines.append(f"- 来源：XMOL 学术高级检索（关键词 `{kw}`）")
    lines.append(f"- 筛选：IF ≥ {CFG['minImpactFactor']}，排除 {'、'.join(CFG['excludeJournals'])}")
    lines.append("- 版本：出版社正式版 PDF（开放获取或机构订阅），无 arXiv、无第三方镜像")
    lines.append(f"- 已下载 **{sum(1 for e in entries if e['ok'])}/{len(entries)}** 篇\n")
    lines.append("| # | 标题 | 期刊 | IF | 日期 | DOI | 页数 | 文件 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, e in enumerate(entries, 1):
        if not e["ok"]:
            continue
        lines.append(f"| {i} | {e['title']} | {e['journal']} | {e['if']} | {e['pubDate']} | "
                     f"[{e['doi']}](https://doi.org/{e['doi']}) | {e['pages']} | `{e['file']}` |")
    blocked = [e for e in entries if not e["ok"]]
    blocked_lines = [f"## 未获取（{len(blocked)} 篇）— 建议手动下载", ""]
    blocked_lines.append("| 标题 | 期刊 | IF | DOI | 出版社入口 |")
    blocked_lines.append("|---|---|---|---|---|")
    for e in blocked:
        blocked_lines.append(f"| {e['title']} | {e['journal']} | {e['if']} | {e['doi']} | "
                             f"[打开](https://doi.org/{e['doi']}) |")
    lines.append("\n" + "\n".join(blocked_lines))
    with open(os.path.join(dest, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(CFG["workDir"], "missing_manual.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(blocked_lines) + "\n")
    print(f"\nwrote {os.path.join(dest, 'README.md')}")
    print(f"wrote {os.path.join(CFG['workDir'], 'missing_manual.md')} ({len(blocked)} papers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

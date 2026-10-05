"""access_map.py — remember which publishers this machine can actually get PDFs from.

Rationale: probing every paper costs ~40 s, and half of that is spent on publishers that are
structurally unreachable here (Wiley answers 403 to scripted clients; IOP/ScienceDirect serve a
Radware/Cloudflare challenge that never resolves). Recording the verdict once turns those into an
instant "listed, not attempted" instead of a long failed attempt.

    python access_map.py probe     # test one representative paper per publisher
    python access_map.py show      # print the stored verdicts
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa
import paperlib as pl  # noqa

CFG = config.load()
MAP_FILE = os.path.join(CFG["workDir"], "publisher_access.json")

# Prefix -> human label. "direct" = plain HTTP works, "browser" = browser session needed,
# "refused" = publisher rejects this network, "captcha" = bot wall we cannot pass automatically.
PREFIXES = {
    "10.1038": "Nature Portfolio / Springer Nature",
    "10.1103": "APS (journals.aps.org)",
    "10.1002": "Wiley",
    "10.1021": "ACS",
    "10.1039": "RSC",
    "10.1016": "Elsevier / ScienceDirect",
    "10.1088": "IOP Publishing",
    "10.1093": "Oxford University Press",
    "10.1007": "Springer",
    "10.21468": "SciPost",
    "10.1126": "Science (AAAS)",
    "10.1073": "PNAS",
    "10.34133": "AAAS partner journals",
}


def load_map():
    if os.path.exists(MAP_FILE):
        try:
            return json.load(open(MAP_FILE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_map(m):
    os.makedirs(os.path.dirname(MAP_FILE), exist_ok=True)
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def probe_one(doi):
    """Classify a DOI prefix by a single direct HTTP attempt."""
    urls = []
    low = doi.lower()
    if low.startswith("10.1038/"):
        urls = [f"https://www.nature.com/articles/{doi.split('/',1)[1]}.pdf"]
    elif low.startswith("10.1103/"):
        urls = [f"https://journals.aps.org/prl/pdf/{doi}"]
    elif low.startswith("10.1002/"):
        urls = [f"https://advanced.onlinelibrary.wiley.com/doi/pdfdirect/{doi}"]
    elif low.startswith("10.1021/"):
        urls = [f"https://pubs.acs.org/doi/pdf/{doi}"]
    elif low.startswith("10.1039/"):
        urls = [f"https://pubs.rsc.org/en/content/articlepdf/2026/nr/{doi.split('/',1)[1]}"]
    elif low.startswith("10.1016/"):
        urls = [f"https://www.sciencedirect.com/science/article/pii/{doi.split('/',1)[1]}/pdfft"]
    elif low.startswith("10.1088/"):
        urls = [f"https://iopscience.iop.org/article/{doi}/pdf"]
    for u in urls:
        t0 = time.time()
        st, h, d = pl.get(u, timeout=45, maxbytes=3_000_000, accept="application/pdf,*/*")
        ms = int((time.time() - t0) * 1000)
        ok, _pages, _note = pl.score_pdf(d)
        ct = (h or {}).get("Content-Type", "")[:30]
        if ok:
            return {"verdict": "direct", "status": st, "ms": ms, "url": u}
        if st in (403, 429):
            return {"verdict": "refused", "status": st, "ms": ms, "ct": ct, "url": u}
        if isinstance(d, bytes) and any(k in d[:20000].lower() for k in (b"captcha", b"bot manager",
                                                                        b"just a moment", b"radware",
                                                                        b"\xe8\xaf\xb7\xe7\xa8\x8d\xe5\x80\x99")):
            return {"verdict": "captcha", "status": st, "ms": ms, "ct": ct, "url": u}
        return {"verdict": "html", "status": st, "ms": ms, "ct": ct, "url": u}
    return {"verdict": "unknown"}


# Verdicts proven by real downloads on this machine (browser session + institutional access).
# A plain HTTP probe cannot tell whether the *browser* can reach a publisher, so hard evidence
# wins over a probe result:
#   reachable : session-fetch / in-page click actually produced PDFs here
#   refused   : the publisher rejects this network even in the browser (403 / HTML instead of PDF)
#   captcha   : a bot wall (Cloudflare / Radware) that never resolves automatically
SEED = {
    "10.1038": {"verdict": "reachable", "route": "session-fetch",
                "note": "Nature 系：OA 直连可用；订阅刊走浏览器 session-fetch 可拿（实测 Nature/NatMater/NatPhys/NatNano）"},
    "10.1103": {"verdict": "reachable", "route": "landing-link",
                "note": "APS：校内订阅；必须在页面内点 Download PDF，且 DOI 大小写敏感（physrevlett→404）"},
    "10.1021": {"verdict": "reachable", "route": "landing-link",
                "note": "ACS：必须在页面内点下载；PDF 地址含文章 ID，不能靠拼接"},
    "10.1039": {"verdict": "reachable", "route": "landing-link",
                "note": "RSC：实测成功（Chem Soc Rev、Nanoscale）"},
    "10.1093": {"verdict": "reachable", "route": "landing-link",
                "note": "OUP：页面内取 article-pdf 链接（实测 National Science Review 成功）"},
    "10.1007": {"verdict": "reachable", "route": "direct",
                "note": "Springer：content/pdf 直链可用（Science China Physics 实测）"},
    "10.21468": {"verdict": "reachable", "route": "direct",
                "note": "SciPost：<doi>/pdf 直链"},
    "10.1002": {"verdict": "refused",
                "note": "Wiley：脚本与浏览器内均被拒（返回 HTML），需人工点 Download PDF"},
    "10.1016": {"verdict": "captcha",
                "note": "ScienceDirect：反爬挑战自动化过不去"},
    "10.1088": {"verdict": "captcha",
                "note": "IOP：Radware Bot Manager 验证码"},
}


def is_blocked(prefix):
    """True when we know this publisher cannot deliver a PDF here."""
    return load_map().get(prefix, {}).get("verdict") in ("refused", "captcha")


def note_for(prefix):
    info = load_map().get(prefix, {})
    return info.get("note") or info.get("verdict") or ""


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    m = load_map()
    if cmd == "probe":
        targets = {
            "10.1038": "10.1038/s41467-025-58642-4",
            "10.1103": "10.1103/PhysRevLett.134.106802",
            "10.1002": "10.1002/advs.202503235",
            "10.1021": "10.1021/acsnano.5c01421",
            "10.1039": "10.1039/d4nr04053h",
            "10.1016": "10.1016/j.csite.2025.106943",
            "10.1088": "10.1088/1361-6633/ae9e46",
            "10.1007": "10.1007/s11433-026-2913-8",
            "10.21468": "10.21468/scipostphys.18.4.125",
        }
        probe_raw = {}
        for pref, doi in targets.items():
            r = probe_one(doi)
            probe_raw[pref] = r
            print(f"  直连探测 {pref:<9} {r['verdict']:<9} status={r.get('status')} {r.get('ms')}ms", flush=True)
            time.sleep(0.5)
        # hard evidence overrides probing; probing only fills prefixes we have no experience with
        for pref, seed in SEED.items():
            m[pref] = {**seed, "probe": probe_raw.get(pref, {}), "probedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        for pref, r in probe_raw.items():
            m.setdefault(pref, {**r, "label": PREFIXES.get(pref, pref), "probedAt": time.strftime("%Y-%m-%dT%H:%M:%S")})
        save_map(m)
        print("saved:", MAP_FILE)
        return 0
    for pref, info in sorted(m.items(), key=lambda kv: kv[1].get("verdict", "")):
        print(f"  {pref:<9} {info.get('verdict','?'):<10} {info.get('route',''):<13} "
              f"{PREFIXES.get(pref,'')[:24]:<24} {info.get('note','')[:54]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

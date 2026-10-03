"""Reusable helpers: arXiv lookup, OA PDF discovery via Unpaywall/OpenAlex, PDF validation."""
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0")
CTX = ssl.create_default_context()
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def get(url, headers=None, timeout=40, maxbytes=8_000_000, accept=None):
    h = {"User-Agent": UA, "Accept": accept or "*/*", "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, dict(r.headers), r.read(maxbytes)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read(4000)
    except Exception as e:
        return None, {}, f"{type(e).__name__}: {e}".encode()


def norm_title(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def arxiv_search(query, max_results=5, field="ti"):
    url = ("https://export.arxiv.org/api/query?search_query="
           + urllib.parse.quote(f'{field}:"{query}"')
           + f"&start=0&max_results={max_results}")
    st, _, body = get(url)
    if st != 200:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall(ATOM + "entry"):
        doi_el = e.find(ARXIV + "doi")
        pdf = ""
        for link in e.findall(ATOM + "link"):
            if link.get("title") == "pdf":
                pdf = link.get("href")
        out.append({
            "arxiv_id": (e.findtext(ATOM + "id") or "").rsplit("/", 1)[-1],
            "title": " ".join((e.findtext(ATOM + "title") or "").split()),
            "doi": (doi_el.text if doi_el is not None else None),
            "pdf": pdf,
            "published": e.findtext(ATOM + "published"),
            "summary": " ".join((e.findtext(ATOM + "summary") or "").split())[:600],
        })
    return out


def find_arxiv(title, doi=None, thresh=0.93):
    """Return best arXiv match by title similarity (and DOI when available)."""
    nt = norm_title(title)
    cands = []
    if doi:
        cands += arxiv_search(doi, max_results=3, field="all")
    words = nt.split()
    q = " ".join(words[:14])
    cands += arxiv_search(q, max_results=10, field="ti")
    best, best_score = None, 0.0
    for c in cands:
        ct = norm_title(c["title"])
        if not ct:
            continue
        score = difflib_ratio(nt, ct)
        if doi and c.get("doi") and c["doi"].lower() == doi.lower():
            score = 1.0
        if score > best_score:
            best, best_score = c, score
    if best and best_score >= thresh:
        best["score"] = round(best_score, 4)
        return best
    return None


def difflib_ratio(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def openalex_by_doi(doi):
    if not doi:
        return None
    st, _, body = get(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}",
                      accept="application/json")
    if st != 200:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


def unpaywall(doi, email="research@example.com"):
    if not doi:
        return None
    st, _, body = get(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={email}",
                      accept="application/json")
    if st != 200:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


def europepmc_pdf(doi):
    """Europe PMC: find open-access full text PDF for a DOI."""
    q = urllib.parse.quote(f'DOI:"{doi}"')
    st, _, body = get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q}"
                      "&resultType=core&format=json", accept="application/json")
    if st != 200:
        return None
    try:
        j = json.loads(body)
    except Exception:
        return None
    for r in (j.get("resultList", {}).get("result") or []):
        pmcid = r.get("pmcid")
        if pmcid and r.get("isOpenAccess") == "Y":
            return {"pmcid": pmcid, "pdf": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextPDF"}
    return None


def score_pdf(data):
    """Validate PDF bytes; return (ok, pages_estimate, note)."""
    if not data or len(data) < 8000:
        return False, 0, f"too small ({len(data) if data else 0} bytes)"
    if not data[:5].startswith(b"%PDF"):
        return False, 0, "no %PDF magic"
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    if b"%%EOF" not in data[-4096:]:
        # tolerate
        pass
    return True, pages, "ok"


def slugify(s, maxlen=90):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"[^\w\s\-\.]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:maxlen].strip("_")

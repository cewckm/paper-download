# paper-download (DSH skill)

**English** | [中文](README.zh-CN.md)

Search **XMOL** for papers → filter by **impact factor / journal** → download the **publisher's
official PDFs** → emit an index. Comes with the troubleshooting knowledge for paywalls, bot
walls and the classic "I clicked download and nothing happened".

## What it solves

Bulk literature downloading usually dies on two things:

1. **Bot walls** — scripted HTTP to a publisher gets 403/Cloudflare, while a real browser session
   does not;
2. **Downloads that never land** — clicking a PDF just opens the built-in viewer, so no file is
   written.

This skill handles both: it drives a real browser and pre-configures it to *always download PDFs
instead of rendering them*.

## Four download routes

| # | Route | How | Works for |
|---|---|---|---|
| 1 | `direct` | plain HTTP against a known-good PDF URL | open-access journals |
| 2 | `session-fetch` | let the article page `fetch` the PDF itself | cookie/entitlement-gated, small files |
| 3 | `landing-link` | read `meta[citation_pdf_url]` / the page's own PDF link | most publishers |
| 4 | `os-click` | **genuine OS mouse click** on the page's Download PDF control | the fallback |

Everything is the **publisher's official version** (open access or your own institutional
subscription). No arXiv, no third-party mirrors.

## Quick start

```bash
cd scripts

python launch.py                        # start the driven browser window
python xmol.py search "Altermagnetism"  # type the keyword into XMOL for real
python xmol.py harvest "Altermagnetism" # page through the results, filter by IF/journal
python resolve.py fill                  # fill in missing DOIs (Crossref)
python resolve.py oa                    # mark open access + free full-text URLs (OpenAlex)
python download.py run                  # four routes, with PDF validation
python verify.py                        # write README index + manual-work list
```

Useful flags: `download.py run --limit 20`, `--min-if 15`, `--only-oa`, `download.py status`,
`resolve.py report`.

## Why not Google Scholar

Google Scholar is **unreachable on this network** (measured: `scholar.google.com` times out after
21 s, `google.com` connection reset), and Scholar does not host full texts anyway — a click lands
on the same publisher page, so changing the discovery source does not change whether the PDF can
be downloaded. XMOL's irreplaceable advantage is that every result carries an `impactFactor`
field, so the "IF ≥ N" filter is one step.

XMOL's two gaps are covered by two **login-free, bot-wall-free** structured APIs:

| Command | API | Covers |
|---|---|---|
| `resolve.py fill` | Crossref | ~6% of XMOL rows have **no DOI**; Crossref resolves the canonical DOI from the title, and also exposes when XMOL's journal label is wrong (a "PRL" row that is really PRB) |
| `resolve.py oa` | OpenAlex | tells you **which papers are open access and where the free PDF lives**, so the downloader does not waste ~40 s per doomed attempt |

Measured on keyword `Altermagnetism` with 112 candidates: 71 open access, 34 not, 7 unresolved.

## Key lessons (full version in SKILL.md)

- A browser started with the **default profile refuses to open a DevTools port** — use a
  dedicated profile;
- you **must disable the built-in PDF viewer** (`plugins.always_open_pdf_externally` plus
  `Page.setDownloadBehavior`), otherwise clicking a PDF never writes a file;
- **APS DOIs are case sensitive**: `physrevlett` → 404, `PhysRevLett` → 200;
- **XMOL's search API caps at 300 rows** (10 pages × 30) even when the page reports more;
- **bot walls stop scripted HTTP, not the browser** — same machine, same second: script gets 403,
  browser gets 200;
- publishers reject a *bare navigation* to their PDF URL but honour a **click on the Download PDF
  control** — dispatch the click in the page, not by screen coordinates (the window moves).

## Layout

```
scripts/
├── config.py       paths, port, filter rules
├── launch.py       start the driven window (PDF download pre-configured)
├── xmol.py         XMOL search / pagination / filtering
├── resolve.py      Crossref DOI fill + OpenAlex open-access pre-flight
├── download.py     four routes + resumable state
├── verify.py       validation + README index + manual-work list
├── cdp.py          minimal CDP client (stdlib-only WebSocket)
├── oswin.py        OS-level mouse/keyboard (SetCursorPos / mouse_event / SendInput)
├── driven.py       locate the driven window and bring it to the front
└── paperlib.py     PDF validation and helpers
```

## Requirements

- Python 3.10+ (stdlib plus `pypdf` for validation)
- Windows + Edge (or Chrome)
- A machine on a network with the subscription you intend to use (IP-based or logged in)

## Compliance

Only download content that is open access or that your own institution's subscription covers.
No Sci-Hub-style mirrors. Keep the pace slow (≥2 s between papers) and read-only.

## License

MIT

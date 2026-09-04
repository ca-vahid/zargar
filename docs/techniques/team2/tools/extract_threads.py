"""Turn a persisted browser_batch result (Thread Reader pages) into notes/x/*.md files."""
import json, re, sys, pathlib

src = pathlib.Path(sys.argv[1])
out_dir = pathlib.Path(sys.argv[2])
ids = sys.argv[3].split(",")          # thread ids in navigation order
slugs = sys.argv[4].split(",") if len(sys.argv) > 4 else ["auto"] * len(ids)
out_dir.mkdir(parents=True, exist_ok=True)

items = json.load(open(src, encoding="utf-8"))
texts = [i["text"] for i in items if i.get("type") == "text"]
pages = [t for t in texts if t.startswith("[get_page_text]")]
links = [t for t in texts if t.startswith("[javascript_tool:javascript_exec]")]

more = set()
for l in links:
    for m in re.findall(r"/thread/(\d+)\.html", l):
        more.add(m)

MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
written = []
for page, tid, slug in zip(pages, ids, slugs):
    head = re.search(r"@(?:Team2Trading|cs_tradess)\s*\n\s*(\w{3}) (\d{1,2})(?:, (\d{4}))? • (\d+) tweets", page)
    if not head:
        print("no header for", tid); continue
    mon, day, year, n = head.groups()
    import datetime as _dt
    date = _dt.datetime.fromtimestamp(((int(tid) >> 22) + 1288834974657) / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")
    a = page.find("Save as PDF\n")
    b = page.find("\n• • •")
    body = page[a + len("Save as PDF\n"): b].strip() if a >= 0 and b > a else page
    # Thread Reader concatenates tweets without separators; keep as-is but normalise blank runs
    body = re.sub(r"\n{3,}", "\n\n", body)
    fm = (f"---\nsource: https://x.com/Team2Trading/status/{tid}\n"
          f"mirror: https://threadreaderapp.com/thread/{tid}.html\n"
          f"author: Casey (@Team2Trading)\nposted: {date}\nkind: thread ({n} tweets)\n"
          f"captured: 2026-09-03 via in-app browser (Thread Reader unroll), text verbatim; "
          f"tweet boundaries are not marked by the unroll\nimages: chart screenshots per tweet - NOT captured\n---\n\n")
    if slug == "auto":
        words = re.sub(r"[^a-z0-9 ]", " ", body.splitlines()[0].lower()).split()
        slug = "-".join(w for w in words if w not in ("spy","qqq","iwm"))[:60].strip("-") or "thread"
    path = out_dir / f"{date}-{tid}-{slug}.md"
    path.write_text(fm + body + "\n", encoding="utf-8")
    written.append((str(path.name), n, len(body)))
    print(f"\n===== {path.name} ({n} tweets, {len(body)} chars)\n{body}\n")

print("\nWRITTEN:", written)
print("MORE THREAD IDS SEEN:", sorted(more))

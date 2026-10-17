#!/usr/bin/env python3
"""Sync index.html with the Creative Director Roadmap doc.

Usage: python3 sync.py <doc_read_output.json> <index.html>
<doc_read_output.json> is the raw result of the Claude Docs `read` call on the
doc's prose node (contains data.xml). Rewrites TASKS and SETUP in index.html.
Prints CHANGED or UNCHANGED.
"""
import json, re, sys
import xml.etree.ElementTree as ET

src, page = sys.argv[1], sys.argv[2]
raw = json.load(open(src, encoding="utf-8"))
if isinstance(raw, list):  # tool result saved as [{type, text}, ...]
    for block in raw:
        try:
            cand = json.loads(block.get("text", ""))
        except (ValueError, TypeError):
            continue
        if isinstance(cand, dict) and ("data" in cand or "value" in cand):
            raw = cand
            break
    else:
        sys.exit("ERROR: could not find the doc JSON in the saved result")
if "data" in raw:
    xml = raw["data"]["xml"]
elif "value" in raw:
    xml = raw["value"]["data"]["xml"]
else:
    xml = raw["xml"]
root = ET.fromstring(xml)

def text(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()

def items(lst):
    out = []
    for li in lst.findall("listItem"):
        it = {"t": text(li.find("paragraph")), "c": li.get("checked") == "true"}
        sub = li.find("list")
        if sub is not None:
            it["s"] = items(sub)
        out.append(it)
    return out

chapters, cur, label = {}, None, None
for el in root:
    if el.tag == "paragraph" and el.get("heading") == "2":
        m = re.match(r"Chapter (\d+) · (.+)", text(el))
        cur = int(m.group(1)) if m else None
        if cur is not None:
            chapters[cur] = []
        label = None
    elif el.tag == "paragraph" and cur is not None:
        b = el.find("text/bold")
        if b is not None and text(el) == text(b):
            label = text(el)
    elif el.tag == "list" and el.get("kind") == "check" and cur is not None:
        chapters[cur].append({"g": label or "Tasks", "items": items(el)})

# Chapters with weekly checklists: drop the duplicate "Make" summary list
for n, gs in chapters.items():
    if any(g["g"].startswith("Week") for g in gs):
        chapters[n] = [g for g in gs if g["g"] != "Make"]

def clean(t):
    t = re.sub(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d+( · \d{1,2}:\d{2})? · ", "", t)
    t = re.sub(r"^Anytime · ", "", t)
    t = re.sub(r" · \d+(\.\d+)?(–\d+)? (hrs?|min)$", "", t)
    t = re.sub(r" \(\d+ min\)$", "", t)
    t = re.sub(r'^(.+?), "(.+?)"$', r"\2 — \1", t)
    t = re.sub(r"^الدحيح: (.+)$", r"\1 — الدحيح", t)
    t = re.sub(r"\. Find one via .*$", "", t)
    # durations: " · 31 min + quiz" → " + quiz", "(9 min)", "(1h 35m)", " · ~20 min", " · 4 hrs (no post this week)"
    t = re.sub(r" · ~?\d+(\.\d+)?(–\d+)? (hrs?|min)( \(no post this week\))?(?= \+ quiz|$| ·|:)", "", t)
    t = re.sub(r" \((~?\d+h ?)?~?\d+(\.\d+)?(–\d+)? ?(min|m|hrs?)\)", "", t)
    t = re.sub(r" \(no post this week\)", "", t)
    t = re.sub(r" · lecture ~?\d+ hrs?", "", t)
    t = re.sub(r" · ~?\d+h( \d+m)?(?=:| ·|$)", "", t)          # " · 1h 52m"
    t = re.sub(r" · ~?\d+(\.\d+)? hrs?(?= \()", "", t)          # " · 2 hrs (note)"
    # simplify: "session 3 of 11" → "session 3", drop "Lesson 4: " prefixes
    t = re.sub(r"\b([Ss]ession \d+) of \d+\b", r"\1", t)
    t = re.sub(r"(^|· )Lesson \d+: ", r"\1", t)
    t = re.sub(r"^Quiz: Lesson \d+$", "Quiz", t)                 # "Quiz: Lesson 2" → "Quiz"
    t = re.sub(r"\s*·?\s*brief:\s*$", "", t)                      # trailing "· brief:" link label
    t = re.sub(r"^HubSpot Content Marketing, (session \d+)", r"HubSpot \1", t)
    return re.sub(r"\s{2,}", " ", t).strip()

def walk(its):
    for i in its:
        i["t"] = clean(i["t"])
        if i.get("s"):
            walk(i["s"])

def leaves(its):
    n = d = 0
    for i in its:
        if i.get("s"):
            a, b = leaves(i["s"]); n += a; d += b
        else:
            n += 1; d += i["c"]
    return n, d

setup = chapters.pop(0, [])
s_total = s_done = 0
for g in setup:
    a, b = leaves(g["items"]); s_total += a; s_done += b

tasks = {}
for n in sorted(chapters):
    for g in chapters[n]:
        walk(g["items"])
    tasks[str(n)] = chapters[n]

if len(tasks) != 8:
    sys.exit(f"ERROR: expected 8 chapters, found {len(tasks)} — doc structure changed, not updating")

h = open(page, encoding="utf-8").read()
new = re.sub(r"const TASKS = \{.*?\};\n",
             lambda m: "const TASKS = " + json.dumps(tasks, ensure_ascii=False, separators=(",", ":")) + ";\n",
             h, count=1, flags=re.S)
new = re.sub(r"const SETUP = \{[^}]*\};",
             f"const SETUP = {{ done: {s_done}, total: {s_total} }};", new, count=1)
if new == h:
    print("UNCHANGED")
else:
    open(page, "w", encoding="utf-8").write(new)
    total = sum(leaves(g["items"])[0] for gs in tasks.values() for g in gs)
    done = sum(leaves(g["items"])[1] for gs in tasks.values() for g in gs)
    print(f"CHANGED setup {s_done}/{s_total} phases {done}/{total}")

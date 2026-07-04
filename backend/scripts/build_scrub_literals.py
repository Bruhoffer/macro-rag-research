"""
Build scrub_literals.txt — the list of known internal sender/recipient names
scrubbed from free text by scripts/scrub_pii.py.

Header-stripping and address redaction can't catch *names in prose* (signatures,
"FW:" subjects, company boilerplate). This extracts, from the source CSV's
email_from/email_to fields:
  - every display name ("Jane Doe <jane@x.com>" -> "Jane Doe"), plus its
    individual word parts (first/last names), so signatures match too
  - the second-level label of every internal domain (e.g. "fund" from fund.com),
    catching the company name in disclaimers/footers

Line format: person names/parts are plain lines (matched on word boundaries);
domain labels are prefixed with "~" (matched as substrings, so they're caught
inside URL-encoded addresses like %40fund.com and logo filenames).

The output file is gitignored — it is itself PII (an index of everything being
hidden). Names are never printed; only counts.

Run from backend/:
    python scripts/build_scrub_literals.py
"""

import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

RAW_DATA = Path(os.environ["RAW_DATA_DIR"])
OUT_PATH = Path(__file__).parent.parent / "scrub_literals.txt"

DISPLAY_NAME_RE = re.compile(r"([A-Za-z][A-Za-z .'\-]{1,40})\s*<([^>]+)>")
MIN_LEN = 4  # skip fragments too short to be safe word-boundary targets

# Generic words that appear in display names but must never be scrubbed —
# e.g. the "Macro AI" ingestion mailbox would otherwise put "Macro" in the
# list and redact it across a macro research corpus.
EXCLUDE_PARTS = {"macro"}


def main():
    df = pd.read_csv(RAW_DATA / "emails_parsed.csv", usecols=["email_from", "email_to"])
    vals = pd.concat([df["email_from"], df["email_to"]]).dropna().unique()

    literals: set[str] = set()
    for v in vals:
        for m in DISPLAY_NAME_RE.finditer(str(v)):
            name, addr = m.group(1).strip().strip(","), m.group(2)
            literals.add(name)
            literals.update(part for part in re.split(r"[ .]+", name))
            # company name from the domain's second-level label — substring
            # match ("~") so URL-encoded addresses and filenames are caught
            domain = addr.rsplit("@", 1)[-1].lower()
            labels = domain.split(".")
            if len(labels) >= 2:
                literals.add("~" + labels[-2])

    literals = {
        lit for lit in literals
        if len(lit.lstrip("~")) >= MIN_LEN and lit.lstrip("~").lower() not in EXCLUDE_PARTS
    }
    OUT_PATH.write_text("\n".join(sorted(literals, key=str.lower)) + "\n")
    print(f"{len(vals)} distinct from/to values -> {len(literals)} literals -> {OUT_PATH.name}")
    print("Review the file before running scrub_pii.py — remove any false positives")
    print("(common words that happen to be name parts).")


if __name__ == "__main__":
    main()

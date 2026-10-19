"""
Your Company Lead Finder — CLI version
====================================
Free B2B lead-gen pipeline:
  1. Discover businesses via Google Maps
  2. Visit each business website, extract an email + social media links
  3. Keep only leads with at least ONE contact method (email, website, or a
     social link) — others are skipped automatically
  4. Export to Excel + CSV — EACH city+category combo gets its OWN file, so
     different searches never get mixed together

RUN THIS ON YOUR OWN MACHINE (Windows/Mac/Linux) — needs real internet
access to google.com and business websites.

------------------------------------------------------------------
SETUP (one-time)
------------------------------------------------------------------
pip install playwright beautifulsoup4 requests openpyxl pandas
playwright install chromium

------------------------------------------------------------------
USAGE
------------------------------------------------------------------
1. Edit the CONFIG section below (search queries, city, category, how many leads).
2. Run:  python lead_finder.py
3. Output files: leads_<city>_<category>.xlsx and .csv (one pair per search)

TIP: Prefer a browser-based dashboard? Run  python app.py  and open
http://localhost:5000 in your browser.
"""

import pandas as pd
from scraper_core import find_qualifying_leads, output_basename

# ==================================================================
# CONFIG — EDIT THIS SECTION
# ==================================================================
SEARCHES = [
    # (search term as typed into Google Maps, city label, category label)
    ("dental clinics in Toronto", "Toronto", "Dental Clinic"),
    # add more rows here, e.g.:
    # ("ecommerce stores in Texas", "Texas", "E commerce store"),
]

TARGET_LEADS_PER_SEARCH = 100     # how many QUALIFYING new leads to collect per search
COLUMNS = ["business_name", "email", "city", "website",
           "category", "facebook", "instagram", "linkedin", "whatsapp"]


def run_one_search(query, city, category, target_count):
    base = output_basename(city, category)
    xlsx_file = f"{base}.xlsx"
    csv_file = f"{base}.csv"

    # Load this SPECIFIC city+category's previous output (if any) so re-running
    # it fetches new leads instead of repeating — but different searches don't mix.
    try:
        existing_df = pd.read_excel(xlsx_file)
        already_have = set(existing_df["business_name"].dropna())
        print(f"Found existing {xlsx_file} with {len(already_have)} leads — will skip these.")
    except FileNotFoundError:
        existing_df = None
        already_have = set()

    print(f"\n=== Searching Google Maps: {query} (target: {target_count} qualifying leads) ===")
    rows = find_qualifying_leads(query, city, category, target_count,
                                  skip_names=already_have, log=print)

    new_df = pd.DataFrame(rows, columns=COLUMNS)
    df = pd.concat([existing_df, new_df], ignore_index=True) if existing_df is not None else new_df
    df.drop_duplicates(subset=["business_name", "website"], inplace=True)

    df.to_excel(xlsx_file, index=False)
    df.to_csv(csv_file, index=False)

    print(f"\n✅ Done. {len(df)} total leads saved to {xlsx_file} and {csv_file}")
    print(f"   This batch: {len(rows)} new qualifying leads added")
    print(f"   Total with email: {(df['email'] != '').sum()}")


def main():
    for query, city, category in SEARCHES:
        run_one_search(query, city, category, TARGET_LEADS_PER_SEARCH)


if __name__ == "__main__":
    main()

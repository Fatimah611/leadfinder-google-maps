"""
Your Company Lead Finder — Web Dashboard
=====================================
Browser-based version of the lead finder. Enter search + city + category,
click Start, watch live progress, then download that search's Excel/CSV.
Each city+category combo gets its OWN file — different searches never mix.

SETUP (one-time):
    pip install flask playwright beautifulsoup4 requests openpyxl pandas
    playwright install chromium

RUN:
    python app.py
Then open http://localhost:5000 in your browser.
"""

import os
import glob
import threading
import pandas as pd
from flask import Flask, request, jsonify, send_file, render_template

from scraper_core import find_qualifying_leads, output_basename

app = Flask(__name__)

COLUMNS = ["business_name", "email", "city", "website",
           "category", "facebook", "instagram", "linkedin", "whatsapp"]

# In-memory job state (single-user local tool, so a simple global is fine)
job_state = {
    "running": False,
    "log": [],
    "progress": 0,
    "total": 0,
    "done": False,
    "error": None,
    "current_base": None,   # filename base of the search currently shown in Results
}
job_lock = threading.Lock()


def add_log(message):
    with job_lock:
        job_state["log"].append(message)
        if len(job_state["log"]) > 300:
            job_state["log"] = job_state["log"][-300:]


def run_job(query, city, category, target_count):
    base = output_basename(city, category)
    xlsx_file = f"{base}.xlsx"
    csv_file = f"{base}.csv"

    try:
        with job_lock:
            job_state["running"] = True
            job_state["done"] = False
            job_state["error"] = None
            job_state["log"] = []
            job_state["progress"] = 0
            job_state["total"] = target_count
            job_state["current_base"] = base

        try:
            existing_df = pd.read_excel(xlsx_file)
            already_have = set(existing_df["business_name"].dropna())
            add_log(f"Found existing {xlsx_file} with {len(already_have)} leads — will skip these.")
        except FileNotFoundError:
            existing_df = None
            already_have = set()

        add_log(f"Searching Google Maps: {query} (target: {target_count} qualifying leads)")

        def log_and_progress(msg):
            add_log(msg)
            # crude progress parse from "[n/target]" prefix
            if msg.startswith("["):
                try:
                    n = int(msg[1:].split("/")[0])
                    with job_lock:
                        job_state["progress"] = n
                except Exception:
                    pass

        rows = find_qualifying_leads(query, city, category, target_count,
                                      skip_names=already_have, log=log_and_progress)

        new_df = pd.DataFrame(rows, columns=COLUMNS)
        df = pd.concat([existing_df, new_df], ignore_index=True) if existing_df is not None else new_df
        df.drop_duplicates(subset=["business_name", "website"], inplace=True)

        df.to_excel(xlsx_file, index=False)
        df.to_csv(csv_file, index=False)

        emails_found = int((df['email'] != '').sum())
        add_log(f"✅ Done. {len(rows)} new qualifying leads added. {len(df)} total saved to {xlsx_file}")
        add_log(f"   Total with email: {emails_found}")

    except Exception as e:
        add_log(f"❌ Error: {e}")
        with job_lock:
            job_state["error"] = str(e)
    finally:
        with job_lock:
            job_state["running"] = False
            job_state["done"] = True


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    with job_lock:
        if job_state["running"]:
            return jsonify({"ok": False, "message": "A search is already running."}), 400

    data = request.json
    query = data.get("query", "").strip()
    city = data.get("city", "").strip()
    category = data.get("category", "").strip() or "Business"
    target_count = int(data.get("max_results", 50))

    if not query or not city:
        return jsonify({"ok": False, "message": "Search query and city are required."}), 400

    thread = threading.Thread(target=run_job, args=(query, city, category, target_count), daemon=True)
    thread.start()
    return jsonify({"ok": True})


@app.route("/status")
def status():
    with job_lock:
        return jsonify(dict(job_state))


@app.route("/results")
def results():
    with job_lock:
        base = job_state.get("current_base")

    xlsx_file = f"{base}.xlsx" if base else None
    if not xlsx_file or not os.path.exists(xlsx_file):
        return jsonify({"rows": [], "count": 0, "file_base": base})

    df = pd.read_excel(xlsx_file)
    df = df.fillna("")
    preview = df.tail(200).to_dict(orient="records")
    return jsonify({"rows": preview, "count": len(df), "file_base": base})


@app.route("/files")
def list_files():
    """List every lead file created so far, so past searches stay downloadable."""
    files = sorted(glob.glob("leads_*.xlsx"))
    file_info = []
    for f in files:
        base = f[:-5]  # strip .xlsx
        try:
            df = pd.read_excel(f)
            count = len(df)
        except Exception:
            count = "?"
        file_info.append({"base": base, "count": count})
    return jsonify({"files": file_info})


@app.route("/download/<base>/<filetype>")
def download(base, filetype):
    # basic safety: only allow files matching our naming pattern
    if not base.startswith("leads_") or filetype not in ("xlsx", "csv"):
        return "Invalid request.", 400
    path = f"{base}.{filetype}"
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "File not found.", 404


if __name__ == "__main__":
    app.run(debug=False, port=5000)

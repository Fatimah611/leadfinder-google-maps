# LeadFinder (Google Maps)

A browser-automation tool that extracts structured business data from Google Maps at scale and exports it to CSV and Excel. It includes a small web interface for running searches.

## Features

- Extracts business name, email, website, city and category
- Reliable website link capture (waits for stable links before reading them)
- Social profile link extraction using rendered pages
- Web UI built with Flask
- Exports results to CSV and XLSX

## Tech stack

Python, Playwright, Flask

## Setup

1. Install dependencies (see `requirements.txt`) and the Playwright browser:

        pip install -r requirements.txt
        playwright install chromium

2. Start the web interface and open the local address shown in the terminal:

        python app.py

## Notes

- Generated lead files are gitignored and are never part of this repository.
- Use responsibly: respect Google's terms of service, website terms and local data-protection laws.
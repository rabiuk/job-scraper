# Job Scraper for SWE New Grad/Intern Roles

## Overview

A Python-based job hunting tool designed to help Software Engineer (SWE) new grads and interns apply first by scraping job postings from multiple sources and sending notifications. The project consists of two independent scripts:

- **Board Scraper**: Scrapes job boards like LinkedIn, GitHub (SimplifyJobs/New-Grad-Positions), and Simplify.jobs, sending new jobs to Discord every 2 hours.
- **Company Scraper**: Monitors company career pages for new junior-friendly SWE jobs, emailing you instantly when found.

Both scripts run concurrently, targeting jobs in Canada, the US, and remote roles, with a focus on speed and avoiding duplicates.

## Features

### Board Scraper

- Scrapes LinkedIn (Canada/US), GitHub (SimplifyJobs/New-Grad-Positions), and Simplify.jobs (Canada/US/Remote).
- Tracks seen jobs to avoid duplicates (`board_scraper/seen_jobs.json`).
- Sends new job postings to a Discord channel via webhook every 2 hours.
- Runs continuously with a 2-hour polling interval.

### Company Scraper

- Monitors career pages of 10+ tech companies (e.g., Google, Amazon, Shopify) for new grad/entry-level SWE jobs.
- Tracks seen jobs (`company_scraper/seen_jobs.json`).
- Emails you instantly with job details: title, company, location, link, and timestamp.
- Polls every 30 seconds for near-real-time alerts.

## Directory Structure

```

JOB-SCRAPER/
├── board_scraper/ # Job board scraper (LinkedIn, GitHub, Simplify)
│ ├── scraper.py
│ ├── linkedin_cookies.pkl
│ ├── scraper.log.txt
│ ├── debug/
│
├── company_scraper/ # Company career page scraper
│ ├── company_script.py
│ ├── companies.csv
│ ├── seen_jobs.json
│
├── .gitignore
├── README.md
├── requirements.txt
├── .env
├── env/
└── test_discord.py

```

## Setup

1. **Clone the Repository** (or create locally):

   ```bash
   git clone <repo-url>  # Replace with your GitHub repo URL
   cd JOB-SCRAPER
   ```

Or copy the project to `C:\Users\Kenny\Documents\Projects\JOB-SCRAPER\`.

2. **Set Up Virtual Environment:**

   ```bash
   python -m venv env
   # Windows
   env\Scripts\activate
   # Mac/Linux
   source env/bin/activate
   ```

3. **Install Dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

   Current dependencies:

   - `requests`
   - `beautifulsoup4`
   - `discord-webhook`
   - `python-dotenv`
   - `selenium`
   - `webdriver-manager`
   - `pandas` (for company scraper)

4. **Configure `.env`:**

   - Create `.env` in the project root (`C:\Users\Kenny\Documents\Projects\JOB-SCRAPER\.env`).
   - Add credentials for both scripts:

     ```env
     # Board Scraper (Discord)
     DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<WEBHOOK_ID>/<WEBHOOK_TOKEN>

     # Company Scraper (Email)
     EMAIL_ADDRESS=your.email@gmail.com
     EMAIL_APP_PASSWORD=your-app-password
     ```

   - **Discord Webhook**: In Discord → Channel Settings → Integrations → Webhooks → New Webhook → Copy URL.
   - **Email Setup**: Use Gmail (or another SMTP service). Generate an app password at `myaccount.google.com/security` → 2-Step Verification → App Passwords.

5. **Run the Scrapers:**

   - **Board Scraper**:

     ```bash
     python board_scraper/scraper.py
     ```

     - Logs to `board_scraper/scraper.log.txt`.
     - Posts new jobs to Discord every 2 hours.

   - **Company Scraper**:
     ```bash
     python company_scraper/company_script.py
     ```
     - Emails new jobs instantly.
     - Polls every 30 seconds.

   Run both in separate terminals to operate concurrently.

## Usage

- **Board Scraper**:

  - First run: Scrapes all jobs, posts new ones to Discord, saves seen jobs.
  - Subsequent runs: Checks every 2 hours, posts only new jobs.
  - Stop: Ctrl+C to exit, restarts from `board_scraper/seen_jobs.json`.

- **Company Scraper**:

  - First run: Checks all career pages in `company_scraper/companies.csv`, emails new jobs, saves seen jobs.
  - Subsequent runs: Polls every 30 seconds, emails only new jobs.
  - Stop: Ctrl+C to exit, restarts from `company_scraper/seen_jobs.json`.

- **Adding Companies**:
  - Edit `company_scraper/companies.csv` to add more career pages (e.g., `Adobe,adobe.com/careers,US`).

## Notes

- **Sources**:
  - Board Scraper: LinkedIn, GitHub (SimplifyJobs/New-Grad-Positions), Simplify.jobs.
  - Company Scraper: Custom list in `company_scraper/companies.csv` (starts with Google, Amazon, Shopify, etc.).
- **Delays**:
  - Board Scraper: 2s between Discord sends to avoid rate limits.
  - Company Scraper: 30s polling (adjustable) to balance speed and site limits.
- **Locations**: Some Simplify jobs show “Unknown Location”—can be refined.
- **Troubleshooting**:
  - Check `board_scraper/scraper.log.txt` for Board Scraper errors.
  - Add logging to `company_script.py` for debugging (coming soon).

## Future Enhancements

- Add more job board sources (e.g., Indeed, Glassdoor).
- Optimize Simplify scraping speed (avoid clicking).
- Add filtering for specific keywords (e.g., “remote”, “Python”).
- Unify notification styles (e.g., email for both scripts, or Discord for company scraper).

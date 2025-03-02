# Job Scraper for SWE New Grad/Intern Roles

## Overview

A Python tool to scrape Software Engineer (SWE) new grad and internship job postings from LinkedIn, GitHub (SimplifyJobs/New-Grad-Positions), and Simplify.jobs. Designed to help you apply first by tracking new jobs and sending notifications to Discord every 2 hours.

## Features

- Scrapes LinkedIn (Canada/US), GitHub, and Simplify (Canada/US/Remote).
- Tracks seen jobs to avoid duplicates (`data/seen_jobs.json`).
- Sends new job postings to a Discord channel via webhook.
- Runs continuously with a 2-hour interval.

## Setup

1. **Clone the Repository** (or create locally):

   ```bash
   git clone <repo-url>  # If hosted on GitHub
   cd job-scraper
   ```

   Or copy the script to `C:\Users\Kenny\Documents\Projects\job-scraper\src\scraper.py`.

2. **Set Up Virtual Environment:**

   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Mac/Linux
   source venv/bin/activate
   ```

3. **Install Dependencies:**

   ```bash
   pip install requests beautifulsoup4 discord-webhook python-dotenv selenium webdriver-manager
   ```

4. **Configure `.env`:**

   - Create `.env` in the project root (`C:\Users\Kenny\Documents\Projects\job-scraper\.env`).
   - Add your Discord webhook URL:
     ```env
     DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<WEBHOOK_ID>/<WEBHOOK_TOKEN>
     ```
   - Get the URL: Discord → Channel Settings → Integrations → Webhooks → New Webhook → Copy URL.

5. **Run the Scraper:**
   ```bash
   python src/scraper.py
   ```
   - Logs to `scraper.log`.
   - Posts new jobs to Discord every 2 hours.

## Usage

- **First Run:** Scrapes all jobs, posts new ones to Discord, and saves seen jobs.
- **Subsequent Runs:** Checks every 2 hours, posts only new jobs.
- **Stop:** Ctrl+C to exit, restarts from `seen_jobs.json`.

## Notes

- **Sources:** LinkedIn, GitHub, Simplify.
- **Delay:** 2s between Discord sends to avoid rate limits.
- **Locations:** Some Simplify jobs show “Unknown Location”—can be refined.
- **Troubleshooting:** Check `scraper.log` for errors (e.g., “No details-view found”).

## Future Enhancements

- Add more job sources (e.g., Indeed).
- Optimize Simplify scraping speed (avoid clicking).

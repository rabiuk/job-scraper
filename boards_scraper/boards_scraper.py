import os
import time
import json
import logging
import asyncio
import requests
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from requests_ratelimiter import LimiterSession
from utils import send_discord_message, load_board_urls, load_seen_jobs, save_seen_jobs
from setup_environment import setup_environment
from config import EST
from boards_scraper.linkedin_utils import get_session, check_cookies_valid, login_to_linkedin, setup_selenium_driver, fetch_linkedin_jobs, COOKIE_FILE

setup_environment()
logger = logging.getLogger(__name__)

session = LimiterSession(per_second=1)
BOARD_URLS_FILE = "boards_scraper/board_urls.json"
SEEN_JOBS_FILE = "boards_scraper/seen_jobs.json"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def get_current_est_time():
    """Get current time in EST as formatted string."""
    return datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S")

def convert_to_est(utc_timestamp):
    """Convert UTC timestamp to EST."""
    if utc_timestamp == "N/A":
        return "N/A"
    utc_time = datetime.utcfromtimestamp(utc_timestamp).replace(tzinfo=timezone.utc)
    return utc_time.astimezone(EST).strftime("%Y-%m-%d %H:%M:%S")

def scrape_simplify(board, base_url):
    """Scrape jobs from Simplify with dynamic country filtering, minimal logging."""
    jobs = []
    api_url = "https://xv95tgzrem61cja4p.a1.typesense.net/multi_search"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "text/plain",
        "Origin": "https://simplify.jobs",
        "Referer": "https://simplify.jobs/",
    }
    
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    search_query = query_params.get("query", ["Software Engineer"])[0]
    experience = query_params.get("experience", ["Entry Level/New Grad"])[0]
    country = query_params.get("country", ["United States"])[0]
    
    page = 1
    per_page = 21
    cutoff_unix_time = int(time.time()) - (14 * 24 * 60 * 60)

    logger.info(f"🔎 Searching {board} jobs in {country} (Cutoff: {convert_to_est(cutoff_unix_time)})")

    while True:
        payload = {
            "searches": [
                {
                    "collection": "jobs",
                    "facet_by": "countries,degrees,experience_level,functions,locations",
                    "filter_by": f"countries:=[`{country}`] && experience_level:=[`{experience}`]",
                    "highlight_full_fields": "title,company_name,functions,locations",
                    "max_facet_values": 50,
                    "page": page,
                    "per_page": per_page,
                    "q": search_query,
                    "query_by": "title,company_name,functions,locations",
                    "sort_by": "_text_match:desc,updated_date:desc"
                },
                {
                    "collection": "jobs",
                    "facet_by": "countries",
                    "filter_by": f"experience_level:=[`{experience}`]",
                    "highlight_full_fields": "title,company_name,functions,locations",
                    "max_facet_values": 50,
                    "page": page,
                    "per_page": per_page,
                    "q": search_query,
                    "query_by": "title,company_name,functions,locations",
                    "sort_by": "_text_match:desc,updated_date:desc"
                },
                {
                    "collection": "jobs",
                    "facet_by": "experience_level",
                    "filter_by": f"countries:=[`{country}`]",
                    "highlight_full_fields": "title,company_name,functions,locations",
                    "max_facet_values": 50,
                    "page": page,
                    "per_page": per_page,
                    "q": search_query,
                    "query_by": "title,company_name,functions,locations",
                    "sort_by": "_text_match:desc,updated_date:desc"
                }
            ]
        }
        
        params = {"x-typesense-api-key": "sUjQlkfBFnglUFcsFsZVcE7xhI8lJ1RG"}
        
        logger.info(f"📄 Fetching page {page}...")
        try:
            response = session.post(api_url, headers=headers, params=params, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            result = data["results"][0]
            hits = result["hits"]
            total_found = result.get("found", 0)
            logger.info(f"📌 Page {page}: Found {len(hits)}/{total_found} jobs")

            if not hits:
                logger.info("🚫 No more results.")
                break

            current_time = get_current_est_time()
            stale_count = 0
            
            for hit in hits:
                doc = hit["document"]
                updated_date = doc.get("updated_date", "N/A")
                if updated_date == "N/A" or not isinstance(updated_date, int):
                    continue

                if updated_date < cutoff_unix_time:
                    stale_count += 1
                    continue

                title = doc.get("title", "Unknown")
                company = doc.get("company_name", "Unknown Company")
                job_id = doc.get("id", "unknown-id")
                job_title = title.replace(" ", "-").lower()
                simplify_url = f"https://simplify.jobs/p/{job_id}/{job_title}"
                job_key = f"simplify-{job_id}"

                jobs.append({
                    "job_title": title,
                    "company": company,
                    "location": doc.get("locations", ["Unknown Location"])[0],
                    "url": simplify_url,
                    "found_at": current_time,
                    "posted_time": convert_to_est(updated_date),
                    "key": job_key
                })

            if stale_count >= len(hits) // 2:
                logger.info(f"⏳ Majority stale ({stale_count}/{len(hits)}).")
                break
            if page * per_page >= total_found:
                logger.info(f"📊 End of results ({page * per_page}/{total_found}).")
                break

            page += 1
        
        except requests.RequestException as e:
            logger.error(f"❌ API error: {e}")
            break
    
    return jobs


def scrape_linkedin(board, base_url):
    """Scrape jobs from LinkedIn."""
    cookies_dict = None
    if os.path.exists(COOKIE_FILE):
        session = get_session()
        if check_cookies_valid(session):
            cookies_dict = session.cookies.get_dict()
        else:
            logger.info("Existing LinkedIn cookies invalid, logging in")
    
    if not cookies_dict:
        driver = setup_selenium_driver()
        cookies_dict = login_to_linkedin(driver)
        driver.quit()
    
    session = get_session(cookies_dict)
    headers = {
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "csrf-token": session.cookies.get("JSESSIONID", "").strip('"'),
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/134.0.0.0 Safari/537.36",
    }
    
    logger.info(f"Scraping {board} jobs from LinkedIn: {base_url}")
    return fetch_linkedin_jobs(session, headers, cookies_dict, base_url)

SCRAPERS = {
    "Simplify": scrape_simplify,
    "LinkedIn": scrape_linkedin
}

async def main():
    boards = load_board_urls(BOARD_URLS_FILE)
    seen_jobs = load_seen_jobs(SEEN_JOBS_FILE)

    while True:
        logger.info(f"Starting new job check cycle ({get_current_est_time()})")
        total_new_jobs = 0
        cycle_jobs = set()
        new_jobs_to_send = []

        for board in boards:
            board_name = board["board"]
            url = board["URL"]
            location = board["Location"]

            logger.info(f"SEARCHING {board_name.upper()} - {location.upper()}...")
            scraper = SCRAPERS.get(board_name)
            if not scraper:
                logger.warning(f"No scraper defined for {board_name}")
                continue

            new_jobs = scraper(board_name, url)
            logger.info(f"Found {len(new_jobs)} total jobs for {board_name} - {location}")

            new_jobs_count = 0
            for job in new_jobs:
                job_key = job.get("key")  # ✅ Ensure we use the unique key
                job_url = job.get("url")

                if job_key and job_key not in seen_jobs and job_url not in cycle_jobs:
                    new_jobs_count += 1
                    total_new_jobs += 1
                    cycle_jobs.add(job_url)
                    seen_jobs[job_key] = job["found_at"]
                    new_jobs_to_send.append(job)

                    logger.info(f"✅ New job #{new_jobs_count} at {job['company']}:")
                    logger.info(f"  🏢 Company: {job['company']}")
                    logger.info(f"  💼 Job Title: {job['job_title']}")
                    logger.info(f"  📍 Location: {job['location']}")
                    logger.info(f"  🔗 Link: {job['url']}")
                    logger.info(f"  ⏳ Found At: {job['found_at']}")
                    logger.info(f"  📅 Posted At: {job['posted_time']}")
                    logger.info("-" * 50)

            logger.info(f"🔎 Found {new_jobs_count} new jobs for {board_name} - {location}")

        if total_new_jobs > 0:
            cycle_start_message = f"✨ NEW JOB ALERT ({get_current_est_time()}) ✨"
            await send_discord_message(DISCORD_WEBHOOK_URL, cycle_start_message)
            logger.info("Sent cycle start message to Discord")
            for job in new_jobs_to_send:
                discord_message = (
                    f"New job at {job['company']}:\n"
                    f"  Job Title: {job['job_title']}\n"
                    f"  Location: {job['location']}\n"
                    f"  Link: {job['url']}\n"
                    f"  Found At: {job['found_at']}\n"
                    f"  Posted At: {job['posted_time']}\n"
                    f"  Apply Clicks: {job.get('apply_clicks', 'N/A')}"  # Added
                )
                # Uncomment to send to Discord
                await send_discord_message(DISCORD_WEBHOOK_URL, discord_message)
                await asyncio.sleep(1)

        logger.info(f"Cycle completed. Total new jobs: {total_new_jobs}")
        save_seen_jobs(seen_jobs, total_new_jobs, SEEN_JOBS_FILE)
        logger.info("Waiting 30 mins before next check...")
        await asyncio.sleep(30 * 60)


if __name__ == "__main__":
    asyncio.run(main())
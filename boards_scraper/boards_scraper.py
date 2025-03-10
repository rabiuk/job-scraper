import os
import time
import json
import aiohttp  # For async Discord webhook requests
import logging
import asyncio
import requests
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from requests_ratelimiter import LimiterSession
from utils import send_discord_message, load_board_urls, load_seen_jobs, save_seen_jobs
from setup_enviroment import setup_environment
from zoneinfo import ZoneInfo


# Set up environment
setup_environment()


logger = logging.getLogger(__name__)

# Session with rate limiting (assuming this is set up)
session = LimiterSession(per_second=1)

EST = ZoneInfo("America/New_York")

# File paths (adjust as needed)
BOARD_URLS_FILE = "boards_scraper/board_urls.json"
SEEN_JOBS_FILE = "boards_scraper/seen_jobs.json"

# Discord webhook URL (replace with your actual webhook URL or load from env/config)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def convert_to_est(utc_timestamp):
    """Convert UTC timestamp to EST datetime string"""
    if utc_timestamp == "N/A":
        return "N/A"
    utc_time = datetime.utcfromtimestamp(utc_timestamp).replace(tzinfo=timezone.utc)
    est_time = utc_time.astimezone(EST)
    return est_time.strftime("%Y-%m-%d %H:%M:%S EST")

def get_current_est_time():
    """Get current time in EST as formatted string"""
    return datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S EST")


def scrape_simplify(board, base_url):
    """Scrape Simplify.jobs using the Typesense API with dynamic params for countries or locations."""
    jobs = []
    api_url = "https://xv95tgzrem61cja4p.a1.typesense.net/multi_search"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "text/plain",
        "Origin": "https://simplify.jobs",
        "Referer": "https://simplify.jobs/",
        "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
    }
    
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    state = query_params.get("state", [""])[0]
    country = query_params.get("country", [""])[0]
    search_query = query_params.get("query", ["Software Engineer"])[0]
    experience = query_params.get("experience", ["Entry Level/New Grad"])[0]
    most_recent = query_params.get("mostRecent", ["true"])[0].lower() == "true"
    
    if country:
        filter_field = "countries"
        filter_value = country
    elif state:
        filter_field = "locations"
        filter_value = state
    else:
        filter_field = "countries"
        filter_value = ""
    
    page = 1
    per_page = 21
    total_found = 0
    
    current_unix_time = int(time.time())
    cutoff_unix_time = current_unix_time - (14 * 24 * 60 * 60)
    
    while True:
        payload = {
            "searches": [
                {
                    "collection": "jobs",
                    "facet_by": "countries,degrees,experience_level,functions,locations",
                    "filter_by": f"{filter_field}:=[`{filter_value}`] && experience_level:=[`{experience}`]",
                    "highlight_full_fields": "title,company_name,functions,locations",
                    "max_facet_values": 50,
                    "page": page,
                    "per_page": per_page,
                    "q": search_query,
                    "query_by": "title,company_name,functions,locations",
                    "sort_by": "updated_date:desc" if most_recent else "_text_match:desc"
                }
            ]
        }
        
        params = {"x-typesense-api-key": "sUjQlkfBFnglUFcsFsZVcE7xhI8lJ1RG"}
        
        logger.info(f"Scraping {board} jobs from Simplify API, page {page} for {filter_value}")
        logger.debug(f"API payload: {json.dumps(payload, indent=2)}")
        
        try:
            response = session.post(api_url, headers=headers, params=params, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            logger.debug(f"Full API response: {json.dumps(data, indent=2)}")
            
            result = data.get("results", [])[0]
            if "hits" in result:
                total_found = result["found"]
                hits = result["hits"]
                current_time = get_current_est_time() # Grab current est time
                for hit in hits:
                    doc = hit["document"]
                    updated_date = doc.get("updated_date", "N/A")
                    
                    if updated_date != "N/A" and updated_date < cutoff_unix_time:
                        logger.debug(f"Skipping old job: {doc.get('title', 'Unknown')} posted at {datetime.utcfromtimestamp(updated_date).strftime('%Y-%m-%d %H:%M:%S UTC')}")
                        continue
                    
                    job_id = doc.get("id", "unknown-id")
                    job_title = doc.get("title", "Unknown-Title").replace(" ", "-").lower()
                    simplify_url = f"https://simplify.jobs/p/{job_id}/{job_title}"
                    
                    # Convert timestamps to EST
                    posted_time = convert_to_est(updated_date) if updated_date != "N/A" else "N/A"
                    start_date = doc.get("start_date", "N/A")
                    start_time = convert_to_est(start_date) if start_date != "N/A" else "N/A"
                    
                    job = {
                        "job_title": doc.get("title", "Unknown Title"),
                        "company": doc.get("company_name", "Unknown Company"),
                        "location": doc.get("locations", ["Unknown Location"])[0],
                        "url": simplify_url,
                        "found_at": current_time,
                        "posted_time": posted_time,
                        "start_time": start_time,
                        "key": simplify_url
                    }
                    if job["key"] not in [j["key"] for j in jobs]:
                        jobs.append(job)
                
                logger.info(f"Parsed {len(jobs)} unique jobs so far (page {page}, total found: {total_found})")
                
                if len(hits) < per_page or len(jobs) >= total_found:
                    break
                page += 1
            else:
                logger.warning("No hits found in API response")
                break
            
            logger.info(f"API call successful, response length: {len(response.text)}")
        
        except requests.RequestException as e:
            logger.error(f"Error fetching Simplify API data for {board}, page {page}: {e}")
            if "response" in locals():
                logger.debug(f"Response: {response.text[:500]}...")
            break
    
    logger.info(f"Completed scraping {board} - {filter_value}: {len(jobs)} unique jobs (total found: {total_found})")
    return jobs

SCRAPERS = {"Simplify": scrape_simplify}

def main():
    boards = load_board_urls(BOARD_URLS_FILE)
    seen_jobs = load_seen_jobs(SEEN_JOBS_FILE)

    loop = asyncio.get_event_loop()

    while True:
        logger.info("Starting new job check cycle...")
        
        total_new_jobs = 0
        cycle_jobs = set()
        new_jobs_to_send = []  # Store new jobs to send after the "Job Alert" message

        for board in boards:
            board_name = board["board"]
            url = board["URL"]
            location = board["Location"]

            logger.info(" " * 50)
            logger.info("-" * 50)
            logger.info(f"SEARCHING {board_name.upper()} - {location.upper()}...")
            logger.info("-" * 50)

            scraper = SCRAPERS.get(board_name)
            if not scraper:
                logger.warning(f"No scraper defined for {board_name}")
                continue

            new_jobs = scraper(board_name, url)
            logger.info(f"Found {len(new_jobs)} total jobs for {board_name} - {location}")

            new_jobs_count = 0
            for job in new_jobs:
                job_key = job.get("key")
                job_url = job.get("url")
                if job_key and job_key not in seen_jobs and job_url not in cycle_jobs:
                    new_jobs_count += 1
                    total_new_jobs += 1
                    cycle_jobs.add(job_url)
                    seen_jobs[job_key] = job["found_at"]
                    
                    # Log to console
                    logger.info(f"New job #{new_jobs_count} at {job['company']}:")
                    logger.info(f"  Job Title: {job['job_title']}")
                    logger.info(f"  Location: {job['location']}")
                    logger.info(f"  Link: {job['url']}")
                    logger.info(f"  Found At: {job['found_at']}")
                    logger.info(f"  Posted At: {job['posted_time']}")
                    logger.info(f"  Start At: {job['start_time']}")
                    logger.info(f"  Key: {job_key}")
                    logger.info("-" * 50)
                    
                    # Store the job for later sending
                    new_jobs_to_send.append(job)
                else:
                    logger.debug(f"Job already seen in cycle or previous cycles: {job_key}")

            logger.info(f"Found {new_jobs_count} new jobs for {board_name} - {location} in this cycle")

        # Send the "Job Alert" message first if there are new jobs
        if total_new_jobs > 0:
            cycle_start_message = (
                f"---------------\n"
                f"✨ NEW JOB ALERT ({get_current_est_time()}) ✨\n"
                f"--"
            )
            loop.run_until_complete(send_discord_message(DISCORD_WEBHOOK_URL, cycle_start_message))

            # Send individual job messages
            for job in new_jobs_to_send:
                discord_message = (
                    f"-----\n"
                    f"New job at {job['company']}:\n"
                    f"  Job Title: {job['job_title']}\n"
                    f"  Location: {job['location']}\n"
                    f"  Link: {job['url']}\n"
                    f"  Found At: {job['found_at']}\n"
                    f"  Posted At: {job['posted_time']}\n"
                    f"  Start At: {job['start_time']}\n"
                    f"-----"
                )
                loop.run_until_complete(send_discord_message(DISCORD_WEBHOOK_URL, discord_message))

        logger.info(f"Cycle completed. Total new jobs found across all boards: {total_new_jobs}")
        save_seen_jobs(seen_jobs, total_new_jobs, SEEN_JOBS_FILE)
        logger.info("Waiting 30 mins before next check...")
        time.sleep(30 * 60)

if __name__ == "__main__":
    main()

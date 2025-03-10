import os
import re
import json
import smtplib
import logging
import aiohttp  # For async Discord webhook requests
from email.message import EmailMessage

logger = logging.getLogger(__name__)

def send_email(job):
    try:
        email_address = os.getenv("EMAIL_ADDRESS")
        email_password = os.getenv("EMAIL_APP_PASSWORD")

        logger.info(f"Attempting to send email using address: {email_address}")

        if not email_address or not email_password:
            logger.error("Email credentials not found in .env file")
            return

        msg = EmailMessage()
        msg['Subject'] = f"New Job at {job['company']}: {job['job_title']}"
        msg['From'] = email_address
        msg['To'] = email_address

        body = f"""Company: {job['company']}
Job Title: {job['job_title']}
Location: {job['location']}
Link: {job['url']}
Found At: {job['found_at']}
Posted At: {job['posted_time']}
"""
        msg.set_content(body)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(email_address, email_password)
            smtp.send_message(msg)
        logger.info(f"Sent email alert for new job: {job['job_title']} at {job['company']}")

    except Exception as e:
        logger.error(f"Failed to send email for job {job['job_title']} at {job['company']}: {e}")

async def send_discord_message(webhook_url, content, max_retries=3):
    """Send a message to Discord via webhook asynchronously with retry on rate limit."""
    for attempt in range(max_retries):
        async with aiohttp.ClientSession() as session:
            payload = {"content": content}
            async with session.post(webhook_url, json=payload) as response:
                if response.status == 204:  # Success
                    logger.info("Successfully sent job message to Discord")
                    return True
                elif response.status == 429:  # Rate limited
                    retry_after = float((await response.json()).get("retry_after", 0.5))  # Default to 0.5s if missing
                    logger.warning(f"Discord rate limit hit, retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_after)
                else:
                    logger.error(f"Failed to send Discord message: {response.status} - {await response.text()}")
                    return False
    logger.error(f"Failed to send Discord message after {max_retries} attempts due to rate limiting")
    return False

def extract_min_years(text):
    """Extract the minimum years of experience from a text string."""
    text = text.lower()
    min_years = []
    range_matches = re.findall(r'(\d+)-(\d*\+?)\s*years?', text)
    for start, end in range_matches:
        min_years.append(int(start))
    plus_matches = re.findall(r'(\d+)\+\s*years?|at least (\d+)\s*years?', text)
    for match in plus_matches:
        if match[0]:
            min_years.append(int(match[0]))
        elif match[1]:
            min_years.append(int(match[1]))
    standalone_matches = re.findall(r'(\d+)\s*years?', text)
    for match in standalone_matches:
        if int(match) not in min_years:
            min_years.append(int(match))
    return min(min_years) if min_years else 0

def is_entry_level(job, min_qual, pref_qual):
    title = job.get("postingTitle", "").lower()
    summary = job.get("jobSummary", "").lower()
    min_qual = min_qual.lower() if min_qual else ""
    pref_qual = pref_qual.lower() if pref_qual else ""

    # Define positive and negative indicators
    positive_keywords = ["junior", "associate"]  # Only unambiguous single words
    positive_phrases = [
        "entry level", "entry-level", "new grad", "recent graduate", "early career",
        "internship experience", "student", "beginner"
    ]
    negative_keywords = ["senior", "sr", "staff", "lead", "manager", "principal", "expert", "advanced"]

    # Check title and summary
    has_positive_title_summary = any(
        re.search(rf'\b{kw}\b', title) or re.search(rf'\b{kw}\b', summary)
        for kw in positive_keywords
    ) or any(
        phrase in title or phrase in summary for phrase in positive_phrases
    )
    has_negative_title_summary = any(
        re.search(rf'\b{kw}\b', title + " " + summary) 
        for kw in negative_keywords
    )

    logger.debug(f"Title: {title}")
    logger.debug(f"Summary: {summary}")
    logger.debug(f"Has positive keywords: {has_positive_title_summary}")
    logger.debug(f"Has negative keywords: {has_negative_title_summary} (matched: {[kw for kw in negative_keywords if re.search(rf'\b{kw}\b', title + ' ' + summary)]})")

    if has_negative_title_summary:
        logger.debug("Rejected due to negative keywords in title/summary")
        return False
    if has_positive_title_summary:
        logger.debug("Accepted due to positive keywords/phrases in title/summary")
        return True

    # Check qualifications
    has_positive_qual = any(
        re.search(rf'\b{kw}\b', min_qual) or re.search(rf'\b{kw}\b', pref_qual)
        for kw in positive_keywords
    ) or any(
        phrase in min_qual or phrase in pref_qual for phrase in positive_phrases
    )
    
    matched_keywords = [kw for kw in positive_keywords if re.search(rf'\b{kw}\b', min_qual) or re.search(rf'\b{kw}\b', pref_qual)]
    matched_phrases = [phrase for phrase in positive_phrases if phrase in min_qual or phrase in pref_qual]
    if has_positive_qual:
        logger.debug(f"Accepted due to positive keywords/phrases in qualifications: {matched_keywords + matched_phrases}")
        return True

    # Check experience requirement
    if min_qual:
        min_years = extract_min_years(min_qual)
        logger.debug(f"Min years extracted: {min_years}")
        has_zero_start_range = bool(re.search(r'\b0-\d*\+?\s*years?', min_qual))
        if has_zero_start_range:
            logger.debug("Found range starting at 0, accepting as entry-level")
            return True
        if min_years > 1:
            logger.debug(f"Rejecting: {min_years} years exceeds 0-1 threshold")
            return False
        if min_years in (0, 1):
            logger.debug(f"Accepting: {min_years} years within 0-1 threshold")
            return True

    logger.debug("No specific years or keywords, defaulting to no negative keywords check")
    return not has_negative_title_summary

# Load board URLs from JSON
def load_board_urls(board_urls_file="company_scraper/board_urls.json"):
    try:
        with open(board_urls_file, "r") as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"{board_urls_file} is empty. Starting with empty list.")
                return []
            f.seek(0)
            boards = json.load(f)
            # Updated log message to include board name and location
            logger.info(f"Loaded {len(boards)} board URLs from {board_urls_file}: {[f'{b['board']} - {b['Location']}' for b in boards]}")
            return boards
    except FileNotFoundError:
        logger.error(f"{board_urls_file} not found.")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"{board_urls_file} contains invalid JSON: {e}")
        return []

# Load companies from JSON
def load_companies(companies_file="company_scraper/companies.json"):
    try:
        with open(companies_file, "r") as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"{companies_file} is empty. Starting with empty list.")
                return []
            f.seek(0)
            companies = json.load(f)
            logger.info(f"Loaded {len(companies)} companies from {companies_file}: {[c['Company'] for c in companies]}")
            return companies
    except FileNotFoundError:
        logger.error(f"{companies_file} not found.")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"{companies_file} contains invalid JSON: {e}")
        return []

def load_seen_jobs(seen_jobs_file="company_scraper/seen_jobs.json"):
    try:
        with open(seen_jobs_file, "r") as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"{seen_jobs_file} is empty. Starting with empty dict.")
                return {}
            f.seek(0)
            seen_jobs = json.load(f)
            logger.info(f"Loaded {len(seen_jobs)} seen jobs from {seen_jobs_file}")
            return seen_jobs
    except FileNotFoundError:
        logger.error(f"{seen_jobs_file} not found. Creating new empty file.")
        with open(seen_jobs_file, "w") as f:
            json.dump({}, f)
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"{seen_jobs_file} contains invalid JSON: {e}. Resetting to empty dict.")
        with open(seen_jobs_file, "w") as f:
            json.dump({}, f)
        return {}

def save_seen_jobs(seen_jobs, new_jobs_count, seen_jobs_file="company_scraper/seen_jobs.json"):
    with open(seen_jobs_file, "w") as f:
        json.dump(seen_jobs, f, indent=4)
    logger.info(f"Persisted seen jobs (including {new_jobs_count} new) to {seen_jobs_file}. Total seen: {len(seen_jobs)}")
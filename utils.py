from datetime import datetime
import os
import re
import json
import smtplib
import aiohttp  # For async Discord webhook requests
import asyncio
import logging
from bs4 import BeautifulSoup
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

def create_job_entry(company, job_title, url, location, posted_time, posted_datetime, min_qual="", pref_qual=""):
    """
    Create a standardized job entry dictionary with optional qualifications.

    Args:
        company (str): Company name
        job_title (str): Job title
        url (str): Job URL
        location (str): Job location
        posted_time (str): Posting date as string (e.g., "2025-03-12" or "N/A")
        posted_datetime (datetime): Posting date as datetime object
        min_qual (str, optional): Minimum qualifications, defaults to ""
        pref_qual (str, optional): Preferred qualifications, defaults to ""
    
    Returns:
        dict: Standardized job entry, with qualifications added only if non-empty
    """
    job_entry = {
        "company": company,
        "job_title": job_title,
        "url": url,
        "location": location,
        "posted_time": posted_time,
        "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "posted_datetime": posted_datetime
    }
    # Only add qualifications if they’re provided and non-empty
    if min_qual:
        job_entry["minimum_qualifications"] = min_qual
    if pref_qual:
        job_entry["preferred_qualifications"] = pref_qual
    return job_entry

def clean_text(text):
    if not text or not isinstance(text, str):
        # Only log if debugging is critical; otherwise, silently return
        # logger.debug("Clean_text received empty or non-string input, returning empty string")
        return ""
    soup = BeautifulSoup(text, "html.parser")
    plain_text = soup.get_text(separator=" ")
    cleaned = " ".join(plain_text.split()).lower()
    logger.debug(f"Cleaned text from '{text[:100]}...' to '{cleaned[:100]}...'")
    return cleaned


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

def is_entry_level(job):
    title = clean_text(job.get("job_title", ""))
    description = clean_text(job.get("job_description", "")) if job.get("job_description") else ""
    min_qual = clean_text(job.get("minimum_qualifications", "")) if job.get("minimum_qualifications") else ""
    pref_qual = clean_text(job.get("preferred_qualifications", "")) if job.get("preferred_qualifications") else ""

    positive_keywords = ["junior", "associate", "intern"]
    positive_phrases = ["entry level", "entry-level", "new grad", "recent graduate", "early career", "internship experience", "student", "beginner"]
    negative_keywords = ["senior", "head", "sr", "staff", "lead", "manager", "principal", "expert", "vp", "director", "chief", "phd"]

    # Step 1: Prioritize internships
    if "intern" in positive_keywords and re.search(r'\b(intern)\b', title):
        logger.debug("Accepted: Found 'intern' in title, prioritizing as entry-level")
        return True

    # Step 2: Check for negative keywords in the title
    has_negative_keywords_in_title = any(re.search(rf'\b{kw}\b', title) for kw in negative_keywords)
    if has_negative_keywords_in_title:
        matched_keywords = [kw for kw in negative_keywords if re.search(rf'\b{kw}\b', title)]
        logger.debug(f"Rejected: Found negative keywords {matched_keywords} in title")
        return False

    # Step 3: Check for positive indicators in title or description
    has_positive_title_description = (
        any(re.search(rf'\b{kw}\b', title) or re.search(rf'\b{kw}\b', description) for kw in positive_keywords)
        or any(phrase in title or phrase in description for phrase in positive_phrases)
    )
    if has_positive_title_description:
        matched_positives = (
            [kw for kw in positive_keywords if re.search(rf'\b{kw}\b', title) or re.search(rf'\b{kw}\b', description)] +
            [phrase for phrase in positive_phrases if phrase in title or phrase in description]
        )
        logger.debug(f"Accepted: Found positive indicators {matched_positives} in title/description")
        return True

    # Step 4: Check years of experience in all available fields
    combined_text = f"{min_qual} {pref_qual} {description}".strip()
    if combined_text:
        min_years = extract_min_years(combined_text)
        has_zero_start_range = bool(re.search(r'\b0-\d*\+?\s*years?', combined_text))
        if has_zero_start_range:
            logger.debug(f"Accepted: Experience range starts at 0 years")
            return True
        if min_years > 1:
            logger.debug(f"Rejected: Minimum {min_years} years exceeds entry-level threshold")
            return False
        if min_years in (0, 1):
            logger.debug(f"Accepted: Minimum {min_years} year(s) within entry-level threshold")
            return True

    # Step 5: Check for positive indicators in qualifications
    has_positive_qual = (
        any(re.search(rf'\b{kw}\b', min_qual) or re.search(rf'\b{kw}\b', pref_qual) for kw in positive_keywords)
        or any(phrase in min_qual or phrase in pref_qual for phrase in positive_phrases)
    )
    if has_positive_qual:
        matched_positives = (
            [kw for kw in positive_keywords if re.search(rf'\b{kw}\b', min_qual) or re.search(rf'\b{kw}\b', pref_qual)] +
            [phrase for phrase in positive_phrases if phrase in min_qual or phrase in pref_qual]
        )
        logger.debug(f"Accepted: Found positive indicators {matched_positives} in qualifications")
        return True

    # Step 6: Default case - assume entry-level if no experience or seniority specified
    logger.debug("Accepted: No experience or seniority indicators found, assuming entry-level")
    return True


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
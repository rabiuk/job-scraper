import json
import time
import random
from bs4 import BeautifulSoup
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
import urllib
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
import re
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
import os
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from selenium.webdriver.common.action_chains import ActionChains
from urllib.parse import urljoin
import requests
from utils import extract_min_years, is_entry_level

# Load environment variables from .env
load_dotenv()

# Clear the log file at startup
log_file = "company_scraper/scraper.log"
with open(log_file, "w") as f:
    f.write("")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
# logging.basicConfig(
#     level=logging.DEBUG,
#     format="%(asctime)s - %(levelname)s - %(message)s"
# )
logger = logging.getLogger(__name__)

# File paths
COMPANIES_FILE = "company_scraper/companies.json"
SEEN_JOBS_FILE = "company_scraper/seen_jobs.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.96 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15",
]

# Load companies from JSON
def load_companies():
    try:
        with open(COMPANIES_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"{COMPANIES_FILE} is empty. Starting with empty list.")
                return []
            f.seek(0)
            companies = json.load(f)
            logger.info(f"Loaded {len(companies)} companies from {COMPANIES_FILE}: {[c['Company'] for c in companies]}")
            return companies
    except FileNotFoundError:
        logger.error(f"{COMPANIES_FILE} not found.")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"{COMPANIES_FILE} contains invalid JSON: {e}")
        return []

# Load seen jobs from JSON
def load_seen_jobs():
    try:
        with open(SEEN_JOBS_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"{SEEN_JOBS_FILE} is empty. Starting with empty dict.")
                return {}
            f.seek(0)
            seen_jobs = json.load(f)
            logger.info(f"Loaded {len(seen_jobs)} seen jobs from {SEEN_JOBS_FILE}")
            return seen_jobs
    except FileNotFoundError:
        logger.error(f"{SEEN_JOBS_FILE} not found. Creating new empty file.")
        with open(SEEN_JOBS_FILE, "w") as f:
            json.dump({}, f)
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"{SEEN_JOBS_FILE} contains invalid JSON: {e}. Resetting to empty dict.")
        with open(SEEN_JOBS_FILE, "w") as f:
            json.dump({}, f)
        return {}

# Save seen jobs to JSON
def save_seen_jobs(seen_jobs, new_jobs_count):
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(seen_jobs, f, indent=4)
    logger.info(f"Persisted seen jobs (including {new_jobs_count} new) to {SEEN_JOBS_FILE}. Total seen: {len(seen_jobs)}")

# Parse posted date to datetime for sorting
def parse_posted_date(posted_text):
    try:
        match = re.search(r"Posted\s+(\w+\s+\d+,\s+\d{4})", posted_text)
        if match:
            date_str = match.group(1)
            date_str = re.sub(r"\s+", " ", date_str).strip()
            return datetime.strptime(date_str, "%B %d, %Y")
        logger.debug(f"No date found in posted text: {posted_text}")
        return datetime.min
    except Exception as e:
        logger.debug(f"Could not parse posted date '{posted_text}': {e}")
        return datetime.min

# Send email alert for a new job
def send_email(job):
    try:
        email_address = os.getenv("EMAIL_ADDRESS")
        email_password = os.getenv("EMAIL_PASSWORD")

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

# Update URL parameter (e.g., 'offset', 'start', or 'page')
def update_url_param(url, param_name, param_value):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    query_params[param_name] = [str(param_value)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query,
        parsed_url.fragment
    ))

# Amazon-specific scraper using Selenium
def scrape_amazon(company, base_url, location):
    jobs = []
    api_base_url = "https://www.amazon.jobs/en/search.json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-CA,en;q=0.9",
        "Referer": base_url,
    }
    
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    
    params = {
        "normalized_country_code[]": query_params.get("country[]", ["USA"]),
        "radius": query_params.get("radius", ["24km"])[0],
        "industry_experience[]": query_params.get("industry_experience", ["less_than_1_year"])[0],
        "facets[]": [
            "normalized_country_code", "normalized_state_name", "normalized_city_name",
            "location", "business_category", "category", "schedule_type_id",
            "employee_class", "normalized_location", "job_function_id", "is_manager", "is_intern"
        ],
        "offset": "0",
        "result_limit": query_params.get("result_limit", ["10"])[0],
        "sort": query_params.get("sort", ["recent"])[0],
        "base_query": query_params.get("base_query", ["Software Engineer"])[0],
    }
    
    if "state[]" in query_params:
        params["normalized_state_name[]"] = query_params["state[]"]
    
    logger.info(f"Scraping {company} jobs")
    
    try:
        offset = 0
        result_limit = int(params["result_limit"])
        total_hits = None
        
        while True:
            params["offset"] = str(offset)
            logger.info(f"Fetching page at offset {offset}")
            
            response = requests.get(api_base_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if offset == 0:
                logger.debug(f"Raw API response: {json.dumps(data, indent=2)[:1000]}...")
            
            if data.get("error"):
                logger.error(f"API error: {data['error']}")
                break
            
            if total_hits is None:
                total_hits = data.get("hits", 0)
                logger.info(f"Total jobs expected: {total_hits}")
            
            job_list = data.get("jobs", [])
            if not job_list:
                logger.info(f"No more jobs at offset {offset}")
                break
            
            logger.info(f"Found {len(job_list)} jobs at offset {offset}")
            
            for job in job_list:
                job_id = job.get("id")
                if not job_id:
                    logger.warning("Job missing ID, skipping")
                    continue
                
                job_path = job.get("job_path", "")
                job_url = f"https://www.amazon.jobs{job_path}" if job_path else f"https://www.amazon.jobs/en/jobs/{job_id}"
                
                locations = job.get("locations", [])
                if locations:
                    try:
                        if isinstance(locations[0], str):
                            first_location = json.loads(locations[0])
                            job_location = first_location.get("normalizedLocation", location)
                        else:
                            job_location = locations[0].get("normalizedLocation", location)
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"Failed to parse location {locations}: {e}")
                        job_location = job.get("location", location)
                else:
                    job_location = job.get("location", location)
                
                if "remote" in job_location.lower():
                    job_location = f"Remote - {location}"
                
                posted_date = job.get("posted_date", "N/A")
                if posted_date != "N/A":
                    try:
                        # Handle "Month Day, Year" format with extra spaces
                        posted_date_cleaned = " ".join(posted_date.split())  # Normalize spaces
                        posted_datetime = datetime.strptime(posted_date_cleaned, "%B %d, %Y")
                        posted_time = posted_datetime.strftime("%Y-%m-%d")
                    except ValueError as e:
                        logger.debug(f"Failed to parse posted_date '{posted_date}': {e}")
                        posted_time = "N/A"
                        posted_datetime = datetime.now()
                else:
                    posted_time = "N/A"
                    posted_datetime = datetime.now()
                
                job_entry = {
                    "company": company,
                    "job_title": job.get("title", "Unknown Title"),
                    "url": job_url,
                    "location": job_location,
                    "posted_time": posted_time,
                    "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "posted_datetime": posted_datetime
                }
                jobs.append(job_entry)
                logger.info(f"Added job: {job_entry['job_title']} at {job_entry['location']}")
            
            if len(job_list) < result_limit or (total_hits and offset + result_limit >= total_hits):
                logger.info(f"End of jobs (extracted {len(jobs)} of {total_hits})")
                break
            
            offset += result_limit
            time.sleep(2)
        
        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        logger.info(f"Extracted {len(jobs)} jobs from {company}")
        
    except Exception as e:
        logger.error(f"Error scraping {company}: {e}")
        if "response" in locals():
            logger.debug(f"Response: {response.text[:500]}...")
    
    return jobs

# Google-specific scraper using Selenium
def scrape_google(company, base_url, location):
    jobs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
    }
    
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    
    page = 1
    results_per_page = 20
    
    while True:
        query_params["page"] = [str(page)]
        paginated_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{urlencode(query_params, doseq=True)}"
        logger.info(f"Scraping {company} page {page}")
        
        try:
            response = requests.get(paginated_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            script_pattern = r"AF_initDataCallback\(({.*?})\);"
            matches = re.findall(script_pattern, response.text, re.DOTALL)
            if not matches:
                logger.warning("No AF_initDataCallback found")
                break
            
            job_data_str = None
            for script_content in matches:
                data_match = re.search(r"data:\s*(\[.*?\])\s*,\s*sideChannel", script_content, re.DOTALL)
                if data_match:
                    data_str = data_match.group(1)
                    try:
                        temp_list = json.loads(data_str)
                        if temp_list and isinstance(temp_list[0], list) and temp_list[0] and isinstance(temp_list[0][0], list) and isinstance(temp_list[0][0][0], str) and temp_list[0][0][0].isdigit():
                            job_data_str = data_str
                            break
                    except json.JSONDecodeError:
                        continue
            
            if not job_data_str:
                logger.error("No job data found in AF_initDataCallback")
                break
            
            try:
                job_list = json.loads(job_data_str)[0]
                logger.debug(f"Found {len(job_list)} job entries in job_list")
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing failed: {e}")
                break
            
            job_items = job_list
            if not job_items:
                logger.info(f"No jobs on page {page}")
                break
            
            logger.info(f"Found {len(job_items)} jobs on page {page}")
            
            for job in job_items:
                job_id = job[0]
                job_title = job[1]
                job_url = f"https://www.google.com/about/careers/applications/jobs/results/{job_id}-{job_title.lower().replace(' ', '-')}"
                company_name = job[7]
                
                locations = job[9]  # Correct index for locations
                job_location = ", ".join(loc[0] for loc in locations) if locations else location
                
                posted_timestamp = job[10][0] if job[10] and len(job[10]) > 0 else None
                if posted_timestamp is not None:
                    posted_datetime = datetime.fromtimestamp(posted_timestamp)
                    posted_time = posted_datetime.strftime("%Y-%m-%d")
                else:
                    posted_time = "N/A"
                    posted_datetime = datetime.now()
                
                job_entry = {
                    "company": company_name,
                    "job_title": job_title,
                    "url": job_url,
                    "location": job_location,
                    "posted_time": posted_time,
                    "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "posted_datetime": posted_datetime
                }
                jobs.append(job_entry)
                logger.info(f"Added job: {job_title} at {job_location}")
            
            if len(job_items) < results_per_page:
                logger.info(f"End of jobs at page {page} (total: {len(jobs)})")
                break
            
            page += 1
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Error on page {page}: {e}")
            break
    
    jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
    logger.info(f"Extracted {len(jobs)} jobs from {company}")
    return jobs

# Netflix-specific scraper using Selenium
def scrape_netflix(company, base_url, location):
    """Scrape Netflix job listings using the API endpoint with pagination."""
    jobs = []
    seen_urls = set()
    
    # Headers to mimic browser request
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": "https://explore.jobs.netflix.net/careers",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    
    # Parse the base URL to extract query parameters
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    logger.info(f"Scraping Netflix jobs for '{company}' with query: {query_params.get('query', [''])[0]}")
    
    # Construct the API base URL and pagination settings
    api_base = "https://explore.jobs.netflix.net/api/apply/v2/jobs"
    params = {
        "domain": "netflix.com",
        "query": query_params.get("query", [""])[0],
        "location": query_params.get("location", [""])[0],
        "Teams": query_params.get("Teams", []),
        "Work Type": query_params.get("Work Type", []),
        "Region": query_params.get("Region", []),
        "sort_by": query_params.get("sort_by", ["new"])[0],
        "start": 0,
        "num": 10,  # Number of jobs per page
    }
    
    while True:
        try:
            # Make API request
            api_url = f"{api_base}?{urlencode(params, doseq=True)}"
            response = requests.get(api_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse JSON response
            data = response.json()
            positions = data.get("positions", [])
            total_count = data.get("count", 0)
            logger.info(f"Fetched {len(positions)} jobs from page starting at {params['start']}, total expected: {total_count}")
            
            if not positions:
                logger.info("No more jobs found, ending pagination")
                break
            
            # Process each job
            for job in positions:
                job_id = job.get("id")
                if not job_id:
                    logger.warning("Job missing ID, skipping")
                    continue
                
                job_url = f"https://explore.jobs.netflix.net/careers/job/{job_id}"
                if job_url in seen_urls:
                    logger.info(f"Skipping duplicate job with URL {job_url}")
                    continue
                seen_urls.add(job_url)
                
                locations = job.get("locations", [])
                job_location = locations[0] if locations else location
                if "remote" in job_location.lower():
                    job_location = f"Remote - {location}"
                
                t_create = job.get("t_create")
                if t_create:
                    try:
                        posted_datetime = datetime.fromtimestamp(t_create)
                        posted_time = posted_datetime.strftime("%Y-%m-%d")
                    except ValueError as e:
                        logger.debug(f"Failed to parse t_create '{t_create}': {e}")
                        posted_time = "N/A"
                        posted_datetime = datetime.now()
                else:
                    posted_time = "N/A"
                    posted_datetime = datetime.now()
                
                job_entry = {
                    "company": company,
                    "job_title": job.get("name", "Unknown Title"),
                    "url": job_url,
                    "location": job_location,
                    "posted_time": posted_time,
                    "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "posted_datetime": posted_datetime
                }
                jobs.append(job_entry)
                logger.info(f"Added job: {job_entry['job_title']} at {job_entry['location']}")
            
            # Check if we've fetched all jobs
            if params["start"] + len(positions) >= total_count:
                logger.info(f"Fetched all {total_count} jobs, ending pagination")
                break
            
            # Move to next page
            params["start"] += params["num"]
        
        except requests.RequestException as e:
            logger.error(f"Error fetching jobs: {e}")
            break
    
    # Sort jobs by posting date (newest first)
    jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
    logger.info(f"Extracted {len(jobs)} unique jobs from {company}")
    
    return jobs


def scrape_intuit(company, base_url, location):
    """Scrape Intuit job listings and return US/Canada Software Engineering jobs."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://jobs.intuit.com/",
    }
    
    # Parse base URL
    parsed_url = urlparse(base_url)
    path_parts = parsed_url.path.strip("/").split("/")
    keyword = path_parts[1] if len(path_parts) > 1 else "Software"
    tenant_id = path_parts[2] if len(path_parts) > 2 else "27595"
    query_params = parse_qs(parsed_url.query)
    
    api_base_url = f"https://jobs.intuit.com/search-jobs/{keyword}/{tenant_id}/1"
    
    logger.info(f"Scraping {company} jobs")
    
    all_jobs = []
    us_ca_states = {
        "US": ["NY", "GA", "CA", "TX", "FL", "IL", "MA", "WA", "Bay Area", "Greater San Diego & Los Angeles", "Atlanta", "New York", "San Diego", "Los Angeles", "Plano"],
        "CA": ["Ontario", "ON", "BC", "AB", "QC", "Toronto"]
    }
    
    try:
        page = 1
        expected_total = None
        total_pages = None
        
        while True:
            params = {"p": str(page)}
            if "glat" in query_params and "glon" in query_params:
                params["glat"] = query_params["glat"][0]
                params["glon"] = query_params["glon"][0]
            
            logger.info(f"Fetching page {page}")
            response = requests.get(api_base_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            job_items = soup.find_all("li", attrs={"data-intuit-jobid": True})
            if not job_items:
                logger.info(f"No more jobs on page {page}")
                break
            
            # Extract metadata
            search_section = soup.find("section", id="search-results")
            if search_section:
                h1_tag = search_section.find("h1")
                if h1_tag:
                    title_text = h1_tag.text.strip()
                    logger.info(f"Page {page} title: {title_text}")
                    if not expected_total and "jobs found for Software" in title_text:
                        expected_total = int(title_text.split()[0])
                        logger.info(f"Expected total jobs from HTML: {expected_total}")
                if not total_pages:
                    total_pages = int(search_section.get("data-total-pages", 0))
                    logger.info(f"Total pages: {total_pages}")
            
            logger.info(f"Found {len(job_items)} jobs on page {page}")
            
            # Parse jobs
            for item in job_items:
                job_id = item.get("data-intuit-jobid", "N/A")
                title = item.find("h2").text.strip() if item.find("h2") else "Unknown Title"
                job_location = item.find("span", class_="job-location").text.strip() if item.find("span", class_="job-location") else "Unknown Location"
                category = item.get("data-category", "N/A")
                
                job = {"job_id": job_id, "title": title, "location": job_location, "category": category}
                all_jobs.append(job)
            
            if total_pages and page >= total_pages:
                logger.info(f"Reached total pages ({page}/{total_pages}); stopping.")
                break
            
            page += 1
            time.sleep(2)
        
        logger.info(f"Total unfiltered jobs collected: {len(all_jobs)}")
        
        # Filter US/Canada
        us_ca_jobs = []
        for job in all_jobs:
            job_location = job["location"]
            if any(country in job_location for country in ["Canada", "United States", "CA", "US"]) or "Multiple Locations" in job_location:
                us_ca_jobs.append(job)
            else:
                for regions in us_ca_states.values():
                    if any(region in job_location for region in regions):
                        us_ca_jobs.append(job)
                        break
        logger.info(f"Total US/Canada jobs after filtering: {len(us_ca_jobs)}")
        
        # Filter Software Engineering and format jobs
        jobs = []
        now = datetime.now()
        for job in us_ca_jobs:
            if job["category"] == "Software Engineering":
                job_entry = {
                    "company": company,
                    "job_title": job["title"],
                    "url": f"https://jobs.intuit.com/job/{job['job_id']}",
                    "location": job["location"],
                    "posted_time": "N/A",  # Intuit HTML doesn’t provide this easily
                    "found_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "posted_datetime": now
                }
                jobs.append(job_entry)
        
        logger.info(f"Total US/Canada Software Engineering jobs: {len(jobs)}")
        
    except Exception as e:
        logger.error(f"Error scraping {company}: {e}")
        return []
    
    return jobs


def scrape_microsoft(company, base_url, location):
    jobs = []
    
    # API endpoint for Microsoft job search
    api_url = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
    
    # Headers to mimic browser request (from your logs)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-CA,en;q=0.9",
        "Origin": "https://jobs.careers.microsoft.com",
        "Referer": base_url,
        "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }
    
    # Parse query parameters from base_url
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    
    # Convert query_params to a flat dict (taking first value for each key)
    params = {key: value[0] for key, value in query_params.items()}
    
    # Ensure some defaults if not present in base_url
    params.setdefault("l", "en_us")      # Language default
    params.setdefault("pg", "1")         # Start at page 1
    params.setdefault("pgSz", "20")      # Default page size
    params.setdefault("o", "Relevance")  # Default sort order
    params.setdefault("flt", "true")     # Default filter flag
    
    # Log the initial request details
    logger.info(f"Parsed params from base_url: {params}")
    logger.info(f"Making API request to {api_url} with initial page {params['pg']}")
    
    try:
        while True:
            # Convert pg and pgSz to integers for pagination logic
            current_page = int(params["pg"])
            page_size = int(params["pgSz"])
            
            # Send GET request to API
            response = requests.get(api_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Extract job listings
            job_data = data.get("operationResult", {}).get("result", {}).get("jobs", [])
            if not job_data:
                logger.warning(f"No jobs found on page {current_page}")
                break
            
            total_jobs = data.get("operationResult", {}).get("result", {}).get("totalJobs", 0)
            logger.info(f"Found {len(job_data)} jobs on page {current_page}, total expected: {total_jobs}")
            
            # Process each job
            for job in job_data:
                job_id = job.get("jobId")
                if not job_id:
                    logger.warning("Job missing jobId, skipping")
                    continue
                
                # Construct specific job URL
                job_url = f"https://jobs.careers.microsoft.com/global/en/job/{job_id}/"
                
                # Get location, fallback to provided location
                job_location = ", ".join(job.get("properties", {}).get("locations", [])) or location
                if "remote" in job_location.lower():
                    job_location = f"Remote - {location}"
                
                # Parse posting date
                posting_date = job.get("postingDate", "N/A")
                if posting_date != "N/A":
                    try:
                        posted_datetime = datetime.strptime(posting_date, "%Y-%m-%dT%H:%M:%S+00:00")
                        posted_time = posted_datetime.strftime("%Y-%m-%d")
                    except ValueError as e:
                        logger.debug(f"Failed to parse postingDate '{posting_date}': {e}")
                        posted_time = "N/A"
                        posted_datetime = datetime.now()
                else:
                    posted_time = "N/A"
                    posted_datetime = datetime.now()
                
                # Build job entry
                job_entry = {
                    "company": company,
                    "job_title": job.get("title", "Unknown Title"),
                    "url": job_url,
                    "location": job_location,
                    "posted_time": posted_time,
                    "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "posted_datetime": posted_datetime
                }
                jobs.append(job_entry)
                logger.info(f"Added job: {job_entry['job_title']} at {job_entry['location']}")
            
            # Pagination check
            if len(jobs) >= total_jobs or len(job_data) < page_size:
                logger.info(f"Reached end of jobs (extracted {len(jobs)} of {total_jobs})")
                break
            
            # Move to next page
            params["pg"] = str(current_page + 1)
            logger.info(f"Moving to page {params['pg']}")
            time.sleep(2)  # Avoid rate limiting
        
        logger.info(f"Extracted {len(jobs)} jobs from {company}")
        
    except Exception as e:
        logger.error(f"Error fetching API data for {company}: {e}")
        if "response" in locals():
            logger.debug(f"Response: {response.text[:500]}...")
    
    return jobs

def scrape_meta(company, base_url, location):
    """Scrape Meta job listings and filter for University/Grad roles."""
    jobs = []
    url = "https://www.metacareers.com/graphql"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-CA,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.metacareers.com",
        "Referer": base_url,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "X-FB-Friendly-Name": "CareersJobSearchResultsDataQuery",
        "X-FB-LSD": "AVrqx8rmwwE",
        "X-ASBD-ID": "359341",
    }
    
    # Parse URL parameters
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    
    # Function to extract array parameters with index syntax
    def extract_array_param(params, param_name):
        pattern = re.compile(rf"^{re.escape(param_name)}\[\d+\]$", re.IGNORECASE)
        values = []
        for key in params:
            if pattern.match(key):
                values.extend(params[key])
        return values
    
    # Extract parameters
    teams = extract_array_param(query_params, 'teams')
    roles = extract_array_param(query_params, 'roles')
    divisions = extract_array_param(query_params, 'divisions')
    offices = extract_array_param(query_params, 'offices')
    
    # Log parsed parameters
    logger.info(f"Parsed teams: {teams}")
    logger.info(f"Parsed roles: {roles}")
    logger.info(f"Parsed divisions: {divisions}")
    logger.info(f"Parsed offices: {offices}")
    
    # Build GraphQL variables
    graphql_vars = {
        "search_input": {
            "q": query_params.get('q', [None])[0],
            "divisions": divisions,
            "offices": offices,
            "roles": roles,
            "teams": teams,
            "is_leadership": query_params.get('is_leadership', ['false'])[0].lower() == 'true',
            "is_remote_only": query_params.get('is_remote_only', ['false'])[0].lower() == 'true',
            "sort_by_new": query_params.get('sort_by_new', ['false'])[0].lower() == 'true',
            "results_per_page": None
        }
    }

    payload = {
        "av": "0",
        "__user": "0",
        "__a": "1",
        "__req": "2",
        "__hs": "20154.BP:DEFAULT.2.0...0",
        "dpr": "1",
        "__ccg": "GOOD",
        "__rev": "1020679384",
        "__s": "3z4y9a:85mlan:w3unkh",
        "__hsi": "7478941632714904730",
        "lsd": "AVrqx8rmwwE",
        "jazoest": "21084",
        "__spin_r": "1020679384",
        "__spin_b": "trunk",
        "__spin_t": "1741326794",
        "__jssesw": "1",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": "CareersJobSearchResultsDataQuery",
        "variables": json.dumps(graphql_vars),
        "server_timestamps": "true",
        "doc_id": "9509267205807711",
    }

    try:
        logger.info(f"Making GraphQL request to {url}")
        response = requests.post(url, headers=headers, data=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        job_data = data.get("data", {}).get("job_search_with_featured_jobs", {}).get("all_jobs", [])
        
        if not job_data:
            logger.warning("No jobs found in response")
            return jobs
        
        # Collect all jobs
        all_jobs = []
        for job in job_data:
            job_id = job.get("id")
            if not job_id:
                continue
                
            job_url = f"https://www.metacareers.com/jobs/{job_id}/"
            job_location = ", ".join(job.get("locations", [])) if job.get("locations") else location
            
            if "remote" in job_location.lower():
                job_location = f"Remote - {location}"
                
            job_entry = {
                "company": company,
                "job_title": job.get("title", "Unknown Title"),
                "url": job_url,
                "location": job_location,
                "posted_time": "N/A",
                "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "posted_datetime": datetime.now()
            }
            all_jobs.append(job_entry)
        
        logger.info(f"Extracted {len(all_jobs)} total jobs from {company}")
        
        # Filter for University/Grad roles (case-insensitive)
        jobs = [job for job in all_jobs if "university" in job["job_title"].lower() or "grad" in job["job_title"].lower()]
        logger.info(f"Filtered to {len(jobs)} University/Grad jobs")
        
    except Exception as e:
        logger.error(f"Error fetching GraphQL data: {e}")
        if "response" in locals():
            logger.debug(f"Response: {response.text[:500]}...")
    
    return jobs

def scrape_apple(company, base_url, location):
    jobs = []
    seen_ids_per_page = {}
    
    session = requests.Session()
    
    page = 1
    cutoff_date = datetime.now() - timedelta(days=14)
    logger.info(f"Cutoff date for jobs: {cutoff_date.strftime('%Y-%m-%d')}")
    
    max_retries = 3
    retry_delay = 10  # Increased from 5 to 10 seconds
    page_delay = random.uniform(5, 10)  # Random delay between 5-10 seconds
    
    parsed_url = urllib.parse.urlparse(base_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    if "key" in query_params:
        query_params["key"] = [urllib.parse.unquote(query_params["key"][0])]
    logger.info(f"Scraping {company} jobs with query: {query_params}")
    
    while True:
        # Rotate User-Agent per page
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://jobs.apple.com/en-us/search",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cookie": "geo=US; dslang=US-EN; s_cc=true; at_check=true"
        }
        session.headers.update(headers)
        
        query_params["page"] = [str(page)]
        query_string = "&".join(f"{k}={urllib.parse.quote(v[0], safe='')}" for k, v in query_params.items())
        paginated_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{query_string}"
        logger.debug(f"Fetching {company} page {page} at {paginated_url} with User-Agent: {headers['User-Agent']}")
        
        for attempt in range(max_retries):
            try:
                response = session.get(paginated_url, timeout=30)
                response.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Attempt {attempt + 1} failed for page {page}: {e}. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Error fetching page {page} after {max_retries} attempts: {e}")
                    if "502" in str(e) or "503" in str(e):
                        logger.info("Possible rate limit detected. Pausing for 15 minutes before exiting...")
                        time.sleep(900)  # 15-minute pause
                    jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
                    logger.info(f"Extracted {len(jobs)} entry-level jobs from {company}")
                    return jobs
        
        match = re.search(r"window\.APP_STATE\s*=\s*({.*?});", response.text, re.DOTALL)
        if not match:
            logger.warning(f"No APP_STATE found on page {page}")
            break
        
        app_state = json.loads(match.group(1))
        total_jobs = app_state.get("totalRecords", float('inf'))
        job_list = app_state.get("searchResults", [])
        
        if not job_list:
            logger.info(f"No jobs found on page {page}")
            break
        
        logger.info(f"Found {len(job_list)} jobs on page {page}")
        previous_total = len(jobs)
        seen_ids_per_page[page] = set()
        
        last_job = job_list[-1]
        last_posting_date = last_job.get("postingDate", "N/A")
        if last_posting_date != "N/A":
            try:
                last_posted_datetime = datetime.strptime(last_posting_date, "%b %d, %Y")
                if last_posted_datetime < cutoff_date:
                    logger.info(f"Page {page} oldest job ({last_job.get('id')}: {last_job.get('postingTitle')}) posted {last_posted_datetime.strftime('%Y-%m-%d')} is before cutoff {cutoff_date.strftime('%Y-%m-%d')}. Stopping.")
                    break
            except ValueError:
                logger.warning(f"Could not parse date for job {last_job.get('id')}: {last_posting_date}")
        
        for job in job_list:
            job_id = job.get("id")
            if not job_id or job_id in seen_ids_per_page[page]:
                continue
            seen_ids_per_page[page].add(job_id)
            
            posting_date = job.get("postingDate", "N/A")
            if posting_date != "N/A":
                try:
                    posted_datetime = datetime.strptime(posting_date, "%b %d, %Y")
                    posted_time = posted_datetime.strftime("%Y-%m-%d")
                    if posted_datetime < cutoff_date:
                        logger.debug(f"Skipping job {job_id} ({job.get('postingTitle')}) - Posted {posted_time}, before cutoff")
                        continue
                except ValueError:
                    posted_time = "N/A"
                    posted_datetime = datetime.now()
            else:
                posted_time = "N/A"
                posted_datetime = datetime.now()
            
            detail_url = f"https://jobs.apple.com/api/role/detail/{job_id}?languageCd=en-us"
            try:
                detail_response = session.get(detail_url, timeout=10)
                detail_response.raise_for_status()
                detail_data = detail_response.json()
                min_qual = detail_data.get("minimumQualifications", "")
                pref_qual = detail_data.get("preferredQualifications", "")
            except requests.RequestException as e:
                logger.warning(f"Failed to fetch details for job {job_id}: {e}")
                min_qual = ""
                pref_qual = ""
            
            if not is_entry_level(job, min_qual, pref_qual):
                years = extract_min_years(min_qual)
                title = job.get("postingTitle", "").lower()
                summary = job.get("jobSummary", "").lower()
                negative_keywords = ["senior", "sr", "staff", "lead", "manager", "principal", "expert", "advanced"]
                has_negative_title_summary = any(
                    re.search(rf"\b{kw}\b|\b{kw}\s+.*engineer|\b{kw}\s+.*developer", title + " " + summary)
                    for kw in negative_keywords
                )
                if years > 1:
                    reason = f"Years: {years}"
                elif has_negative_title_summary:
                    reason = "Negative keyword in title/summary"
                else:
                    reason = "Other rejection criteria"
                logger.debug(f"Skipped job: {job.get('postingTitle')} (ID: {job_id}) - Reason: {reason}")
                continue
            
            reason = "No years mentioned" if not extract_min_years(min_qual) else f"Max {extract_min_years(min_qual)} year(s)"
            logger.info(f"Entry-level job found: {job.get('postingTitle')} (ID: {job_id}) - Reason: {reason}")
            logger.debug(f"Minimum Qualifications: {min_qual if min_qual else 'Not provided'}")
            
            transformed_title = job.get("transformedPostingTitle", job.get("postingTitle", "unknown-title").lower().replace(" ", "-"))
            job_url = f"https://jobs.apple.com/en-us/details/{job_id}/{transformed_title}"
            
            locations = job.get("locations", [])
            job_location = locations[0].get("name", location) if locations else location
            if job.get("homeOffice", False):
                job_location = f"Remote - {job_location}"
            
            job_entry = {
                "company": company,
                "job_title": job.get("postingTitle", "Unknown Title"),
                "url": job_url,
                "location": job_location,
                "posted_time": posted_time,
                "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "posted_datetime": posted_datetime,
                "minimum_qualifications": min_qual
            }
            jobs.append(job_entry)
        
        logger.info(f"Page {page} added {len(jobs) - previous_total} new jobs, cumulative total: {len(jobs)}")
        logger.info(f"Total jobs reported by site: {total_jobs}, fetched so far: {len(jobs)}")
        
        if len(job_list) < 20 or len(jobs) >= total_jobs:
            logger.info(f"Stopping at page {page} (fetched: {len(jobs)}, total expected: {total_jobs})")
            break
        
        page += 1
        logger.info(f"Waiting {page_delay:.2f} seconds before next page...")
        time.sleep(page_delay)  # Random delay between pages
    
    jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
    logger.info(f"Extracted {len(jobs)} entry-level jobs from {company}")
    return jobs

SCRAPERS = {
    "Amazon": scrape_amazon,
    "Google": scrape_google,
    "Netflix": scrape_netflix,
    "Intuit": scrape_intuit,
    "Microsoft": scrape_microsoft,
    "Meta": scrape_meta,
    "Apple": scrape_apple,
}

# Main loop
def main():
    companies = load_companies()
    seen_jobs = load_seen_jobs()

    while True:
        logger.info("Starting new job check cycle...")
        for company in companies:
            company_name = company["Company"]
            url = company["URL"]
            location = company["Location"]

            # Add the formatted company search separator
            logger.info(" " * 50)
            logger.info("-" * 50)
            logger.info(f"SEARCHING {company_name.upper()}...")
            logger.info("-" * 50)

            scraper = SCRAPERS.get(company_name)
            if not scraper:
                logger.warning(f"No scraper defined for {company_name}")
                continue

            new_jobs = scraper(company_name, url, location)
            logger.info(f"Found {len(new_jobs)} total jobs for {company_name}")

            new_jobs_count = 0
            for job in new_jobs:
                job_url = job["url"]
                if job_url and job_url not in seen_jobs:
                    new_jobs_count += 1
                    seen_jobs[job_url] = job["found_at"]
                    logger.info(f"New job #{new_jobs_count} at {job['company']}:")
                    logger.info(f"  Job Title: {job['job_title']}")
                    logger.info(f"  Location: {job['location']}")
                    logger.info(f"  Link: {job['url']}")
                    logger.info(f"  Found At: {job['found_at']}")
                    logger.info(f"  Posted At: {job['posted_time']}")
                    logger.info("-" * 50)
                    send_email(job)

            logger.info(f"Found {new_jobs_count} new jobs for {company_name} in this cycle")

        save_seen_jobs(seen_jobs, new_jobs_count)
        logger.info("Waiting 30 mins before next check...")
        time.sleep(30 * 60)

if __name__ == "__main__":
    main()
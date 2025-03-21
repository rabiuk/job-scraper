import os
import json
import time
import random
import logging
import requests
import tempfile
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import quote, urlparse, parse_qs
from dotenv import load_dotenv
from config import EST
from selenium.common.exceptions import TimeoutException

logger = logging.getLogger(__name__)
load_dotenv()

COOKIE_FILE = "boards_scraper/linkedin_cookies.json"


def setup_selenium_driver():
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-breakpad")

    # ✅ Use a persistent user data directory
    user_data_dir = os.path.expanduser("~/.config/google-chrome")
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

    service = Service("/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # ✅ Log driver initialization and open LinkedIn manually
    print("Chrome WebDriver initialized successfully.")
    driver.get("https://www.linkedin.com")
    print("Navigated to LinkedIn.")

    return driver


def type_human_like(element, text):
    """Types text into an element with human-like speed."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))

def login_to_linkedin(driver):
    """
    Logs into LinkedIn, saves cookies, and provides detailed feedback.
    Returns a dictionary of cookies on success, raises an exception on failure.
    """
    email = os.getenv("LINKEDIN_EMAIL")
    password = os.getenv("LINKEDIN_PASSWORD")
    
    if not email or not password:
        error_msg = "Missing LinkedIn credentials. Please set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in your .env file."
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info("Starting LinkedIn login process...")
    driver.get("https://www.linkedin.com/login")
    
    try:
        # Wait for and fill email field
        logger.debug("Locating email field...")
        email_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        logger.debug("Typing email with human-like speed...")
        type_human_like(email_field, email)
        
        # Fill password field
        logger.debug("Locating password field...")
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
        logger.debug("Typing password with human-like speed...")
        type_human_like(password_field, password)
        
        # Submit login form
        logger.debug("Locating login button...")
        login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
        )
        logger.debug("Submitting login form...")
        login_button.click()
        
        # Handle post-login scenarios
        try:
            # Wait for successful login (global navigation bar) or error message
            WebDriverWait(driver, 30).until(
                lambda d: (
                    d.find_elements(By.CLASS_NAME, "global-nav") or
                    d.find_elements(By.ID, "error-for-password") or
                    d.find_elements(By.ID, "error-for-username")
                )
            )
            
            # Check for login errors
            error_elements = {
                "password": driver.find_elements(By.ID, "error-for-password"),
                "username": driver.find_elements(By.ID, "error-for-username")
            }
            for field, elements in error_elements.items():
                if elements and elements[0].is_displayed():
                    error_text = elements[0].text
                    logger.error(f"Login failed due to {field} error: {error_text}")
                    raise Exception(f"Login failed: {error_text}")
            
            # Confirm successful login
            if driver.find_elements(By.CLASS_NAME, "global-nav"):
                logger.info("Login successful, waiting for session to stabilize...")
                time.sleep(2)  # Ensure cookies are fully set
                
                cookies = driver.get_cookies()
                cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}
                
                # Log key cookie details for debugging
                important_cookies = {'JSESSIONID', 'li_at', 'lidc', 'bcookie'}
                for cookie in cookies:
                    if cookie['name'] in important_cookies:
                        expiry = cookie.get('expiry', 'Session')
                        expiry_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d %H:%M:%S") if expiry != 'Session' else 'Session'
                        logger.debug(f"Cookie {cookie['name']} set, expires: {expiry_str}")
                
                # Save cookies
                with open(COOKIE_FILE, "w") as f:
                    json.dump(cookies, f)
                logger.info(f"Saved {len(cookies)} cookies to {COOKIE_FILE}")
                
                return cookies_dict
            else:
                logger.error("Unexpected login state: no navigation bar or error message detected")
                raise Exception("Login completed but success not confirmed")
        
        except TimeoutException:
            logger.error("Login timed out after 30 seconds; possible MFA or network issue")
            raise Exception("Login timed out; check for MFA or network connectivity")
    
    except Exception as e:
        logger.error(f"Login process failed: {str(e)}", exc_info=True)
        raise Exception(f"Failed to log into LinkedIn: {str(e)}")
    
    finally:
        # Optional: Uncomment to keep browser open for debugging on failure
        # logger.debug("Keeping browser open for inspection; close manually when done")
        # input("Press Enter to close the browser...")
        pass

def get_session(cookies=None):
    """Returns a requests.Session with cookies."""
    session = requests.Session()
    if cookies:
        session.cookies.update(cookies)
        logger.info("Using provided cookies for LinkedIn session")
    elif os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "r") as f:
            cookies = json.load(f)
        session.cookies.update({cookie['name']: cookie['value'] for cookie in cookies})
        logger.info(f"Loaded {len(cookies)} cookies from {COOKIE_FILE}")
    else:
        logger.warning("No cookies available for LinkedIn; login required")
    return session

def check_cookies_valid(session):
    """Checks if cookies are valid."""
    test_url = "https://www.linkedin.com/voyager/api/identity/profiles/me"
    headers = {
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "csrf-token": session.cookies.get("JSESSIONID", "").strip('"'),
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/134.0.0.0 Safari/537.36",
    }
    try:
        response = session.get(test_url, headers=headers, timeout=10)
        if response.status_code == 200:
            logger.info("Cookies validated successfully")
            return True
        else:
            logger.warning(f"Cookie validation failed with status {response.status_code}: {response.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Cookie validation failed: {str(e)}")
        return False

def parse_job_postings(response_data):
    """Extracts job postings from API response."""
    job_postings = []
    for item in response_data.get("included", []):
        if item.get("$type") == "com.linkedin.voyager.dash.jobs.JobPosting" and not item.get("repostedJob", False):
            entity_urn = item.get("entityUrn", "")
            job_id = entity_urn.split(":")[3] if entity_urn and len(entity_urn.split(":")) >= 4 else None
            job_postings.append({
                "job_id": job_id,
                "job_title": item.get("title", ""),
                "url": f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else None,
            })
    return job_postings

def fetch_job_detail(session, job_id, headers, cookies):
    """Fetches detailed job info."""
    jobPostingUrn = f"urn:li:fsd_jobPosting:{job_id}"
    encoded_jobPostingUrn = quote(jobPostingUrn, safe='')
    variables = f"(cardSectionTypes:List(TOP_CARD,HOW_YOU_FIT_CARD),jobPostingUrn:{encoded_jobPostingUrn},includeSecondaryActionsV2:true,includeHowYouFitCard:true,includeFitLevelCard:true)"
    queryId = "voyagerJobsDashJobPostingDetailSections.37c03692ed8b5db1c59b6ba4bff59bb8"
    detail_url = f"https://www.linkedin.com/voyager/api/graphql?variables={variables}&queryId={queryId}"
    
    response = session.get(detail_url, headers=headers, cookies=cookies, timeout=30)
    return response.json() if response.status_code == 200 else None

def parse_job_detail(detail_data):
    """Extracts company and detailed tertiary info including repost_info and apply_clicks."""
    company_name = None
    tertiary = {
        "location": "Unknown",
        "posted_time": "Unknown",  # Changed from previous code to match main structure
        "repost_info": "Unknown",  # Added for "X days ago"
        "apply_clicks": "Unknown"  # Added for "X applicants"
    }
    for item in detail_data.get("included", []):
        if "name" in item and not company_name:
            company_name = item["name"]
        if "tertiaryDescription" in item:
            tertiary_text = item["tertiaryDescription"].get("text", "")
            parts = [part.strip() for part in tertiary_text.split("·")]
            if len(parts) >= 3:
                tertiary = {
                    "location": parts[0],
                    "repost_info": parts[1],  # e.g., "2 days ago"
                    "apply_clicks": parts[2]  # e.g., "15 applicants"
                }
            elif len(parts) == 2:
                tertiary = {
                    "location": parts[0],
                    "repost_info": parts[1],
                    "apply_clicks": "Unknown"
                }
            else:
                tertiary = {
                    "location": tertiary_text,
                    "repost_info": "Unknown",
                    "apply_clicks": "Unknown"
                }
    return company_name or "Unknown", tertiary


def parse_url_to_api_query(url):
    """Converts LinkedIn URL to API query."""
    parsed_url = urlparse(url)
    params = parse_qs(parsed_url.query)
    
    base_api_url = (
        "https://www.linkedin.com/voyager/api/voyagerJobsDashJobCards?"
        "decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-218"
        "&count=25&q=jobSearch&query=("
    )
    
    query_parts = []
    if "currentJobId" in params:
        query_parts.append(f"currentJobId:{params['currentJobId'][0]}")
    if "origin" in params:
        query_parts.append(f"origin:{params['origin'][0]}")
    if "keywords" in params:
        query_parts.append(f"keywords:{quote(params['keywords'][0])}")
    if "geoId" in params:
        query_parts.append(f"locationUnion:(geoId:{params['geoId'][0]})")
    if "distance" in params:
        query_parts.append(f"distance:{params['distance'][0]}")
    
    filters = []
    if "f_E" in params:
        filters.append(f"experience:List({params['f_E'][0]})")
    if "f_TPR" in params:
        filters.append(f"timePostedRange:List({params['f_TPR'][0]})")
    if "f_WT" in params:
        filters.append(f"workRemoteAllowed:List({params['f_WT'][0]})")
    if "f_C" in params:
        filters.append(f"company:List({params['f_C'][0]})")
    if "sortBy" in params:
        filters.append(f"sortBy:List({params['sortBy'][0]})")
    if filters:
        query_parts.append(f"selectedFilters:({','.join(filters)})")
    
    if "spellCorrectionEnabled" in params:
        query_parts.append(f"spellCorrectionEnabled:{params['spellCorrectionEnabled'][0]}")
    
    query_string = ",".join(query_parts)
    return f"{base_api_url}{query_string})"

def fetch_job_description(session, job_id, headers, cookies):
    """Fetches job description from LinkedIn API."""
    url = f"https://www.linkedin.com/voyager/api/jobs/jobPostings/{job_id}"
    response = session.get(url, headers=headers, cookies=cookies, timeout=30)
    if response.status_code == 200:
        data = response.json()
        description = data.get("data", {}).get("description", {}).get("text", "No description available")
        return description
    logger.warning(f"Failed to fetch description for job {job_id}: {response.status_code}")
    return "No description available"

def fetch_linkedin_jobs(session, headers, cookies, url, max_pages=5):
    """Fetches LinkedIn jobs with descriptions, ignoring 'Jobs via Dice' and filtering entry-level."""
    from utils import is_entry_level  # Import here or at the top of the file

    jobs = []
    base_api_url = parse_url_to_api_query(url)
    
    for page in range(max_pages):
        start = page * 25
        api_url = f"{base_api_url}&start={start}"
        logger.info(f"Fetching LinkedIn page {page + 1} (start={start})")
        
        response = session.get(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Failed to retrieve jobs: {response.status_code}")
            break
        
        job_postings = parse_job_postings(response.json())
        if not job_postings:
            logger.info(f"No more jobs on page {page + 1}")
            break
        
        current_time = datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S")
        for job in job_postings:
            detail_data = fetch_job_detail(session, job['job_id'], headers, cookies)
            description = fetch_job_description(session, job['job_id'], headers, cookies)
            if detail_data:
                company, tertiary = parse_job_detail(detail_data)
                if "Jobs via Dice" in company:
                    logger.info(f"Skipping job '{job['job_title']}' from 'Jobs via Dice'")
                    continue
                
                # Check if the job is entry-level
                mock_job = {"job_title": job["job_title"], "job_description": description}
                if not is_entry_level(mock_job):
                    logger.debug(f"Skipped non-entry-level job: {job['job_title']}")
                    continue
                
                jobs.append({
                    "job_title": job["job_title"],
                    "company": company,
                    "location": tertiary["location"],
                    "url": job["url"],
                    "found_at": current_time,
                    "posted_time": tertiary["repost_info"],
                    "key": job["url"],
                    "apply_clicks": tertiary["apply_clicks"],
                    "description": description  # Add description to job data
                })
        
        logger.info(f"Found {len(job_postings)} jobs on page {page + 1}")
        time.sleep(random.uniform(2, 5))
    
    return jobs
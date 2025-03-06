import json
import time
from bs4 import BeautifulSoup
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import re
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
import os
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from selenium.webdriver.common.action_chains import ActionChains

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
logger = logging.getLogger(__name__)

# File paths
COMPANIES_FILE = "company_scraper/companies.json"
SEEN_JOBS_FILE = "company_scraper/seen_jobs.json"

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
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        driver.set_page_load_timeout(30)

        result_limit = 10
        offset = 0
        total_jobs = 0
        previous_job_urls = set()

        while True:
            url = update_url_param(base_url, "offset", offset)
            logger.info(f"Scraping {company} page at {url} (offset={offset})")
            
            driver.get(url)
            logger.info(f"Successfully loaded page for {company} at offset={offset}")

            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, "html.parser")

            if not total_jobs:
                total_jobs_tag = soup.find("span", class_="total-jobs")
                if total_jobs_tag:
                    total_jobs = int(total_jobs_tag.text.strip())
                    logger.info(f"Total jobs found: {total_jobs}")
                else:
                    logger.warning("Could not determine total number of jobs. Will scrape until no more jobs found.")

            job_tile_container = soup.find("div", class_="job-tile-lists")
            if not job_tile_container:
                logger.warning(f"No job-tile-lists container found on {company} page at offset={offset}")
                logger.debug(f"HTML snippet: {str(soup)[:1000]}...")
                break

            job_tiles = job_tile_container.find_all("div", class_="job-tile")
            logger.info(f"Found {len(job_tiles)} job tiles on {company} page at offset={offset}")

            if not job_tiles:
                break

            current_job_urls = set()
            for job_tile in job_tiles:
                link_tag = job_tile.find("a", class_="job-link")
                job_url = link_tag["href"] if link_tag else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.amazon.jobs{job_url}"
                current_job_urls.add(job_url)

            if current_job_urls and current_job_urls == previous_job_urls:
                logger.info(f"Same jobs found at offset={offset} as previous page. Stopping pagination.")
                break
            previous_job_urls = current_job_urls

            for job_tile in job_tiles:
                title_tag = job_tile.find("h3", class_="job-title")
                if not title_tag:
                    continue
                link_tag = title_tag.find("a", class_="job-link")
                job_title = link_tag.text.strip() if link_tag else title_tag.text.strip()

                job_url = link_tag["href"] if link_tag else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.amazon.jobs{job_url}"

                location_container = job_tile.find("div", class_="location-and-id")
                job_location = location
                if location_container:
                    location_list = location_container.find("ul")
                    if location_list:
                        locations = [li.text.strip() for li in location_list.find_all("li") if "Job ID" not in li.text and li.text.strip() != "|"]
                        job_location = ", ".join(locations)
                        if "remote" in job_location.lower():
                            job_location = f"Remote - {location}"

                posted_tag = job_tile.find("h2", class_="posting-date")
                posted_time = posted_tag.text.strip() if posted_tag else "N/A"

                job_data = {
                    "company": company,
                    "job_title": job_title,
                    "url": job_url,
                    "location": job_location,
                    "posted_time": posted_time,
                    "found_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "posted_datetime": parse_posted_date(posted_time)
                }
                jobs.append(job_data)

            offset += result_limit
            if total_jobs and offset >= total_jobs:
                logger.info(f"Reached total jobs ({total_jobs}). Stopping pagination.")
                break

        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        logger.info(f"Extracted and sorted {len(jobs)} jobs from {company}")

    except Exception as e:
        logger.error(f"Error scraping {company} ({url}): {e}")
    finally:
        if driver:
            driver.quit()
    return jobs

# Google-specific scraper using Selenium
def scrape_google(company, base_url, location):
    jobs = []
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        driver.set_page_load_timeout(30)

        start = 0
        jobs_per_page = 10
        total_jobs = 0
        previous_job_urls = set()

        while True:
            if "?" in base_url:
                url = f"{base_url}&start={start}"
            else:
                url = f"{base_url}?start={start}"
            logger.info(f"Scraping {company} page at {url} (start={start})")
            
            driver.get(url)
            logger.info(f"Successfully loaded page for {company} at start={start}")

            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, "html.parser")

            if not total_jobs:
                total_jobs_tag = soup.find("div", jsname="uEp2ad")
                if total_jobs_tag:
                    total_text = total_jobs_tag.text.strip()
                    match = re.search(r"of (\d+)", total_text)
                    if match:
                        total_jobs = int(match.group(1))
                        logger.info(f"Total jobs found: {total_jobs}")
                if not total_jobs:
                    logger.warning("Could not determine total number of jobs. Will scrape until no more jobs found.")

            job_items = soup.find_all("li", class_="lLd3Je")
            logger.info(f"Found {len(job_items)} job tiles on {company} page at start={start}")

            if not job_items:
                break

            current_job_urls = set()
            for job_item in job_items:
                link_tag = job_item.find("a", jsname="hSRGPd")
                job_url = link_tag["href"] if link_tag else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.google.com/about/careers/applications/{job_url}"
                current_job_urls.add(job_url)

            if current_job_urls and current_job_urls == previous_job_urls:
                logger.info(f"Same jobs found at start={start} as previous page. Stopping pagination.")
                break
            previous_job_urls = current_job_urls

            for job_item in job_items:
                title_tag = job_item.find("h3", class_="QJPWVe")
                if not title_tag:
                    continue
                job_title = title_tag.text.strip()

                link_tag = job_item.find("a", jsname="hSRGPd")
                job_url = link_tag["href"] if link_tag else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.google.com/about/careers/applications/{job_url}"

                location_container = job_item.find("p", class_="l103df")
                job_location = location
                if location_container:
                    location_spans = location_container.find_all("span", class_=["r0wTof", "BVHzed", "Z2gFhf"])
                    locations = [span.text.strip() for span in location_spans]
                    job_location = "; ".join(locations)
                    if "remote" in job_location.lower():
                        job_location = f"Remote - {location}"

                posted_time = "N/A"

                job_data = {
                    "company": company,
                    "job_title": job_title,
                    "url": job_url,
                    "location": job_location,
                    "posted_time": posted_time,
                    "found_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "posted_datetime": parse_posted_date(posted_time) if posted_time != "N/A" else datetime.now()
                }
                jobs.append(job_data)

            start += jobs_per_page
            if total_jobs and start >= total_jobs:
                logger.info(f"Reached total jobs ({total_jobs}). Stopping pagination.")
                break

        logger.info(f"Extracted {len(jobs)} jobs from {company}")

    except Exception as e:
        logger.error(f"Error scraping {company} ({url}): {e}")
    finally:
        if driver:
            driver.quit()
    return jobs

# Netflix-specific scraper using Selenium
def scrape_netflix(company, base_url, location):
    jobs = []
    seen_urls = set()  # Track seen URLs to avoid duplicates
    driver = None
    try:
        chrome_options = Options()
        # Uncomment for headless mode after testing
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        logger.info("Initializing WebDriver")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        driver.set_page_load_timeout(30)

        logger.info(f"Navigating to base URL: {base_url}")
        driver.get(base_url)
        logger.info("Successfully loaded initial page")

        # Pagination to load all jobs
        logger.info("Starting pagination to load all jobs")
        retry_attempts = 3
        while True:
            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            
            # Check for end of jobs
            all_positions_loaded = soup.find("div", class_="all-positions-loaded-div")
            if all_positions_loaded:
                logger.info("Found 'No more matching jobs' message. Stopping pagination.")
                break

            job_items = soup.find_all("div", class_=["card", "position-card", "pointer"])
            current_job_count = len(job_items)
            logger.info(f"Current job count: {current_job_count}")
            if expected_jobs > 0 and current_job_count >= expected_jobs:
                logger.info(f"Reached expected number of jobs ({current_job_count}/{expected_jobs}). Stopping pagination.")
                break

            # Click "Show More Positions"
            for attempt in range(retry_attempts):
                try:
                    cards_container = driver.find_element(By.CLASS_NAME, "position-cards-container")
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'end'});", cards_container)
                    time.sleep(1)
                    show_more_button = driver.find_element(By.CLASS_NAME, "show-more-positions")
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", show_more_button)
                    time.sleep(1)
                    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "show-more-positions")))
                    logger.info(f"Attempt {attempt + 1}/{retry_attempts}: Clicking 'Show More Positions'")
                    ActionChains(driver).move_to_element(show_more_button).click().perform()
                    WebDriverWait(driver, 30).until(
                        lambda d: len(d.find_elements(By.CSS_SELECTOR, "div.card.position-card.pointer")) > current_job_count
                        or d.find_elements(By.CLASS_NAME, "all-positions-loaded-div")
                    )
                    time.sleep(5)
                    break
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1}/{retry_attempts} failed: {e}")
                    if attempt == retry_attempts - 1:
                        logger.error("Max retry attempts reached. Stopping pagination.")
                        break
                    time.sleep(2)
            else:
                break

        # Scroll to top to ensure all cards are accessible
        logger.info("Scrolling to top before collecting jobs")
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)

        # Collect all job cards
        soup = BeautifulSoup(driver.page_source, "html.parser")
        job_items = soup.find_all("div", class_=["card", "position-card", "pointer"])
        logger.info(f"Found {len(job_items)} job tiles after loading all jobs")

        for index, job_item in enumerate(job_items):
            # Extract basic info from the card
            title_tag = job_item.find("div", class_="position-title")
            if not title_tag:
                logger.warning(f"Job at index {index} has no title tag")
                continue
            job_title = title_tag.text.strip()
            logger.info(f"Processing job at index {index}: {job_title}")

            card_id = job_item.get("data-test-id", "")
            if not card_id:
                logger.warning(f"No data-test-id for job: {job_title}")
                continue
            card_index = card_id.replace("position-card-", "")
            logger.info(f"Card index: {card_index}")

            # Click the card to get the URL
            try:
                job_card = driver.find_element(By.CSS_SELECTOR, f"div[data-test-id='position-card-{card_index}']")
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", job_card)
                time.sleep(1)
                WebDriverWait(driver, 10).until(EC.element_to_be_clickable(job_card))
                logger.info(f"Clicking job card for {job_title}")
                original_url = driver.current_url
                ActionChains(driver).move_to_element(job_card).click().perform()
                WebDriverWait(driver, 10).until(lambda d: d.current_url != original_url)
                time.sleep(2)
                job_url = driver.current_url
                logger.info(f"Captured URL for {job_title}: {job_url}")
            except Exception as e:
                logger.warning(f"Failed to click card or capture URL for {job_title}: {e}")
                job_url = "N/A"

            if job_url in seen_urls:
                logger.info(f"Skipping duplicate job with URL {job_url} for {job_title}")
                continue
            seen_urls.add(job_url)

            # Extract location
            location_tag = job_item.find("p", class_="position-location")
            job_location = location
            if location_tag:
                location_text = location_tag.text.strip()
                if location_text.startswith("📍"):
                    location_text = location_text[1:].strip()
                job_location = location_text
                if "remote" in job_location.lower():
                    job_location = f"Remote - {location}"
            logger.info(f"Location for {job_title}: {job_location}")

            # Extract department
            department_tag = job_item.find("span", id=f"position-department-{card_index}")
            department = department_tag.text.strip() if department_tag else "N/A"
            logger.info(f"Department for {job_title}: {department}")

            posted_time = "N/A"
            job_data = {
                "company": company,
                "job_title": job_title,
                "url": job_url,
                "location": job_location,
                "posted_time": posted_time,
                "found_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "posted_datetime": datetime.now()  # Default to now since posted time is N/A
            }
            jobs.append(job_data)
            logger.info(f"Added job {job_title}. Total jobs: {len(jobs)}")

        logger.info(f"Extracted {len(jobs)} unique jobs from {company}")

    except Exception as e:
        logger.error(f"Error scraping {company} ({base_url}): {e}")
    finally:
        if driver:
            driver.quit()
    return jobs


# Dictionary mapping companies to their scraping functions
SCRAPERS = {
    "Amazon": scrape_amazon,
    "Google": scrape_google,
    "Netflix": scrape_netflix
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
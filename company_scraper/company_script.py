import os
import re
import time
import json
import urllib
import random
import brotli
import requests
import logging
import zstandard as zstd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from setup_environment import setup_environment
from utils import create_job_entry, send_email, is_entry_level, load_companies, load_seen_jobs, save_seen_jobs
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin
from requests_ratelimiter import LimiterSession


# Set up environment
setup_environment() # loads .env stuff, sets python path, and logger level to DEBUG
logger = logging.getLogger(__name__)


# Define a global rate-limited session
session = LimiterSession(per_second=0.5, per_host=True) # 1 request every 2 secs per domain

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

# Amazon-specific scraper
def scrape_amazon(company, base_url, location):
    jobs = []
    api_base_url = "https://www.amazon.jobs/en/search.json"
    
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
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
            
            response = session.get(api_base_url, headers=headers, params=params, timeout=30)
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
                
                job_entry = create_job_entry(
                    company=company,
                    job_title=job.get("title", "Unknown Title"),
                    url=job_url,
                    location=job_location,
                    posted_time=posted_time,
                    posted_datetime=posted_datetime
                )
                jobs.append(job_entry)
                logger.debug(f"Added job: {job_entry['job_title']} at {job_entry['location']}")
            
            if len(job_list) < result_limit or (total_hits and offset + result_limit >= total_hits):
                logger.info(f"End of jobs (extracted {len(jobs)} of {total_hits})")
                break
            
            offset += result_limit
        
        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        logger.info(f"Extracted {len(jobs)} jobs from {company}")
        
    except Exception as e:
        logger.error(f"Error scraping {company}: {e}")
        if "response" in locals():
            logger.debug(f"Response: {response.text[:500]}...")
    
    return jobs

# Google-specific scraper
def scrape_google(company, base_url, location):
    jobs = []
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
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
            response = session.get(paginated_url, headers=headers, timeout=30)
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
                
                job_entry = create_job_entry(
                    company=company_name,
                    job_title=job_title,
                    url=job_url,
                    location=job_location,
                    posted_time=posted_time,
                    posted_datetime=posted_datetime
                )

                jobs.append(job_entry)
                logger.debug(f"Added job: {job_title} at {job_location}")
            
            if len(job_items) < results_per_page:
                logger.info(f"End of jobs at page {page} (total: {len(jobs)})")
                break
            
            page += 1
            
        except Exception as e:
            logger.error(f"Error on page {page}: {e}")
            break
    
    jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
    logger.info(f"Extracted {len(jobs)} jobs from {company}")
    return jobs

# Netflix-specific scraper
def scrape_netflix(company, base_url, location):
    """Scrape Netflix job listings using the API endpoint with pagination."""
    jobs = []
    seen_urls = set()
    
    # Headers to mimic browser request
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
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
            response = session.get(api_url, headers=headers, timeout=30)
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
                
                job_entry = create_job_entry(
                    company=company,
                    job_title=job.get("name", "Unknown Title"),
                    url=job_url,
                    location=job_location,
                    posted_time=posted_time,
                    posted_datetime=posted_datetime
                )
                jobs.append(job_entry)
                logger.debug(f"Added job: {job_entry['job_title']} at {job_entry['location']}")
            
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

# Intuit-specific scraper
def scrape_intuit(company, base_url, location):
    """Scrape Intuit job listings and return US/Canada Software Engineering jobs."""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
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
            response = session.get(api_base_url, headers=headers, params=params, timeout=30)
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
                link_tag = item.find("a", href=True)
                job_url = urljoin("https://jobs.intuit.com/", link_tag["href"]) if link_tag else f"https://jobs.intuit.com/job/{job_id}"
                
                job = {"job_id": job_id, "title": title, "location": job_location, "category": category, "url": job_url}
                all_jobs.append(job)
            
            if total_pages and page >= total_pages:
                logger.info(f"Reached total pages ({page}/{total_pages}); stopping.")
                break
            
            page += 1
        
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
                mock_job = {
                    "job_title": job["title"],
                    "job_description": ""  # Intuit doesn't provide descriptions
                }

                # Check if entry level using title only
                if is_entry_level(mock_job):  # No quals, defaults to ""
                    job_entry = create_job_entry(
                        company=company,
                        job_title=job["title"],
                        url=job["url"],
                        location=job["location"],
                        posted_time="Unknown", # Intuit doesnt provide this
                        posted_datetime=datetime.now()
                    )
                    jobs.append(job_entry)
                    logger.debug(f"Added entry-level job: {job['title']}")
                else:
                    logger.debug(f"Skipped non-entry-level position: {job['title']}")
        
        logger.info(f"Final US/Canada Software Engineering entry-level jobs: {len(jobs)}")
        
    except Exception as e:
        logger.error(f"Error scraping {company}: {e}")
        return []
    
    return jobs

# Microsoft-specific scraper
def scrape_microsoft(company, base_url, location):
    """Scrape Microsoft job listings for all available entry-level jobs."""
    jobs = []
    seen_job_ids = set()
    api_url = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
    
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Origin": "https://jobs.careers.microsoft.com",
        "Referer": "https://jobs.careers.microsoft.com/",
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }
    
    parsed_url = urlparse(base_url)
    params = parse_qs(parsed_url.query)
    params["pgSz"] = "20"  # Matches API's enforced page size
    
    logger.info(f"Starting scrape with params: {params}")
    
    page = 1
    total_jobs_encountered = 0
    
    while True:
        params["pg"] = str(page)
        try:
            response = session.get(api_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            job_list = data["operationResult"]["result"].get("jobs", [])
            total_jobs_encountered += len(job_list)
            
            if not job_list:
                logger.info(f"No jobs found on page {page}. Stopping.")
                break
            
            for job in job_list:
                job_id = job.get("jobId")
                if not job_id or job_id in seen_job_ids:
                    continue

                job_title = job.get("title", "Unknown Title")
                job_description = job.get("properties", {}).get("description", "")
                mock_job = {"job_title": job_title, "job_description": job_description, "jobId": job_id}
                
                seen_job_ids.add(job_id)
                
                if not is_entry_level(mock_job):
                    continue

                job_url = f"https://jobs.careers.microsoft.com/global/en/job/{job_id}/"
                locations = [loc["description"] for loc in job.get("locations", [])]
                job_location = ", ".join(locations) if locations else location
                
                posted_date = job.get("postedDate", "N/A")
                if posted_date != "N/A":
                    try:
                        posted_datetime = datetime.strptime(posted_date.split("T")[0], "%Y-%m-%d")
                        posted_time = posted_datetime.strftime("%Y-%m-%d")
                    except ValueError:
                        posted_time = "N/A"
                        posted_datetime = datetime.now()
                else:
                    posted_time = "N/A"
                    posted_datetime = datetime.now()
                
                job_entry = create_job_entry(
                    company=company,
                    job_title=job_title,
                    url=job_url,
                    location=job_location,
                    posted_time=posted_time,
                    posted_datetime=posted_datetime
                )
                jobs.append(job_entry)
            
            page += 1
            time.sleep(random.uniform(2, 4))
        
        except requests.RequestException as e:
            logger.error(f"Error fetching page {page}: {e}")
            break
    
    jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
    logger.info(f"Finished scraping {company}: {total_jobs_encountered} total jobs found, {len(jobs)} entry-level jobs extracted")
    return jobs

# Meta-specific scraper
def scrape_meta(company, base_url, location):
    jobs = []
    url = "https://www.metacareers.com/graphql"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
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
        "X-FB-LSD": "AVrqx8rmwwE",  # Consider fetching dynamically if needed
        "X-ASBD-ID": "359341",
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    
    def extract_array_param(params, param_name):
        pattern = re.compile(rf"^{re.escape(param_name)}\[\d+\]$", re.IGNORECASE)
        values = []
        for key in params:
            if pattern.match(key):
                values.extend(params[key])
        return values
    
    teams = extract_array_param(query_params, 'teams')
    roles = extract_array_param(query_params, 'roles')
    divisions = extract_array_param(query_params, 'divisions')
    offices = extract_array_param(query_params, 'offices')
    
    logger.info(f"Parsed teams: {teams}")
    logger.info(f"Parsed roles: {roles}")
    logger.info(f"Parsed divisions: {divisions}")
    logger.info(f"Parsed offices: {offices}")
    
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
        response = session.post(url, data=payload, timeout=60)  # Increased timeout
        response.raise_for_status()
        
        # Log response details
        logger.debug(f"Response headers: {response.headers}")
        logger.debug(f"Raw response length: {len(response.content)} bytes")
        
        # Handle zstd decompression
        if response.headers.get("Content-Encoding") == "zstd":
            logger.debug("Decompressing zstd-encoded response")
            try:
                decompressed = zstd.decompress(response.content)
                data_str = decompressed.decode("utf-8")
                logger.debug(f"Decompressed response (first 500 chars): {data_str[:500]}")
                data = json.loads(data_str)
            except zstd.ZstdError as e:
                logger.error(f"Zstd decompression failed: {e}")
                # Attempt to parse raw content as JSON in case it's not actually zstd
                try:
                    data = json.loads(response.content.decode("utf-8"))
                    logger.debug("Parsed raw content as JSON despite zstd header")
                except json.JSONDecodeError as je:
                    logger.error(f"Failed to parse raw content as JSON: {je}")
                    return jobs
        else:
            logger.debug("Raw response content (first 500 chars): {response.content[:500]}")
            data = response.json()
        
        # Extract jobs
        job_data = data.get("data", {}).get("job_search_with_featured_jobs", {}).get("all_jobs", [])
        logger.debug(f"Job data extracted: {len(job_data)} jobs found in response")
        
        if not job_data:
            logger.warning("No jobs found in response")
            return jobs
        
        all_jobs = []
        for job in job_data:
            job_id = job.get("id")
            if not job_id:
                logger.warning("Job missing ID, skipping")
                continue
            job_url = f"https://www.metacareers.com/jobs/{job_id}/"
            job_location = ", ".join(job.get("locations", [])) if job.get("locations") else location
            if "remote" in job_location.lower():
                job_location = f"Remote - {location}"
            job_entry = create_job_entry(
                company=company,
                job_title=job.get("title", "Unknown Title"),
                url=job_url,
                location=job_location,
                posted_time="Unknown",
                posted_datetime=datetime.now()
            )
            all_jobs.append(job_entry)
            logger.debug(f"Added job: {job_entry['job_title']} at {job_entry['location']}")
        
        logger.info(f"Extracted {len(all_jobs)} total jobs from {company}")
        
        # Filter for University/Grad roles
        jobs = [job for job in all_jobs if "university" in job["job_title"].lower() or "grad" in job["job_title"].lower()]
        logger.info(f"Filtered to {len(jobs)} University/Grad jobs")
        
    except Exception as e:
        logger.error(f"Error fetching GraphQL data: {e}")
        if "response" in locals():
            logger.debug(f"Raw response content: {response.content[:500]}")
    
    return jobs

# Apple-specific scraper
def scrape_apple(company, base_url, location):
    jobs = []
    seen_ids_per_page = {}
    
    page = 1
    cutoff_date = datetime.now() - timedelta(days=14)
    logger.info(f"Cutoff date for jobs: {cutoff_date.strftime('%Y-%m-%d')}")
    
    max_retries = 3
    retry_delay = 10  # Increased from 5 to 10 seconds
    
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
            
            posting_date = job.get("postingDate", "Unknown")
            if posting_date != "Unknown":
                try:
                    posted_datetime = datetime.strptime(posting_date, "%b %d, %Y")
                    posted_time = posted_datetime.strftime("%Y-%m-%d")
                    if posted_datetime < cutoff_date:
                        logger.debug(f"Skipping job {job_id} ({job.get('postingTitle')}) - Posted {posted_time}, before cutoff")
                        continue
                except ValueError:
                    posted_time = "Unknown"
                    posted_datetime = datetime.now()
            else:
                posted_time = "Unknown"
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

            mock_job = {
                "job_title": job.get("postingTitle", "Unknown Title"),
                "job_description": job.get("jobDescription", ""),
                "minimum_qualifications": min_qual,
                "preferred_qualifications": pref_qual
            }
            
            if not is_entry_level(mock_job):
                logger.debug(f"Skipped non-entry-level job: {job.get('postingTitle')} (ID: {job_id})")
                continue
            
            logger.info(f"Entry-level job found: {job.get('postingTitle')} (ID: {job_id})")

            transformed_title = job.get("transformedPostingTitle", job.get("postingTitle", "unknown-title").lower().replace(" ", "-"))
            job_url = f"https://jobs.apple.com/en-us/details/{job_id}/{transformed_title}"
            
            locations = job.get("locations", [])
            job_location = locations[0].get("name", location) if locations else location
            if job.get("homeOffice", False):
                job_location = f"Remote - {job_location}"
            
            job_entry = create_job_entry(
                company=company,
                job_title=job.get("postingTitle", "Unknown Title"),
                url=job_url,
                location=job_location,
                posted_time=posted_time,
                posted_datetime=posted_datetime,
                min_qual=min_qual,
                pref_qual=pref_qual
            )
            job_entry["minimum_qualifications"] = min_qual  # Add extra field
            jobs.append(job_entry)
        
        logger.info(f"Page {page} added {len(jobs) - previous_total} new jobs, cumulative total: {len(jobs)}")
        logger.info(f"Total jobs reported by site: {total_jobs}, fetched so far: {len(jobs)}")
        
        if len(job_list) < 20 or len(jobs) >= total_jobs:
            logger.info(f"Stopping at page {page} (fetched: {len(jobs)}, total expected: {total_jobs})")
            break
        
        page += 1
    
    jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
    logger.info(f"Extracted {len(jobs)} entry-level jobs from {company}")
    return jobs

def scrape_uber(company, base_url, location):
    jobs = []
    api_url = "https://www.uber.com/api/loadSearchJobsResults?localeCode=en"
    
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-CA,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://www.uber.com",
        "Referer": base_url,
        "x-csrf-token": "x",  # TODO: Fetch dynamically if required
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    query = query_params.get("query", ["Software Engineer"])[0]
    departments = query_params.get("department", ["Engineering"])
    locations_raw = query_params.get("location", [])
    locations = []
    for loc in locations_raw:
        parts = loc.split("-")
        if len(parts) >= 3:
            country = parts[0]
            region = parts[1]
            city = "-".join(parts[2:])
            locations.append({"country": country, "region": region, "city": city})
    
    payload = {
        "limit": 10,
        "page": 0,
        "params": {
            "query": query,
            "department": departments,
            "location": locations if locations else [{"country": "USA", "region": "", "city": location}],
        }
    }
    
    logger.info(f"Scraping {company} jobs with query: {query}, locations: {len(locations)}")
    
    try:
        while True:
            logger.info(f"Fetching page {payload['page']}")
            response = session.post(api_url, json=payload, timeout=30)
            response.raise_for_status()
            
            logger.debug(f"Raw response content (first 500 chars): {response.content[:500]}")
            logger.debug(f"Response headers: {response.headers}")
            
            content_encoding = response.headers.get("Content-Encoding", "").lower()
            if content_encoding == "br":
                logger.debug("Attempting to parse Brotli-encoded response")
                try:
                    data = json.loads(response.content.decode("utf-8"))
                    logger.debug("Parsed raw content as JSON directly")
                except json.JSONDecodeError:
                    logger.debug("Decompressing Brotli-encoded response")
                    try:
                        decompressed = brotli.decompress(response.content)
                        data = json.loads(decompressed.decode("utf-8"))
                        logger.debug(f"Decompressed response (first 500 chars): {decompressed[:500].decode('utf-8')}")
                    except brotli.error as e:
                        logger.error(f"Brotli decompression failed: {e}")
                        raise
            elif content_encoding in ("gzip", "deflate"):
                data = response.json()
            else:
                data = response.json()
            
            if data.get("status") != "success":
                logger.error(f"API returned non-success status: {data.get('status')}")
                break
            
            results = data.get("data", {}).get("results", [])
            total_results = data.get("data", {}).get("totalResults", {}).get("low", 0)
            logger.info(f"Found {len(results) if results is not None else 0} jobs on page {payload['page']}, total expected: {total_results}")
            
            if results is None or not results:
                logger.info(f"No more jobs on page {payload['page']}")
                break
            
            for job in results:
                job_id = job.get("id")
                if not job_id:
                    logger.warning("Job missing ID, skipping")
                    continue
                
                job_title = job.get("title", "Unknown Title")
                job_description = job.get("description", "")
                
                mock_job = {"job_title": job_title, "job_description": job_description}
                if not is_entry_level(mock_job):
                    logger.debug(f"Skipped non-entry-level job: {job_title}")
                    continue
                
                job_url = f"https://www.uber.com/global/en/careers/list/{job_id}/"
                primary_location = job.get("location", {})
                job_location = f"{primary_location.get('city', '')}, {primary_location.get('region', '')}, {primary_location.get('countryName', location)}".strip(", ")
                all_locations = job.get("allLocations", [])
                if any("remote" in loc.get("city", "").lower() or "remote" in loc.get("region", "").lower() for loc in all_locations):
                    job_location = f"Remote - {job_location}"
                
                creation_date = job.get("creationDate", "N/A")
                if creation_date != "N/A":
                    try:
                        posted_datetime = datetime.strptime(creation_date, "%Y-%m-%dT%H:%M:%S.000Z")
                        posted_time = posted_datetime.strftime("%Y-%m-%d")
                    except ValueError:
                        posted_time = "N/A"
                        posted_datetime = datetime.now()
                else:
                    posted_time = "N/A"
                    posted_datetime = datetime.now()
                
                job_entry = create_job_entry(
                    company=company,
                    job_title=job_title,
                    url=job_url,
                    location=job_location,
                    posted_time=posted_time,
                    posted_datetime=posted_datetime
                )
                jobs.append(job_entry)
                logger.debug(f"Added entry-level job: {job_title} at {job_location}")
            
            if len(jobs) >= total_results or (results is not None and len(results) < payload["limit"]):
                logger.info(f"Reached end of jobs (extracted {len(jobs)} of {total_results})")
                break
            
            payload["page"] += 1
        
        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        logger.info(f"Extracted {len(jobs)} entry-level jobs from {company}")
    
    except Exception as e:
        logger.error(f"Error scraping {company}: {e}")
    
    return jobs

SCRAPERS = {
    "Amazon": scrape_amazon,
    "Google": scrape_google,
    "Netflix": scrape_netflix,
    "Intuit": scrape_intuit,
    "Microsoft": scrape_microsoft,
    "Meta": scrape_meta,
    "Apple": scrape_apple,
    "Uber": scrape_uber,
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

        # Configurable sleep time from .env
        try:
            sleep_minutes = int(os.getenv("SLEEP_MINUTES", 30))
            if sleep_minutes <= 0:
                raise ValueError("Sleep minutes must be positive")
        except ValueError as e:
            logger.warning(f"Invalid SLEEP_MINUTES: {e}. Defaulting to 30 minutes.")
            sleep_minutes = 30
        logger.info(f"Waiting {sleep_minutes} minutes before next check...")
        time.sleep(sleep_minutes * 60)

if __name__ == "__main__":
    main()
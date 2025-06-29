import json
import re
import time
from bs4 import BeautifulSoup
import urllib
from config import USER_AGENTS
from utils import clean_text, create_job_entry, is_entry_level
import random
import logging
import brotli
import zstandard as zstd
import requests
from datetime import datetime, timedelta
from setup_environment import setup_environment
from urllib.parse import urlparse, parse_qs, urlencode, urljoin
from company_scraper.base_scraper import BaseScraper  # Import the base class
from cloudscraper import create_scraper
from typing import Dict, List

# Setup environment
setup_environment()

logger = logging.getLogger(__name__)

class AmazonScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        # Parse the base URL to extract query parameters
        parsed_url = urlparse(self.base_url)
        self.query_params = parse_qs(parsed_url.query)
        # Set up API-specific parameters
        self.api_base_url = "https://www.amazon.jobs/en/search.json"
        self.params = {
            "normalized_country_code[]": self.query_params.get("country[]", ["USA"]),
            "radius": self.query_params.get("radius", ["24km"])[0],
            "industry_experience[]": self.query_params.get("industry_experience", ["less_than_1_year"])[0],
            "facets[]": [
                "normalized_country_code", "normalized_state_name", "normalized_city_name",
                "location", "business_category", "category", "schedule_type_id",
                "employee_class", "normalized_location", "job_function_id", "is_manager", "is_intern"
            ],
            "offset": "0",
            "result_limit": self.query_params.get("result_limit", ["10"])[0],
            "sort": self.query_params.get("sort", ["recent"])[0],
            "base_query": self.query_params.get("base_query", ["Software Engineer"])[0],
        }
        if "state[]" in self.query_params:
            self.params["normalized_state_name[]"] = self.query_params["state[]"]

    def scrape(self):
        jobs = []
        logger.info(f"Scraping {self.company} jobs")

        try:
            offset = 0
            result_limit = int(self.params["result_limit"])
            total_hits = None

            while True:
                self.params["offset"] = str(offset)
                logger.info(f"Fetching page at offset {offset}")

                # Use fetch_page from BaseScraper instead of session.get
                response = self.fetch_page(self.api_base_url, params=self.params)
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
                                job_location = first_location.get("normalizedLocation", self.location)
                            else:
                                job_location = locations[0].get("normalizedLocation", self.location)
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.debug(f"Failed to parse location {locations}: {e}")
                            job_location = job.get("location", self.location)
                    else:
                        job_location = job.get("location", self.location)

                    if "remote" in job_location.lower():
                        job_location = f"Remote - {self.location}"

                    posted_date = job.get("posted_date", "N/A")
                    if posted_date != "N/A":
                        try:
                            posted_date_cleaned = " ".join(posted_date.split())
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
                        company=self.company,
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
            logger.info(f"Extracted {len(jobs)} jobs from {self.company}")

        except Exception as e:
            logger.error(f"Error scraping {self.company}: {e}")
            if "response" in locals():
                logger.debug(f"Response: {response.text[:500]}...")

        return jobs


class GoogleScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        # Override headers for Google (HTML scraping)
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-CA,en;q=0.9",
        }
        # Parse the base URL
        self.parsed_url = urlparse(self.base_url)
        self.query_params = parse_qs(self.parsed_url.query)
        self.results_per_page = 20

    def scrape(self):
        jobs = []
        page = 1

        logger.info(f"Scraping {self.company} jobs")

        try:
            while True:
                self.query_params["page"] = [str(page)]
                paginated_url = f"{self.parsed_url.scheme}://{self.parsed_url.netloc}{self.parsed_url.path}?{urlencode(self.query_params, doseq=True)}"
                logger.info(f"Scraping {self.company} page {page}")

                response = self.fetch_page(paginated_url)
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
                    job_location = ", ".join(loc[0] for loc in locations) if locations else self.location

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

                if len(job_items) < self.results_per_page:
                    logger.info(f"End of jobs at page {page} (total: {len(jobs)})")
                    break

                page += 1

            jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
            logger.info(f"Extracted {len(jobs)} jobs from {self.company}")

        except Exception as e:
            logger.error(f"Error scraping {self.company} on page {page}: {e}")
            if "response" in locals():
                logger.debug(f"Response: {response.text[:500]}...")

        return jobs

class NetflixScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        # Override headers for Netflix
        self.headers = {
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
        # Parse the base URL
        parsed_url = urlparse(self.base_url)
        self.query_params = parse_qs(parsed_url.query)
        # Set up API parameters
        self.api_base = "https://explore.jobs.netflix.net/api/apply/v2/jobs"
        self.params = {
            "domain": "netflix.com",
            "query": self.query_params.get("query", [""])[0],
            "location": self.query_params.get("location", [""])[0],
            "Teams": self.query_params.get("Teams", []),
            "Work Type": self.query_params.get("Work Type", []),
            "Region": self.query_params.get("Region", []),
            "sort_by": self.query_params.get("sort_by", ["new"])[0],
            "start": 0,
            "num": 10,
        }
        self.seen_urls = set()

    def scrape(self):
        jobs = []
        logger.info(f"Scraping Netflix jobs for '{self.company}' with query: {self.query_params.get('query', [''])[0]}")

        try:
            while True:
                api_url = f"{self.api_base}?{urlencode(self.params, doseq=True)}"
                response = self.fetch_page(api_url)
                data = response.json()
                positions = data.get("positions", [])
                total_count = data.get("count", 0)
                logger.info(f"Fetched {len(positions)} jobs from page starting at {self.params['start']}, total expected: {total_count}")

                if not positions:
                    logger.info("No more jobs found, ending pagination")
                    break

                for job in positions:
                    job_id = job.get("id")
                    if not job_id:
                        logger.warning("Job missing ID, skipping")
                        continue

                    job_url = f"https://explore.jobs.netflix.net/careers/job/{job_id}"
                    if job_url in self.seen_urls:
                        logger.info(f"Skipping duplicate job with URL {job_url}")
                        continue
                    self.seen_urls.add(job_url)

                    locations = job.get("locations", [])
                    job_location = locations[0] if locations else self.location
                    if "remote" in job_location.lower():
                        job_location = f"Remote - {self.location}"

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
                        company=self.company,
                        job_title=job.get("name", "Unknown Title"),
                        url=job_url,
                        location=job_location,
                        posted_time=posted_time,
                        posted_datetime=posted_datetime
                    )
                    jobs.append(job_entry)
                    logger.debug(f"Added job: {job_entry['job_title']} at {job_entry['location']}")

                if self.params["start"] + len(positions) >= total_count:
                    logger.info(f"Fetched all {total_count} jobs, ending pagination")
                    break

                self.params["start"] += self.params["num"]

        except requests.RequestException as e:
            logger.error(f"Error fetching jobs: {e}")
            if "response" in locals():
                logger.debug(f"Response: {response.text[:500]}...")

        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        logger.info(f"Extracted {len(jobs)} unique jobs from {self.company}")

        return jobs

# ... (Existing imports, AmazonScraper, GoogleScraper, NetflixScraper remain unchanged)

class IntuitScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        # Override headers for Intuit (HTML scraping)
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://jobs.intuit.com/",
        }
        # Parse the base URL
        parsed_url = urlparse(self.base_url)
        path_parts = parsed_url.path.strip("/").split("/")
        self.keyword = path_parts[1] if len(path_parts) > 1 else "Software"
        self.tenant_id = path_parts[2] if len(path_parts) > 2 else "27595"
        self.query_params = parse_qs(parsed_url.query)
        self.api_base_url = f"https://jobs.intuit.com/search-jobs/{self.keyword}/{self.tenant_id}/1"
        # Define US/Canada states for filtering
        self.us_ca_states = {
            "US": ["NY", "GA", "CA", "TX", "FL", "IL", "MA", "WA", "Bay Area", "Greater San Diego & Los Angeles", "Atlanta", "New York", "San Diego", "Los Angeles", "Plano"],
            "CA": ["Ontario", "ON", "BC", "AB", "QC", "Toronto"]
        }

    def scrape(self):
        logger.info(f"Scraping {self.company} jobs")
        all_jobs = []
        page = 1
        expected_total = None
        total_pages = None

        try:
            while True:
                params = {"p": str(page)}
                if "glat" in self.query_params and "glon" in self.query_params:
                    params["glat"] = self.query_params["glat"][0]
                    params["glon"] = self.query_params["glon"][0]

                logger.info(f"Fetching page {page}")
                response = self.fetch_page(self.api_base_url, params=params)
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
                    for regions in self.us_ca_states.values():
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
                        "job_description": ""
                    }
                    if is_entry_level(mock_job):
                        job_entry = create_job_entry(
                            company=self.company,
                            job_title=job["title"],
                            url=job["url"],
                            location=job["location"],
                            posted_time="Unknown",
                            posted_datetime=datetime.now()
                        )
                        jobs.append(job_entry)
                        logger.debug(f"Added entry-level job: {job['title']}")
                    else:
                        logger.debug(f"Skipped non-entry-level position: {job['title']}")

            logger.info(f"Final US/Canada Software Engineering entry-level jobs: {len(jobs)}")

        except Exception as e:
            logger.error(f"Error scraping {self.company}: {e}")
            return []

        return jobs
    
class MicrosoftScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        self.headers = {
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
        self.api_url = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
        self.job_api_url = "https://gcsservices.careers.microsoft.com/search/api/v1/job/{job_id}?lang=en_us"
        parsed_url = urlparse(self.base_url)
        self.params = parse_qs(parsed_url.query)
        self.params["pgSz"] = "20"
        self.seen_job_ids = set()
        self.cutoff_date = datetime.now() - timedelta(days=7)

    def fetch_job_details(self, job_id: str) -> dict:
        """Fetch detailed job information."""
        url = self.job_api_url.format(job_id=job_id)
        try:
            response = self.fetch_page(url)
            data = response.json()
            job_data = data.get("operationResult", {}).get("result")
            if not job_data:
                logger.warning(f"No job data for job {job_id}")
                return {}
            return job_data
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"Failed to fetch details for job {job_id}: {e}")
            return {}

    def scrape(self):
        jobs = []
        page = 1
        total_jobs_encountered = 0

        logger.info(f"Scraping Microsoft jobs (cutoff: {self.cutoff_date.strftime('%Y-%m-%d')})")

        try:
            while True:
                self.params["pg"] = str(page)
                response = self.fetch_page(self.api_url, params=self.params)
                data = response.json()
                job_list = data["operationResult"]["result"].get("jobs", [])
                total_jobs_encountered += len(job_list)

                if not job_list:
                    logger.info(f"No jobs on page {page}, stopping")
                    break

                logger.debug(f"Processing {len(job_list)} jobs on page {page}")

                # Track if we found any jobs within the cutoff on this page
                found_recent_job = False

                for job in job_list:
                    job_id = job.get("jobId")
                    if not job_id or job_id in self.seen_job_ids:
                        continue

                    self.seen_job_ids.add(job_id)
                    job_details = self.fetch_job_details(job_id)
                    if not job_details:
                        continue

                    if job_details.get("jobStatus", "Posted") == "Unposted":
                        logger.debug(f"Skipping closed job {job_id} (closed on {job_details.get('closedDate', 'Unknown')})")
                        continue

                    job_title = job_details.get("title", "Unknown Title")
                    posted_info = job_details.get("posted", {})
                    posted_date = posted_info.get("external", "N/A") if posted_info else "N/A"
                    if posted_date != "N/A":
                        try:
                            posted_datetime = datetime.strptime(posted_date.split("T")[0], "%Y-%m-%d")
                            posted_time = posted_datetime.strftime("%Y-%m-%d")
                            if posted_datetime < self.cutoff_date:
                                logger.debug(f"Skipping job {job_id} - Posted {posted_time}, before cutoff")
                                continue
                            else:
                                found_recent_job = True  # Found a job within cutoff
                        except ValueError:
                            posted_time = "N/A"
                            posted_datetime = datetime.now()
                    else:
                        posted_time = "N/A"
                        posted_datetime = datetime.now()

                    mock_job = {
                        "job_title": job_title,
                        "job_description": job_details.get("description", ""),
                        "minimum_qualifications": job_details.get("qualifications", ""),
                        "preferred_qualifications": job_details.get("responsibilities", "")
                    }

                    if not is_entry_level(mock_job):
                        logger.debug(f"Skipping non-entry-level job: {job_title} (ID: {job_id})")
                        continue

                    job_url = f"https://jobs.careers.microsoft.com/global/en/job/{job_id}/"
                    locations = [loc["description"] for loc in job.get("locations", [])]
                    job_location = ", ".join(locations) if locations else self.location

                    job_entry = create_job_entry(
                        company=self.company,
                        job_title=job_title,
                        url=job_url,
                        location=job_location,
                        posted_time=posted_time,
                        posted_datetime=posted_datetime,
                        min_qual=job_details.get("qualifications", ""),
                        pref_qual=job_details.get("responsibilities", "")
                    )
                    jobs.append(job_entry)
                    logger.info(f"Added job: {job_title} (ID: {job_id})")

                # Stop if no jobs on this page were within cutoff
                if not found_recent_job:
                    logger.info(f"No jobs within cutoff on page {page}, stopping")
                    break

                page += 1
                time.sleep(random.uniform(2, 4))

        except requests.RequestException as e:
            logger.error(f"Error fetching page {page}: {e}")

        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        logger.info(f"Scraped {len(jobs)} entry-level jobs from {total_jobs_encountered} total")
        return jobs


class MetaScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        # Override headers for Meta GraphQL
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-CA,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.metacareers.com",
            "Referer": self.base_url,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-FB-Friendly-Name": "CareersJobSearchResultsDataQuery",
            # X-FB-LSD and X-ASBD-ID will be attempted dynamically below
            "X-ASBD-ID": "359341",
        }
        # Parse the base URL
        parsed_url = urlparse(self.base_url)
        self.query_params = parse_qs(parsed_url.query)
        self.url = "https://www.metacareers.com/graphql"

    def extract_array_param(self, params, param_name):
        pattern = re.compile(rf"^{re.escape(param_name)}\[\d+\]$", re.IGNORECASE)
        values = []
        for key in params:
            if pattern.match(key):
                values.extend(params[key])
        return values

    def fetch_lsd_token(self):
        """Attempt to fetch the X-FB-LSD token from a preliminary request."""
        try:
            prelim_response = self.session.get("https://www.metacareers.com/careers/")
            prelim_response.raise_for_status()
            lsd_match = re.search(r'"LSD",\s*\[\],\s*{\s*"token"\s*:\s*"([^"]+)"', prelim_response.text)
            if lsd_match:
                return lsd_match.group(1)
            logger.warning("Could not extract X-FB-LSD token from preliminary request")
            return "AVrqx8rmwwE"  # Fallback to hardcoded value
        except requests.RequestException as e:
            logger.error(f"Failed to fetch LSD token: {e}")
            return "AVrqx8rmwwE"  # Fallback

    def scrape(self):
        jobs = []
        session = requests.Session()  # Use standalone session like original
        session.headers.update(self.headers)

        teams = self.extract_array_param(self.query_params, 'teams')
        roles = self.extract_array_param(self.query_params, 'roles')
        divisions = self.extract_array_param(self.query_params, 'divisions')
        offices = self.extract_array_param(self.query_params, 'offices')

        logger.info(f"Parsed teams: {teams}")
        logger.info(f"Parsed roles: {roles}")
        logger.info(f"Parsed divisions: {divisions}")
        logger.info(f"Parsed offices: {offices}")

        graphql_vars = {
            "search_input": {
                "q": self.query_params.get('q', [None])[0],
                "divisions": divisions,
                "offices": offices,
                "roles": roles,
                "teams": teams,
                "is_leadership": self.query_params.get('is_leadership', ['false'])[0].lower() == 'true',
                "is_remote_only": self.query_params.get('is_remote_only', ['false'])[0].lower() == 'true',
                "sort_by_new": self.query_params.get('sort_by_new', ['false'])[0].lower() == 'true',
                "results_per_page": None
            }
        }

        # Update headers with dynamic LSD token
        self.headers["X-FB-LSD"] = self.fetch_lsd_token()
        session.headers.update({"X-FB-LSD": self.headers["X-FB-LSD"]})

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
            "lsd": self.headers["X-FB-LSD"],
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
            logger.info(f"Making GraphQL request to {self.url}")
            logger.debug(f"Payload: {payload}")
            response = session.post(self.url, data=payload, timeout=60)
            response.raise_for_status()

            logger.debug(f"Response headers: {response.headers}")
            logger.debug(f"Raw response length: {len(response.content)} bytes")

            if response.headers.get("Content-Encoding") == "zstd":
                logger.debug("Decompressing zstd-encoded response")
                try:
                    decompressed = zstd.decompress(response.content)
                    data_str = decompressed.decode("utf-8")
                    logger.debug(f"Decompressed response (first 500 chars): {data_str[:500]}")
                    data = json.loads(data_str)
                except zstd.ZstdError as e:
                    logger.error(f"Zstd decompression failed: {e}")
                    try:
                        data = json.loads(response.content.decode("utf-8"))
                        logger.debug("Parsed raw content as JSON despite zstd header")
                    except json.JSONDecodeError as je:
                        logger.error(f"Failed to parse raw content as JSON: {je}")
                        return jobs
            else:
                logger.debug(f"Raw response content (first 500 chars): {response.content[:500]}")
                data = response.json()

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
                job_location = ", ".join(job.get("locations", [])) if job.get("locations") else self.location
                if "remote" in job_location.lower():
                    job_location = f"Remote - {self.location}"
                job_entry = create_job_entry(
                    company=self.company,
                    job_title=job.get("title", "Unknown Title"),
                    url=job_url,
                    location=job_location,
                    posted_time="Unknown",
                    posted_datetime=datetime.now()
                )
                all_jobs.append(job_entry)
                logger.debug(f"Added job: {job_entry['job_title']} at {job_entry['location']}")

            logger.info(f"Extracted {len(all_jobs)} total jobs from {self.company}")

            jobs = [job for job in all_jobs if "university" in job["job_title"].lower() or "grad" in job["job_title"].lower()]
            logger.info(f"Filtered to {len(jobs)} University/Grad jobs")

        except Exception as e:
            logger.error(f"Error fetching GraphQL data: {e}")
            if "response" in locals():
                logger.debug(f"Raw response content: {response.content[:500]}")

        return jobs



class AppleScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://jobs.apple.com/en-us/search",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cookie": "geo=US; dslang=US-EN; s_cc=true; at_check=true"
        }
        self.api_url = f"{urllib.parse.urlparse(self.base_url).scheme}://{urllib.parse.urlparse(self.base_url).netloc}{urllib.parse.urlparse(self.base_url).path}"
        self.detail_api_url = "https://jobs.apple.com/api/role/detail/{job_id}?languageCd=en-us"
        self.params = urllib.parse.parse_qs(urllib.parse.urlparse(self.base_url).query)
        if "key" in self.params:
            self.params["key"] = [urllib.parse.unquote(self.params["key"][0])]
        self.params["page"] = ["1"]  # Default, updated in scrape
        self.seen_job_ids = set()
        self.cutoff_date = datetime.now() - timedelta(days=7)
        self.max_retries = 3
        self.retry_delay = 10

    def fetch_job_details(self, job_id: str) -> dict:
        """Fetch detailed job information from Apple's detail API."""
        url = self.detail_api_url.format(job_id=job_id)
        for attempt in range(self.max_retries):
            try:
                response = self.fetch_page(url, timeout=10)
                data = response.json()
                return data if data else {}
            except (requests.RequestException, ValueError) as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Attempt {attempt + 1} failed for job {job_id}: {e}. Retrying in {self.retry_delay}s...")
                    time.sleep(self.retry_delay)
                else:
                    logger.warning(f"Failed to fetch details for job {job_id} after {self.max_retries} attempts: {e}")
                    return {}

    def scrape(self):
        jobs = []
        page = 1
        total_jobs_encountered = 0

        logger.info(f"Scraping {self.company} jobs (cutoff: {self.cutoff_date.strftime('%Y-%m-%d')})")

        try:
            while True:
                self.params["page"] = [str(page)]
                query_string = "&".join(f"{k}={urllib.parse.quote(v[0], safe='')}" for k, v in self.params.items())
                paginated_url = f"{self.api_url}?{query_string}"
                logger.debug(f"Fetching page {page}: {paginated_url}")

                for attempt in range(self.max_retries):
                    try:
                        response = self.fetch_page(paginated_url)
                        match = re.search(r"window\.APP_STATE\s*=\s*({.*?});", response.text, re.DOTALL)
                        if not match:
                            logger.warning(f"No APP_STATE on page {page}, stopping")
                            raise ValueError("No APP_STATE found")
                        app_state = json.loads(match.group(1))
                        job_list = app_state.get("searchResults", [])
                        break
                    except (requests.RequestException, ValueError) as e:
                        if attempt < self.max_retries - 1:
                            logger.warning(f"Attempt {attempt + 1} failed for page {page}: {e}. Retrying in {self.retry_delay}s...")
                            time.sleep(self.retry_delay)
                        else:
                            logger.error(f"Failed page {page} after {self.max_retries} attempts: {e}")
                            if "502" in str(e) or "503" in str(e):
                                logger.info("Rate limit detected, pausing 15min...")
                                time.sleep(900)
                            jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
                            logger.info(f"Scraped {len(jobs)} entry-level jobs from {total_jobs_encountered} total")
                            return jobs

                total_jobs_encountered += len(job_list)
                if not job_list:
                    logger.info(f"No jobs on page {page}, stopping")
                    break

                logger.debug(f"Processing {len(job_list)} jobs on page {page}")
                found_recent_job = False

                for job in job_list:
                    job_id = job.get("id")
                    if not job_id or job_id in self.seen_job_ids:
                        continue
                    self.seen_job_ids.add(job_id)

                    # Note: Apple doesn’t explicitly mark jobs as "closed" in search results,
                    # but we’ll assume active unless detail fetch fails or data suggests otherwise
                    posting_date = job.get("postingDate", "Unknown")
                    if posting_date != "Unknown":
                        try:
                            posted_datetime = datetime.strptime(posting_date, "%b %d, %Y")
                            posted_time = posted_datetime.strftime("%Y-%m-%d")
                            if posted_datetime < self.cutoff_date:
                                logger.debug(f"Skipping job {job_id} - Posted {posted_time}, before cutoff")
                                continue
                            else:
                                found_recent_job = True  # Within cutoff
                        except ValueError:
                            posted_time = "Unknown"
                            posted_datetime = datetime.now()
                    else:
                        posted_time = "Unknown"
                        posted_datetime = datetime.now()

                    job_details = self.fetch_job_details(job_id)
                    if not job_details:
                        continue

                    job_title = job.get("postingTitle", "Unknown Title")
                    mock_job = {
                        "job_title": job_title,
                        "job_description": job.get("jobDescription", ""),
                        "minimum_qualifications": job_details.get("minimumQualifications", ""),
                        "preferred_qualifications": job_details.get("preferredQualifications", "")
                    }

                    if not is_entry_level(mock_job):
                        logger.debug(f"Skipping non-entry-level job: {job_title} (ID: {job_id})")
                        continue

                    job_url = f"https://jobs.apple.com/en-us/details/{job_id}/{job.get('transformedPostingTitle', job_title.lower().replace(' ', '-'))}"
                    locations = job.get("locations", [])
                    job_location = locations[0].get("name", self.location) if locations else self.location
                    if job.get("homeOffice", False):
                        job_location = f"Remote - {job_location}"

                    job_entry = create_job_entry(
                        company=self.company,
                        job_title=job_title,
                        url=job_url,
                        location=job_location,
                        posted_time=posted_time,
                        posted_datetime=posted_datetime,
                        min_qual=job_details.get("minimumQualifications", ""),
                        pref_qual=job_details.get("preferredQualifications", "")
                    )
                    jobs.append(job_entry)
                    logger.info(f"Added job: {job_title} (ID: {job_id})")

                if not found_recent_job:
                    logger.info(f"No jobs within cutoff on page {page}, stopping")
                    break

                page += 1
                time.sleep(random.uniform(1, 3))

        except requests.RequestException as e:
            logger.error(f"Error fetching page {page}: {e}")

        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        logger.info(f"Scraped {len(jobs)} entry-level jobs from {total_jobs_encountered} total")
        return jobs
    

class UberScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        # Override headers to match the working request
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-CA,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://www.uber.com",
            "Referer": self.base_url,  # Should match the careers list page
            "x-csrf-token": "x",  # Using the working token value
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        # Parse the base URL
        parsed_url = urlparse(self.base_url)
        self.query_params = parse_qs(parsed_url.query)
        self.api_url = "https://www.uber.com/api/loadSearchJobsResults?localeCode=en"
        self.query = self.query_params.get("query", ["Software Engineer"])[0]
        self.departments = self.query_params.get("department", ["Engineering"])
        locations_raw = self.query_params.get("location", [])
        self.locations = []
        for loc in locations_raw:
            parts = loc.split("-")
            if len(parts) >= 3:
                country = parts[0]
                region = parts[1]
                city = "-".join(parts[2:])
                self.locations.append({"country": country, "region": region, "city": city})
        if not self.locations:
            self.locations = [{"country": "USA", "region": "", "city": self.location}]

    def initialize_session(self):
        """Initialize the session with a preliminary request to set cookies and context."""
        try:
            prelim_url = "https://www.uber.com/us/en/careers/list/"
            logger.info(f"Initializing session with preliminary request to {prelim_url}")
            response = self.session.get(prelim_url, headers=self.headers, timeout=30)
            response.raise_for_status()
            logger.debug(f"Preliminary response status: {response.status_code}, cookies: {response.cookies}")
        except requests.RequestException as e:
            logger.error(f"Failed to initialize session: {e}")
            # Continue without initialization if it fails, relying on base session

    def scrape(self):
        self.initialize_session()  # Set up session context
        jobs = []

        payload = {
            "limit": 10,
            "page": 0,
            "params": {
                "query": self.query,
                "department": self.departments,
                "location": self.locations,
            }
        }

        logger.info(f"Scraping {self.company} jobs with query: {self.query}, locations: {len(self.locations)}")

        try:
            while True:
                logger.info(f"Fetching page {payload['page']}")
                response = self.session.post(self.api_url, json=payload, timeout=30, headers=self.headers)
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
                    job_location = f"{primary_location.get('city', '')}, {primary_location.get('region', '')}, {primary_location.get('countryName', self.location)}".strip(", ")
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
                        company=self.company,
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

        except Exception as e:
            logger.error(f"Error scraping {self.company}: {e}")
            if "response" in locals():
                logger.debug(f"Response: {response.text[:500]}...")

        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        logger.info(f"Extracted {len(jobs)} entry-level jobs from {self.company}")
        return jobs
    
class TwitchScraper(BaseScraper):
    def __init__(self, company_name: str, base_url: str, location: str = None):
        super().__init__(company_name, base_url, location)
        # Updated to include "engineering" alongside "engineer"
        self.required_keywords = ["software", "engineer", "engineering"]
        self.api_url = "https://www.twitch.tv/jobs/en/careers/index.json"

    def scrape(self) -> List[Dict]:
        logger.info(f"Scraping Twitch jobs from {self.base_url}")
        jobs = []
        response = self.fetch_page(self.api_url)
        if not response:
            return []

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Twitch JSON response: {e}")
            return []

        logger.info(f"Found {len(data)} jobs in response")

        for job in data:
            job_title = job.get("title", "")
            job_description = job.get("content", "")
            job_location = job.get("location", "Unknown")
            office_info = job.get("office", "")
            if office_info:
                job_location += f" ({office_info})"
            link = f"https://www.twitch.tv/jobs/careers/{job.get('id', '')}/"

            # Filter for jobs with required keywords in the title
            keyword_pattern = r'\b(' + '|'.join(self.required_keywords) + r')\b'
            if not re.search(keyword_pattern, clean_text(job_title), re.IGNORECASE):
                logger.debug(f"Skipped job '{job_title}' - does not contain any of {self.required_keywords} in title")
                continue
            
            mock_job = {"job_title": job_title, "job_description": job_description}
            if not is_entry_level(mock_job):
                logger.debug(f"Skipped non-entry-level job: {job_title}")
                continue

            job_entry = create_job_entry(
                company=self.company,
                job_title=job_title,
                url=link,
                location=job_location,
                posted_time="Unknown",  # Update this if API provides posting date
                posted_datetime=datetime.now()
            )
            jobs.append(job_entry)
            logger.debug(f"Added entry-level job: {job_title} at {job_location}")

        logger.info(f"Extracted {len(jobs)} entry-level jobs from Twitch")
        return jobs

class DoorDashScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        self.session = create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False,
                'desktop': True
            },
            delay=10
        )
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-CA,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://careersatdoordash.com/",
            "Cookie": "",
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "cache-control": "max-age=0",
            "priority": "u=0, i"
        }
        parsed_url = urlparse(self.base_url)
        self.query_params = parse_qs(parsed_url.query)
        self.api_base_url = "https://careersatdoordash.com/job-search/"
        self.params = {
            "department": self.query_params.get("department", ["DashMart|Engineering|"])[0],
            "function": self.query_params.get("function", ["Software Engineering|"])[0],
            "keyword": self.query_params.get("keyword", [""])[0],
            "location": self.query_params.get("location", [""])[0],
            "intern": self.query_params.get("intern", ["0"])[0],
            "spage": "1"
        }
        self.seen_link_ids = set()
        self.initialize_session()

    def initialize_session(self):
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                prelim_url = "https://careersatdoordash.com/"
                logger.info(f"Initializing session (attempt {attempt + 1}/{max_attempts})")
                response = self.session.get(prelim_url, headers=self.headers, timeout=30)
                response.raise_for_status()
                self.headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in self.session.cookies.items()])
                self.headers["Referer"] = prelim_url
                logger.debug("Session initialized with fresh cookies")
                return
            except Exception as e:
                logger.error(f"Session init failed (attempt {attempt + 1}): {e}")
                if attempt + 1 == max_attempts:
                    raise Exception("Failed to initialize session after all attempts")
                time.sleep(5)

    def scrape(self):
        jobs = []
        page = 1
        logger.info(f"Scraping {self.company} jobs")

        try:
            while True:
                self.params["spage"] = str(page)
                paginated_url = f"{self.api_base_url}?{urlencode(self.params, doseq=True)}"
                logger.info(f"Fetching page {page}")

                if page > 1:
                    self.headers["Referer"] = f"{self.api_base_url}?{urlencode({**self.params, 'spage': str(page-1)}, doseq=True)}"

                response = self.fetch_page(paginated_url)
                if response.status_code == 403:
                    logger.error(f"403 Forbidden on page {page}")
                    break
                if response.status_code == 200 and "job-item" not in response.text:
                    logger.warning(f"Page {page} loaded but has no job items")
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                job_items = soup.find_all("div", class_="job-item")
                if not job_items:
                    logger.info(f"No jobs found on page {page}")
                    break

                logger.info(f"Found {len(job_items)} jobs on page {page}")
                duplicates = 0

                for item in job_items:
                    title_container = item.find("div", class_="title-container")
                    if not title_container:
                        logger.debug("Skipping job: No title-container")
                        continue

                    link_tag = title_container.find("a", href=True)
                    job_title = link_tag.text.strip() if link_tag else "Unknown Title"
                    job_url = urljoin(self.api_base_url, link_tag["href"]) if link_tag else None
                    if not job_url:
                        logger.debug(f"Skipping job '{job_title}': No URL")
                        continue

                    link_id = job_url.split('/')[-1] if job_url else "N/A"
                    if link_id in self.seen_link_ids:
                        duplicates += 1
                        logger.debug(f"Duplicate job skipped: {job_title} (Link ID: {link_id})")
                        continue
                    self.seen_link_ids.add(link_id)

                    job_id_tag = title_container.find("div", class_="label")
                    job_id = job_id_tag.text.replace("Job ID: ", "").strip() if job_id_tag else "N/A"

                    location_container = item.find("div", class_="location-container")
                    job_location = (
                        location_container.find("div", class_="value-secondary").text.strip()
                        if location_container and location_container.find("div", class_="value-secondary")
                        else self.location
                    )

                    posted_datetime = datetime.now()
                    posted_time = "Unknown"

                    job_entry = create_job_entry(
                        company=self.company,
                        job_title=job_title,
                        url=job_url,
                        location=job_location,
                        posted_time=posted_time,
                        posted_datetime=posted_datetime
                    )
                    jobs.append(job_entry)

                logger.info(f"Added {len(job_items) - duplicates} new jobs from page {page} ({duplicates} duplicates skipped). Total: {len(jobs)}")
                page += 1
                time.sleep(random.uniform(1, 3))

            logger.info(f"Completed scraping. Extracted {len(jobs)} jobs from {self.company}")

        except Exception as e:
            logger.error(f"Scraping failed on page {page}: {e}")
            if "response" in locals():
                logger.debug(f"Response snippet: {response.text[:500]}")

        jobs.sort(key=lambda x: x["posted_datetime"], reverse=True)
        return jobs

class HubspotScraper(BaseScraper):
    def __init__(self, company: str, base_url: str, location: str):
        super().__init__(company, base_url, location)
        # HubSpot uses a GraphQL API
        self.api_url = "https://wtcfns.hubspot.com/careers/graphql"
        self.headers.update({
            "Content-Type": "application/json",
            "Origin": "https://www.hubspot.com",
            "Referer": "https://www.hubspot.com/careers/jobs"
        })
        
        # Extract search query from the URL provided in companies.json
        parsed_url = urlparse(self.base_url)
        self.query_params = parse_qs(parsed_url.query)
        search_query = self.query_params.get("q", [""])[0]

        # Prepare the GraphQL payload
        self.payload = {
            "operationName": "Jobs",
            "query": """
                query Jobs($departmentIds: [Int], $officeIds: [Int], $languages: [String], $roleTypes: [String], $searchQuery: String) {
                    jobs(departmentIds: $departmentIds, officeIds: $officeIds, languages: $languages, roleTypes: $roleTypes, searchQuery: $searchQuery) {
                        id
                        title
                        department { name id }
                        office { id location }
                        location { name }
                    }
                }
            """,
            "variables": {
                "departmentIds": [],
                "officeIds": [],
                "languages": [],
                "roleTypes": [],
                "searchQuery": search_query
            }
        }

    def scrape(self):
        jobs = []
        search_query = self.payload["variables"]["searchQuery"]
        logger.info(f"Scraping {self.company} jobs with query: '{search_query}'")

        try:
            # Unlike other scrapers, HubSpot's GraphQL endpoint returns all results at once.
            # There is no pagination needed.
            response = self.session.post(self.api_url, headers=self.headers, json=self.payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            job_list = data.get("data", {}).get("jobs", [])

            if not job_list:
                logger.info("No jobs found for the specified query.")
                return jobs

            logger.info(f"Found {len(job_list)} total jobs from API response.")

            for job in job_list:
                job_id = job.get("id")
                if not job_id:
                    logger.warning("Job missing ID, skipping.")
                    continue

                job_title = job.get("title", "Unknown Title")
                
                # Use the helper function to check for entry-level keywords
                mock_job = {"job_title": job_title, "job_description": ""}
                if not is_entry_level(mock_job):
                    logger.debug(f"Skipping non-entry-level job: {job_title}")
                    continue

                # The careers site uses this URL structure
                job_url = f"https://www.hubspot.com/careers/jobs/{job_id}"
                
                # The 'office' object seems to have the most descriptive location
                job_location = job.get("office", {}).get("location", self.location)

                # The API does not provide a posting date, so we mark it as unknown
                posted_time = "Unknown"
                posted_datetime = datetime.now()

                job_entry = create_job_entry(
                    company=self.company,
                    job_title=job_title,
                    url=job_url,
                    location=job_location,
                    posted_time=posted_time,
                    posted_datetime=posted_datetime
                )
                jobs.append(job_entry)
                logger.debug(f"Added entry-level job: {job_title} at {job_location}")

        except requests.RequestException as e:
            logger.error(f"Failed to fetch jobs from HubSpot API: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during HubSpot scraping: {e}")
            if 'response' in locals():
                logger.debug(f"Response text: {response.text[:500]}")

        logger.info(f"Extracted {len(jobs)} entry-level jobs from {self.company}")
        return jobs


SCRAPERS = {
    "Amazon": AmazonScraper,
    "Google": GoogleScraper,
    "Netflix": NetflixScraper,
    "Intuit": IntuitScraper,
    "Microsoft": MicrosoftScraper,
    "Meta": MetaScraper,
    "Apple": AppleScraper,
    "Uber": UberScraper,
    "Twitch": TwitchScraper,
    "DoorDash": DoorDashScraper,
    "HubSpot": HubspotScraper
}
from config import COMPANIES_FILE, SEEN_JOBS_FILE, SLEEP_MINUTES
from company_scraper.scrapers import SCRAPERS
from utils import load_companies, load_seen_jobs, save_seen_jobs, send_email
from setup_environment import setup_environment
import logging
import time

# Setup environment
setup_environment()
logger = logging.getLogger(__name__)

def main():
    companies = load_companies(COMPANIES_FILE)
    seen_jobs = load_seen_jobs(SEEN_JOBS_FILE)

    while True:
        logger.info("Starting new job check cycle...")
        for company in companies:
            company_name = company["Company"]
            url = company["URL"]
            location = company["Location"]

            logger.info(" " * 50)
            logger.info("-" * 50)
            logger.info(f"SEARCHING {company_name.upper()}...")
            logger.info("-" * 50)

            scraper_class = SCRAPERS.get(company_name)
            if not scraper_class:
                logger.warning(f"No scraper defined for {company_name}")
                continue

            # Instantiate the scraper class and call scrape
            scraper = scraper_class(company_name, url, location)
            new_jobs = scraper.scrape()
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

        save_seen_jobs(seen_jobs, new_jobs_count, SEEN_JOBS_FILE)

        if SLEEP_MINUTES <= 0:
            logger.warning("Sleep minutes must be positive, defaulting to 30.")
            sleep_minutes = 30
        else:
            sleep_minutes = SLEEP_MINUTES
        logger.info(f"Waiting {sleep_minutes} minutes before next check...")
        time.sleep(sleep_minutes * 60)

if __name__ == "__main__":
    main()
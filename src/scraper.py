import requests
from bs4 import BeautifulSoup
import json
import time
from discord_webhook import DiscordWebhook
from dotenv import load_dotenv
import os
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Set up logging
logging.basicConfig(level=logging.INFO, filename="scraper.log", filemode="a",
                    format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables from .env
load_dotenv()

# Configuration
CONFIG = {
    "linkedin": {
        "urls": [
            "https://www.linkedin.com/jobs/search/?f_E=2&f_TPR=r86400&geoId=101174742&keywords=software%20engineer&refresh=true&spellCorrectionEnabled=true",  # Canada
            "https://www.linkedin.com/jobs/search/?f_E=2&f_TPR=r86400&geoId=103644278&keywords=software%20engineer&refresh=true&spellCorrectionEnabled=true"   # US
        ],
        "scrape_function": "scrape_linkedin"
    },
    "github": {
        "urls": [
            "https://github.com/SimplifyJobs/New-Grad-Positions"
        ],
        "scrape_function": "scrape_github"
    },
    "simplify": {
        "urls": [
            "https://simplify.jobs/jobs?query=Software%20Engineer&state=Canada&points=83.13505%3B-52.619409%3B41.729668%3B-141.002742&country=Canada&experience=Entry%20Level%2FNew%20Grad&mostRecent=true&jobId=bfa077a1-30c4-48bd-b603-9e6feb1a2077",  # Canada
            "https://simplify.jobs/jobs?query=Software%20Engineer&state=United%20States&points=71.5388001%3B-66.885417%3B18.7763%3B-180&country=United%20States&experience=Entry%20Level%2FNew%20Grad&mostRecent=true&jobId=eb917aaa-747c-4cde-9e28-003d8c49fb5e",  # US
            "https://simplify.jobs/jobs?query=Software%20Engineer&state=Remote%20in%20Canada&experience=Entry%20Level%2FNew%20Grad&mostRecent=true&jobId=8af89527-71b7-4064-b5a4-ae764f672c54",  # Remote Canada
            "https://simplify.jobs/jobs?query=Software%20Engineer&state=Remote%20in%20USA&experience=Entry%20Level%2FNew%20Grad&mostRecent=true&jobId=1a00012f-0e25-4386-a7ce-4ecebf8fa406"  # Remote US
        ],
        "scrape_function": "scrape_simplify"
    }
}
SEEN_JOBS_FILE = "data/seen_jobs.json"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
DEBUG_DIR = "debug"

def load_seen_jobs():
    """Load previously seen job links from file."""
    try:
        with open(SEEN_JOBS_FILE, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen_jobs(seen_jobs):
    """Save seen job links to file."""
    os.makedirs(os.path.dirname(SEEN_JOBS_FILE), exist_ok=True)
    with open(SEEN_JOBS_FILE, 'w') as f:
        json.dump(list(seen_jobs), f)

def scrape_linkedin(url):
    """Scrape job listings from LinkedIn."""
    logging.info(f"Scraping LinkedIn URL: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        logging.info(f"LinkedIn response status: {response.status_code}, length: {len(response.text)}")
        
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, f"linkedin_{url.split('geoId=')[1].split('&')[0]}.html"), "w", encoding="utf-8") as f:
            f.write(response.text)
    except requests.RequestException as e:
        logging.error(f"Failed to fetch LinkedIn URL {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    job_cards = soup.find_all('div', class_='job-search-card')
    logging.info(f"Found {len(job_cards)} LinkedIn job cards")
    
    jobs = []
    for card in job_cards:
        title_elem = card.find('h3', class_='base-search-card__title')
        title = title_elem.text.strip() if title_elem else "Unknown Title"
        
        company_elem = card.find('h4', class_='base-search-card__subtitle')
        company = company_elem.text.strip() if company_elem else "Unknown Company"
        
        location_elem = card.find('span', class_='job-search-card__location')
        location = location_elem.text.strip() if location_elem else "Unknown Location"
        
        time_elem = card.find('time', class_='job-search-card__listdate--new')
        time_posted = time_elem.text.strip() if time_elem else "Unknown Time"
        
        link_elem = card.find('a', class_='base-card__full-link')
        link = link_elem['href'] if link_elem and link_elem.get('href') else "No Link Available"
        
        jobs.append({
            'title': title,
            'company': company,
            'location': location,
            'time_posted': time_posted,
            'link': link,
            'source': 'LinkedIn'
        })
    
    return jobs

def scrape_github(url):
    """Scrape job listings from GitHub SimplifyJobs/New-Grad-Positions README, filtering out locked links."""
    logging.info(f"Scraping GitHub URL: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        logging.info(f"GitHub response status: {response.status_code}, length: {len(response.text)}")
        
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, "github_new_grad_positions.html"), "w", encoding="utf-8") as f:
            f.write(response.text)
    except requests.RequestException as e:
        logging.error(f"Failed to fetch GitHub URL {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    readme_article = soup.find('article', class_='markdown-body') or soup.find('div', id='readme')
    if not readme_article:
        logging.info("No README article or div#readme found in GitHub page")
        return []
    
    table = readme_article.find('table')
    if not table:
        logging.info("No table found in GitHub README")
        return []
    
    jobs = []
    rows = table.find('tbody').find_all('tr') if table.find('tbody') else table.find_all('tr')[1:]  # Skip header
    logging.info(f"Found {len(rows)} GitHub job rows")
    
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 5:
            logging.info(f"Skipping row with insufficient columns: {row.prettify()}")
            continue
        
        company_elem = cols[0].find('a') or cols[0]
        company = company_elem.text.strip() if company_elem else "Unknown Company"
        
        title = cols[1].text.strip() if cols[1].text.strip() else "Unknown Title"
        
        location = cols[2].text.strip() if cols[2].text.strip() else "Unknown Location"
        
        link_elem = cols[3].find('a', href=True)
        link_text = cols[3].text.strip()
        if not link_elem or 'utm_source=Simplify' not in link_elem['href'] or link_text == '🔒':
            logging.info(f"Skipping row due to no valid link or locked: {row.prettify()}")
            continue
        link = link_elem['href']
        
        time_posted = cols[4].text.strip() if cols[4].text.strip() else "Unknown Time"
        
        jobs.append({
            'title': title,
            'company': company,
            'location': location,
            'time_posted': time_posted,
            'link': link,
            'source': 'GitHub'
        })
    
    logging.info(f"Filtered to {len(jobs)} GitHub jobs with valid links")
    return jobs

def scrape_simplify(url):
    """Scrape job listings from Simplify.jobs by clicking each card and parsing detail pages."""
    logging.info(f"Scraping Simplify URL: {url}")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--log-level=3")
    
    service = Service(ChromeDriverManager().install())
    service.log_path = "nul"  # Suppress ChromeDriver output
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    jobs = []
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 15)  # Increased to 15s
        wait.until(EC.presence_of_element_located((By.XPATH, "//div[@data-testid='job-card']")))
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        job_cards = soup.find_all('div', attrs={'data-testid': 'job-card'})
        logging.info(f"Found {len(job_cards)} Simplify job cards")
        
        if not job_cards:
            logging.info("No job cards found, dumping first 2000 chars of HTML: " + soup.prettify()[:2000])
            driver.quit()
            return []
        
        for index in range(len(job_cards)):
            try:
                card_buttons = driver.find_elements(By.XPATH, "//button[div[@data-testid='job-card']]")
                logging.info(f"Found {len(card_buttons)} clickable job card buttons on iteration {index + 1}")
                if index >= len(card_buttons):
                    logging.warning(f"Index {index} exceeds available buttons ({len(card_buttons)})")
                    break
                
                button = card_buttons[index]
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", button)
                wait.until(EC.url_changes(url))
                job_link = driver.current_url
                logging.info(f"Clicked job card {index + 1}, got URL: {job_link}")
                
                wait.until(EC.presence_of_element_located((By.XPATH, "//div[@data-testid='details-view']")))
                detail_soup = BeautifulSoup(driver.page_source, 'html.parser')
                detail_card = detail_soup.find('div', attrs={'data-testid': 'details-view'})
                
                if not detail_card:
                    logging.error(f"No details-view found for job card {index + 1}")
                    continue
                
                title_elem = detail_card.find('h1')
                title = title_elem.text.strip() if title_elem else "Unknown Title"
                
                company_elem = detail_card.find('h2')
                company = company_elem.text.strip() if company_elem else "Unknown Company"
                
                location_elem = detail_card.find('svg', viewBox="0 0 24 24")
                if location_elem:
                    location_p = location_elem.find_next('p', class_='text-sm font-bold')
                    location = location_p.text.strip().split('<')[0].strip() if location_p else "Unknown Location"
                else:
                    location = "Unknown Location"
                
                time_elem = detail_card.find('p', string=lambda s: s and "Confirmed live" in s)
                time_posted = time_elem.text.strip() if time_elem else "Unknown Time"
                
                job_key = f"{title}_{company}_{location}"
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': location,
                    'time_posted': time_posted,
                    'link': job_link,
                    'source': 'Simplify',
                    'key': job_key
                })
                
                back_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'flex items-center gap-2')]")))
                driver.execute_script("arguments[0].click();", back_button)
                wait.until(EC.presence_of_element_located((By.XPATH, "//div[@data-testid='job-card']")))
                time.sleep(1)
                
            except Exception as e:
                import traceback
                logging.error(f"Failed to process job card {index + 1}: {str(e)}\n{traceback.format_exc()}")
                driver.get(url)
                wait.until(EC.presence_of_element_located((By.XPATH, "//div[@data-testid='job-card']")))
                continue
        
        os.makedirs(DEBUG_DIR, exist_ok=True)
        region = url.split('state=')[1].split('&')[0].replace('%20', '_')
        with open(os.path.join(DEBUG_DIR, f"simplify_{region}.html"), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        
        logging.info(f"Scraped {len(jobs)} Simplify jobs")
        return jobs
    
    except Exception as e:
        import traceback
        logging.error(f"Failed to fetch Simplify URL {url} with Selenium: {str(e)}\n{traceback.format_exc()}")
        return jobs
    finally:
        driver.quit()

def send_discord_notification(job):
    """Send a formatted notification to Discord."""
    message = (
        f"**New Job Found ({job['source']})**\n"
        f"**Title:** {job['title']}\n"
        f"**Company:** {job['company']}\n"
        f"**Location:** {job['location']}\n"
        f"**Posted:** {job['time_posted']}\n"
        f"**Link:** {job['link']}"
    )
    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL, content=message)
    response = webhook.execute()
    if response.status_code not in [200, 204]:
        print(f"Failed to send Discord notification: {response.status_code} - {response.text}")
    time.sleep(2)

def main():
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL not found in .env")
        return
    
    seen_jobs = load_seen_jobs()
    print(f"Loaded {len(seen_jobs)} seen jobs")
    while True:
        print("Checking for new jobs...")
        all_jobs = []
        for source, details in CONFIG.items():
            scrape_func = globals()[details['scrape_function']]
            for url in details['urls']:
                jobs = scrape_func(url)
                all_jobs.extend(jobs)
                logging.info(f"Scraped {len(jobs)} jobs from {source} URL: {url}")
                print(f"Scraped {len(jobs)} jobs from {source} URL: {url}")
        
        if not all_jobs:
            print("No jobs found in this run")
        else:
            # Send separator with current date and time
            timestamp = time.strftime("%b %d, %Y %I:%M %p", time.localtime())
            separator = f"-----------------------------\n**NEW JOB ALERT - {timestamp}**\n______________________________"
            webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL, content=separator)
            webhook.execute()
            time.sleep(2)  # Delay after separator
        
        for job in all_jobs:
            job_id = job.get('key', job['link'])
            if job_id not in seen_jobs:
                print(f"New job found ({job['source']}): {job['title']} - {job['company']} - {job['location']} - {job['time_posted']} - {job['link']}")
                logging.info(f"New job found ({job['source']}): {job['title']} - {job['company']} - {job['location']} - {job['time_posted']} - {job['link']}")
                send_discord_notification(job)
                seen_jobs.add(job_id)
            else:
                logging.info(f"Job already seen ({job['source']}): {job['title']} - {job['link']}")
        save_seen_jobs(seen_jobs)
        print("Finished checking, waiting 2 hours...")
        time.sleep(7200)

if __name__ == "__main__":
    main()
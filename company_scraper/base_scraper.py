from abc import ABC, abstractmethod
from requests_ratelimiter import LimiterSession
from config import USER_AGENTS
import random
import logging
import requests

logger = logging.getLogger(__name__)

class BaseScraper(ABC):
    def __init__(self, company: str, base_url: str, location: str):
        """Initialize the scraper with company details."""
        self.company = company
        self.base_url = base_url
        self.location = location
        self.session = LimiterSession(per_second=0.5)
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-CA,en;q=0.9",
            "Referer": self.base_url,
        }

    def fetch_page(self, url: str, params: dict = None, timeout: int = 30) -> requests.Response:
        """Fetch a page with error handling and logging."""
        try:
            logger.info(f"Fetching page: {url} with params {params}")
            response = self.session.get(url, headers=self.headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            raise

    def paginate(self, start: int = 0, step: int = 10):
        """Generator for pagination (e.g., offset-based)."""
        while True:
            yield start
            start += step

    @abstractmethod
    def scrape(self) -> list:
        """Abstract method that must be implemented by child classes."""
        pass
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Centralized logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

def setup_environment():
    # Load environment variables (optional, enable if needed)
    load_dotenv()
    logger.info("Environment setup complete.")
    # Add other setup logic here (e.g., API keys, paths) if needed
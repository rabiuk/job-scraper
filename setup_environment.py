import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def setup_environment():
    # Load environment variables (optional, enable if needed)
    load_dotenv()

    logging.basicConfig(
    level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Suppress urllib3 debug logs
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)  # Optional: also suppress requests logs
    logger = logging.getLogger(__name__)

    logger.info("Environment setup complete.")
    # Add other setup logic here (e.g., API keys, paths) if needed
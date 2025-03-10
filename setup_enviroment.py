import os
import sys
import logging
from dotenv import load_dotenv


logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

def setup_environment():
    """
    Load environment variables, set up PYTHONPATH, and configure logging.
    """
    # Load environment variables from .env file
    load_dotenv()

    # Debug: Print the loaded PYTHONPATH
    pythonpath = os.getenv("PYTHONPATH")
    logger.info(f"Loaded PYTHONPATH: {pythonpath}")


    # Ensure the project root is in the PYTHONPATH
    if pythonpath:
        sys.path.append(pythonpath)
    else:
        raise EnvironmentError("PYTHONPATH is not set in the environment variables.")

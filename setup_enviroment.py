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
    Load environment variables from .env, set up PYTHONPATH, and configure logging.
    """
    # Load environment variables from .env file
    load_dotenv()

    # Get the project root from the .env file
    project_root = os.getenv("PROJECT_ROOT")
    
    # Check if PROJECT_ROOT was loaded successfully
    if not project_root:
        raise EnvironmentError(
            "PROJECT_ROOT not found in .env file. Please set it in your .env file."
        )

    # Add project_root to sys.path if it's not already there
    if project_root not in sys.path:
        sys.path.append(project_root)
        logger.info(f"Added {project_root} to PYTHONPATH")
    else:
        logger.info(f"{project_root} already in PYTHONPATH")

    # Set PYTHONPATH environment variable for subprocesses
    os.environ["PYTHONPATH"] = project_root
    
    # Verify the path exists
    if not os.path.exists(project_root):
        raise EnvironmentError(f"Project root directory does not exist: {project_root}")

    # Debug: Log the current PYTHONPATH
    logger.info(f"Current PYTHONPATH: {os.environ.get('PYTHONPATH')}")

# Run the setup
if __name__ == "__main__":
    setup_environment()
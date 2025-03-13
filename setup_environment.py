# job_scraper/setup_environment.py
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

def setup_environment():
    """Load environment variables and configure paths."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        logger.info(f"Loaded .env from {env_path}")
    else:
        logger.warning(f"No .env file found at {env_path}")

    env_project_root = os.getenv("PROJECT_ROOT")
    if env_project_root and os.path.exists(env_project_root):
        project_root = env_project_root
        logger.info(f"Using PROJECT_ROOT from .env: {project_root}")
    else:
        logger.info(f"Using calculated project root: {project_root}")

    if not os.path.exists(project_root):
        raise EnvironmentError(f"Project root directory does not exist: {project_root}")

    # No sys.path manipulation needed; package installation handles it
    current_pythonpath = os.environ.get("PYTHONPATH", "")
    if project_root not in current_pythonpath.split(os.pathsep):
        os.environ["PYTHONPATH"] = f"{project_root}{os.pathsep}{current_pythonpath}".strip(os.pathsep)
        logger.info(f"Updated PYTHONPATH: {os.environ['PYTHONPATH']}")
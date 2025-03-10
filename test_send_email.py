from setup_enviroment import setup_environment
from utils import send_email

# Set up environment
setup_environment()

def main():

    # Create dummy job
    dummy_job = {
        'company': 'Test Company',
        'job_title': 'Software Engineer',
        'location': 'Bay Area, San Francisco',
        'url': 'https://test.company.com/20198725/software-engineer',
        'found_at': '2025-03-09 03:42:12',
        'posted_time': '2025-03-09'
    }

    print("-" * 50)
    print("Testing Email")
    print("-" * 50)
    send_email(dummy_job)

if __name__ == "__main__":
    main()

import os
from discord_webhook import DiscordWebhook
from setup_environment import setup_environment

# Setup environment
setup_environment()

url = os.getenv("LINKEDIN_WEBHOOK_URL")
print(f"Using URL: {url}")
webhook = DiscordWebhook(url=url, content="Test message")
response = webhook.execute()
print(f"Response: {response.status_code} - {response.text}")
from discord_webhook import DiscordWebhook
import os
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DISCORD_WEBHOOK_URL")
print(f"Using URL: {url}")
webhook = DiscordWebhook(url=url, content="Test message")
response = webhook.execute()
print(f"Response: {response.status_code} - {response.text}")
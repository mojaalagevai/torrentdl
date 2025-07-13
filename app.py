from flask import Flask
import threading
import time
import requests
from collections import deque
from datetime import datetime

app = Flask(__name__)

# Thread-safe storage for ping results (max 10)
ping_results = deque(maxlen=10)
ping_lock = threading.Lock()

def ping_server():
    url = "http://localhost:7860"
    while True:
        try:
            start_time = time.time()
            response = requests.get(url, timeout=2)
            status = "Success" if response.status_code == 200 else "Failed"
            latency = (time.time() - start_time) * 1000
        except:
            status = "Failed"
            latency = 0
        with ping_lock:
            ping_results.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "status": status,
                "latency": f"{latency:.0f}ms" if latency > 0 else "-"
            })
        time.sleep(600)

@app.route('/')
def home():
    with ping_lock:
        results = list(ping_results)
    html = """<html><head><title>Status</title><style>
        body{font-family:Arial;}
        table{border-collapse:collapse;width:500px;margin:10px;}
        th,td{border:1px solid #ddd;padding:4px;}
        th{background:#f0f0f0;}
        .success{color:green;}
        .failed{color:red;}
    </style></head><body>
    <h3>Server Status (Last 10 Pings)</h3>
    <p>Running</p>
    <table><tr><th>Time</th><th>Status</th><th>Latency</th></tr>"""
    for r in reversed(results):
        html += f"<tr><td>{r['time']}</td><td class='{r['status'].lower()}'>{r['status']}</td><td>{r['latency']}</td></tr>"
    html += "</table></body></html>"
    return html

# Run Flask and ping in separate threads
def run_flask():
    app.run(host='0.0.0.0', port=7860)

threading.Thread(target=ping_server, daemon=True).start()
threading.Thread(target=run_flask, daemon=True).start()


import json
import asyncio
import re
import uuid
import time
import requests
from telethon import TelegramClient, events

# Bot configuration
BOT_TOKEN = "7595286719:AAGyYSgfyQf3rIJL9SrJdshJT-iRYnakkKc"
API_ID = 29202599  # Replace with your API_ID from my.telegram.org
API_HASH = "2581d59249312f29258f7413cf005141"  # Replace with your API_HASH from my.telegram.org
ALLOWED_USERS = [7014665654, 5631774748]
ADMIN_ID = 7384283560

# TeraBox URL regex
TERABOX_REGEX = (
    r"https?://(?:www\.)?("
    r"teraboxlink\.com|"
    r"teraboxapp\.com|"
    r"1024terabox\.com|"
    r"terabox\.com|"
    r"terasharelink\.com|"
    r"terafileshare\.com|"
    r"4funbox\.co|"
    r"teraboxapp\.to|"
    r"terabox\.app"
    r")/s/[\w-]+$"
)

# In-memory queue for requests
request_queue = []
queue_lock = asyncio.Lock()
task_queue = asyncio.Queue()

def add_to_queue(user_id, url):
    """Add a request to the in-memory queue."""
    request_id = str(uuid.uuid4())
    request_queue.append({"user_id": user_id, "url": url, "request_id": request_id})
    return request_id

async def remove_from_queue(request_id):
    """Remove a request from the queue by request_id."""
    global request_queue
    async with queue_lock:
        request_queue = [req for req in request_queue if req["request_id"] != request_id]

def parse_expiration_time(direct_link):
    """Parse expiration time from direct link, if available."""
    try:
        expires = re.search(r"expires=(\d+h)", direct_link)
        if expires:
            return expires.group(1)
        return "unknown duration"
    except (AttributeError, TypeError):
        return "unknown duration"

def get_direct_link(terabox_url):
    """Fetch direct download link from TeraBox API."""
    api_url = f"https://teraboxapi.jammesop007.workers.dev/marufking?link={terabox_url}"
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        direct_link = response.text.strip()
        if direct_link.startswith("https://d.terabox.app/file/"):
            return direct_link
        return None
    except (requests.RequestException, ValueError):
        return None

async def process_url(client: TelegramClient, chat_id: int, user_id: int, url: str, request_id: str):
    """Process a single URL with retries."""
    start_time = time.time()
    direct_link = None
    for attempt in range(3):  # Retry up to 3 times
        direct_link = await asyncio.get_event_loop().run_in_executor(None, get_direct_link, url)
        if direct_link:
            break
        if attempt < 2:
            await asyncio.sleep(30)  # 30-second cooldown

    processing_time = time.time() - start_time
    if direct_link:
        expiration = parse_expiration_time(direct_link)
        formatted_response = (
            f"📥 Direct download link for {url}:\n"
            f"`{direct_link}`\n\n"
            f"Expires in: {expiration}\n"
            f"Processing time: {processing_time:.2f} seconds\n"
            f"Click to copy and paste in your browser!"
        )
        await client.send_message(chat_id, formatted_response, parse_mode="md")
    else:
        await client.send_message(
            chat_id,
            f"Failed to generate direct link for {url}. Skipped due to API error. Processing time: {processing_time:.2f} seconds"
        )

    # Remove request from queue
    await remove_from_queue(request_id)

async def url_processor(client: TelegramClient):
    """Worker to process URLs from the task queue."""
    while True:
        try:
            chat_id, user_id, url, request_id = await task_queue.get()
            await process_url(client, chat_id, user_id, url, request_id)
            task_queue.task_done()
        except asyncio.CancelledError:
            break

def validate_url(url):
    """Validate TeraBox URL and provide detailed feedback."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return "URL must start with http:// or https://"
    if not re.match(TERABOX_REGEX, url):
        if "/s/" not in url:
            return "URL is missing the '/s/' path."
        if not any(domain in url for domain in [
            "teraboxlink.com", "teraboxapp.com", "1024terabox.com", "terabox.com",
            "terasharelink.com", "terafileshare.com", "4funbox.co", "teraboxapp.to", "terabox.app"
        ]):
            return "Invalid TeraBox domain. Use a supported domain (e.g., teraboxapp.com, 1024terabox.com)."
        return "Invalid URL format. Ensure it ends with an alphanumeric ID."
    return None

async def main():
    """Run the bot with Telethon."""
    # Initialize Telethon client with API_ID and API_HASH
    client = TelegramClient('bot', api_id=API_ID, api_hash=API_HASH)

    # Start the URL processor
    processor_task = asyncio.create_task(url_processor(client))

    # Command handlers
    @client.on(events.NewMessage(pattern='/start'))
    async def start(event):
        """Handle /start command and display bot features."""
        features = (
            "Welcome to the TeraBox Downloader Bot! 📥\n\n"
            "Features:\n"
            "- Convert TeraBox links to direct download links.\n"
            "- Process multiple links at once (send one per line or separated by spaces).\n"
            "- Show link expiration time (e.g., 8 hours).\n"
            "- Show processing time for each link.\n"
            "- Detailed feedback for invalid URLs.\n"
            "- Queue system with progress updates (e.g., 'You are #2 in the queue').\n"
            "- Admin commands to manage allowed users, check status, and view queue.\n"
            "- Failsafe operation: skips errors and retries API calls with a 30-second cooldown.\n\n"
            "Send one or more TeraBox links to start downloading!\n"
            "Use /help for usage instructions."
        )
        await event.reply(features)

    @client.on(events.NewMessage(pattern='/help'))
    async def help_command(event):
        """Handle /help command to show usage instructions."""
        usage = (
            "Usage Instructions:\n\n"
            "1. Send one or more TeraBox links (e.g., https://teraboxapp.com/s/1oAWUspZcX8YmkimPz2M88g).\n"
            "   - Use one link per line or separate by spaces for multiple links.\n"
            "2. If authorized, the bot will process each link and return a direct download link in a copyable format.\n"
            "3. Links are validated, and you'll get feedback if a URL is invalid.\n"
            "4. You'll be informed of your position in the queue for each link.\n"
            "5. Direct links include expiration info (e.g., 'Expires in: 8h') and processing time.\n\n"
            "Admin Commands (for admin only):\n"
            "- /adduser <user_id>: Add a user to the allowed list.\n"
            "- /removeuser <user_id>: Remove a user from the allowed list.\n"
            "- /users: View allowed users with details.\n"
            "- /status: Check bot and API status.\n"
            "- /queue: View the current queue in JSON format."
        )
        await event.reply(usage)

    @client.on(events.NewMessage(pattern='/adduser'))
    async def add_user(event):
        """Admin command to add a user to ALLOWED_USERS."""
        if event.sender_id != ADMIN_ID:
            await event.reply("Only the admin can use this command.")
            return
        try:
            user_id = int(event.message.text.split()[1])
            if user_id not in ALLOWED_USERS:
                ALLOWED_USERS.append(user_id)
                await event.reply(f"User {user_id} added to allowed users.")
            else:
                await event.reply(f"User {user_id} is already allowed.")
        except (IndexError, ValueError):
            await event.reply("Usage: /adduser <user_id>")

    @client.on(events.NewMessage(pattern='/removeuser'))
    async def remove_user(event):
        """Admin command to remove a user from ALLOWED_USERS."""
        if event.sender_id != ADMIN_ID:
            await event.reply("Only the admin can use this command.")
            return
        try:
            user_id = int(event.message.text.split()[1])
            if user_id == ADMIN_ID:
                await event.reply("Cannot remove the admin from allowed users.")
                return
            if user_id in ALLOWED_USERS:
                ALLOWED_USERS.remove(user_id)
                await event.reply(f"User {user_id} removed from allowed users.")
            else:
                await event.reply(f"User {user_id} is not in the allowed list.")
        except (IndexError, ValueError):
            await event.reply("Usage: /removeuser <user_id>")

    @client.on(events.NewMessage(pattern='/users'))
    async def users(event):
        """Admin command to list allowed users with details."""
        if event.sender_id != ADMIN_ID:
            await event.reply("Only the admin can use this command.")
            return
        if not ALLOWED_USERS:
            await event.reply("No allowed users.")
            return
        user_list = []
        for user_id in ALLOWED_USERS:
            try:
                user = await client.get_entity(user_id)
                username = f"@{user.username}" if user.username else "N/A"
                first_name = user.first_name or "N/A"
                user_list.append(f"ID: {user_id}, Username: {username}, First Name: {first_name}")
            except Exception:
                user_list.append(f"ID: {user_id}, Username: N/A, First Name: N/A (User info unavailable)")
        response = "Allowed Users:\n" + "\n".join(user_list)
        await event.reply(response)

    @client.on(events.NewMessage(pattern='/status'))
    async def status(event):
        """Admin command to check bot and API status."""
        if event.sender_id != ADMIN_ID:
            await event.reply("Only the admin can use this command.")
            return
        try:
            test_url = "https://teraboxapp.com/s/1oAWUspZcX8YmkimPz2M88g"
            direct_link = await asyncio.get_event_loop().run_in_executor(None, get_direct_link, test_url)
            status = "Bot is running.\n" + ("API is operational." if direct_link else "API is down.")
            await event.reply(status)
        except Exception:
            await event.reply("Bot is running, but API check failed.")

    @client.on(events.NewMessage(pattern='/queue'))
    async def queue(event):
        """Admin command to show current queue in JSON format."""
        if event.sender_id != ADMIN_ID:
            await event.reply("Only the admin can use this command.")
            return
        async with queue_lock:
            if not request_queue:
                await event.reply("Queue is empty.")
                return
            queue_info = json.dumps(request_queue, indent=2)
            await event.reply(f"Current queue:\n```\n{queue_info}\n```", parse_mode="md")

    @client.on(events.NewMessage(incoming=True))
    async def handle_message(event):
        """Handle incoming messages with TeraBox links."""
        if event.message.text.startswith('/'):
            return  # Skip commands
        user_id = event.sender_id
        chat_id = event.chat_id
        if user_id not in ALLOWED_USERS and user_id != ADMIN_ID:
            await event.reply("You are not authorized to use this bot.")
            return

        # Split message by whitespace (spaces, newlines, tabs)
        urls = re.split(r"\s+", event.message.text.strip())
        valid_urls = []
        for url in urls:
            url = url.strip()
            if not url:
                continue
            validation_error = validate_url(url)
            if validation_error:
                await event.reply(f"Invalid URL: {url}\nError: {validation_error}")
            else:
                valid_urls.append(url)

        if not valid_urls:
            return

        # Add valid URLs to queue and task queue
        async with queue_lock:
            request_ids = []
            for url in valid_urls:
                request_id = add_to_queue(user_id, url)
                request_ids.append(request_id)
                queue_position = next(i + 1 for i, req in enumerate(request_queue) if req["request_id"] == request_id)
                await event.reply(f"Processing {url}\nYou are #{queue_position} in the queue.")
                await task_queue.put((chat_id, user_id, url, request_id))

    # Start the client
    try:
        print(f"Starting bot with token {BOT_TOKEN[:10]}... at {time.ctime()}")
        await client.start(bot_token=BOT_TOKEN)
        await client.run_until_disconnected()
    finally:
        processor_task.cancel()
        try:
            await processor_task
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Rest of your existing main.py code follows...

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime
import pytz
import json
import discord
from discord.ext import commands
import aiohttp
import asyncio
import traceback
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import base64
from openai import OpenAI
from discord import ButtonStyle, Interaction
from discord.ui import Button, View
from flask import Flask
from threading import Thread
import time
import torch
from keep_alive import keep_alive

from google.oauth2.service_account import Credentials

# Flask app for keeping the bot alive
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive"

def run_flask():
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    server = Thread(target=run_flask)
    server.daemon = True
    server.start()

class GoogleSheetsLogger:
    def __init__(self, credentials_json, spreadsheet_id):
        # Load credentials from the JSON string
        creds_dict = json.loads(credentials_json)
        credentials = Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )

        # Create Google Sheets service
        self.service = build('sheets', 'v4', credentials=credentials)
        self.spreadsheet_id = spreadsheet_id

        # Initialize the spreadsheet with headers if needed
        self.initialize_sheet()

    def initialize_sheet(self):
        """Initialize the spreadsheet with headers if it's empty"""
        headers = [
            ['Date', 'Question Asked', 'Answer Provided', 'Feedback Given', 
             'Suggested Improvements', 'Status']
        ]

        # Check if headers exist
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range='Sheet1!A1:F1'
        ).execute()

        # If no headers, add them
        if 'values' not in result:
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range='Sheet1!A1',
                valueInputOption='RAW',
                body={'values': headers}
            ).execute()

    def log_interaction(self, question, answer, feedback="", improvements="", status="New"):
        """Log a new interaction to the spreadsheet"""
        # Get current time in desired timezone (e.g., Singapore)
        sg_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.now(sg_tz).strftime('%Y-%m-%d %H:%M:%S')

        # Prepare the row data
        row_data = [[
            current_time,
            question,
            answer,
            feedback,
            improvements,
            status
        ]]

        # Append the row to the spreadsheet
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range='Sheet1!A:F',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body={'values': row_data}
        ).execute()

    def update_feedback(self, question, feedback, status="Reviewed"):
        """Update the feedback and status for a specific question"""
        # Search for the question
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range='Sheet1!A:F'
        ).execute()

        if 'values' in result:
            values = result['values']
            # Skip header row
            for i, row in enumerate(values[1:], start=2):
                if len(row) > 1 and row[1] == question:
                    # Update feedback and status
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f'Sheet1!D{i}:F{i}',
                        valueInputOption='RAW',
                        body={'values': [[feedback, "", status]]}
                    ).execute()
                    break



class FeedbackView(View):
    def __init__(self, orig_question: str, bot_response: str):
        super().__init__(timeout=300)  # Buttons expire after 5 minutes
        self.orig_question = orig_question
        self.bot_response = bot_response

        # Add the buttons
        self.add_item(Button(style=ButtonStyle.green, custom_id="accurate", label="Accurate", emoji="✅"))
        self.add_item(Button(style=ButtonStyle.red, custom_id="not_accurate", label="Not Accurate", emoji="❌"))
        self.add_item(Button(style=ButtonStyle.blurple, custom_id="can_improve", label="Can Be Improved", emoji="📝"))


class FreshdeskKBBot:
    # Define ALLOWED_CATEGORIES as a class attribute
    ALLOWED_CATEGORIES = [
        "General Info",
        "Training Programme (Customer Success)",
        "Workflow",
        "Corporate Gift Products",
        "Product Specific Articles"
    ]
    def __init__(self, discord_token, freshdesk_domain, freshdesk_api_key, 
                openai_api_key, sheets_creds_json, spreadsheet_id):
        # Initialize bot
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix='!', intents=intents)  # Initialize self.bot first
        self.discord_token = discord_token  # Store token

        # Store other configurations
        self.freshdesk_domain = freshdesk_domain
        self.freshdesk_api_key = freshdesk_api_key
        self.base_url = f"https://{freshdesk_domain}.freshdesk.com/api/v2"

        # Initialize OpenAI client
        self.openai_client = OpenAI(api_key=openai_api_key)

        # Initialize Google Sheets logger
        self.sheets_logger = GoogleSheetsLogger(sheets_creds_json, spreadsheet_id)

        # Initialize empty cache
        self.kb_cache = []
        self.kb_embeddings = None
        self._model = None
        self._model_loaded = False

        # Remove default help command AFTER bot is initialized
        self.bot.remove_command('help')

        # Set up Discord commands
        self.setup_commands()

    @property
    def model(self):
        if not self._model_loaded:
            try:
                print("Loading sentence transformer model...")
                # Add timeout and device placement
                os.environ['TOKENIZERS_PARALLELISM'] = 'false'
                self._model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
                torch.set_num_threads(4)  # Limit threads
                self._model_loaded = True
                print("Model loaded successfully")
            except Exception as e:
                print(f"Error loading model: {str(e)}")
                self._model = None
                self._model_loaded = False
        return self._model

    def setup_commands(self):
        @self.bot.event
        async def on_ready():
            print(f'{self.bot.user} has connected to Discord!')
            try:
                await self.load_kb_articles()  # Load articles
                print('Bot is ready to answer questions! Knowledge base loaded.')
            except Exception as e:
                print(f'Error loading articles: {str(e)}')

        @self.bot.command(name='check_article')  # Using self.bot consistently
        async def check_article(ctx):
            async with ctx.typing():
                await ctx.send("Checking target article directly... Please check the console output.")
                await self.check_single_article()
                await ctx.send("Article check complete. Check the console for results.")

        @self.bot.command(name='test')  # Fixed from @bot to @self.bot
        async def test(ctx):
            await ctx.send('Bot is working!')

        @self.bot.command(name='diagnose_kb')
        async def diagnose_kb(ctx):
            async with ctx.typing():
                await ctx.send("Running knowledge base diagnostic... Please check the console output.")
                await self.diagnose_kb_content()
                await ctx.send("Knowledge base diagnostic complete. Check the console for results.")

        @self.bot.event
        async def on_interaction(interaction: Interaction):
            if not interaction.data:
                return
    
            if interaction.data.get("custom_id") in ["accurate", "not_accurate", "can_improve"]:
                feedback_type = interaction.data["custom_id"]
                orig_message = interaction.message
                message_content = interaction.message.content
                question_part = message_content.split("Question: ")
                if len(question_part) > 1:
                    original_question = question_part[1].split("\n")[0]
                else:
                    original_question = "Question not found"
    
                status_mapping = {
                    "accurate": "Resolved",
                    "not_accurate": "Update Needed",
                    "can_improve": "Review Needed"
                }
    
                self.sheets_logger.update_feedback(
                    question=original_question,
                    feedback=feedback_type,
                    status=status_mapping[feedback_type]
                )
    
                feedback_messages = {
                    "accurate": "Thank you for confirming that the answer was accurate! 🎯",
                    "not_accurate": "Thank you for letting us know the answer wasn't accurate. We'll work on improving it! 🎯",
                    "can_improve": "Thank you for the feedback! We'll work on improving the answer quality. 📈"
                }
    
                await interaction.response.send_message(
                    feedback_messages[feedback_type],
                    ephemeral=True
                )
    
                try:
                    for child in orig_message.components:
                        for button in child.children:
                            button.disabled = True
                    await orig_message.edit(view=View.from_message(orig_message))
                except Exception as e:
                    print(f"Error disabling buttons: {str(e)}")

        @self.bot.command(name='ask')
        async def ask(ctx, *, question):
            async with ctx.typing():
                response = await self.get_gpt_answer(question)
                self.sheets_logger.log_interaction(
                    question=question,
                    answer=response,
                    status="New"
                )
                view = FeedbackView(question, response)
                await ctx.send(
                    f"Question: {question}\n\n{response}",
                    view=view
                )

        @self.bot.command(name='help')
        async def help_command(ctx):
            help_text = (
                "**Available Commands:**\n"
                "`!ask <your question>` - Ask me anything about our knowledge base\n"
                "`!help` - Show this help message\n"
                "`!diagnose` - Run diagnostic on Freshdesk folders\n"
                "`!visibility <folder_id>` - Check and update folder visibility\n"
                "`!refresh` - Manually refresh the knowledge base to fetch new articles\n\n"
                "**Available Categories:**\n"
                "• General Info\n"
                "• Training Programme (Customer Success)\n"
                "• Workflow\n"
                "• Corporate Gift Products\n"
                "• Product Specific Articles\n\n"
                "**Example Questions:**\n"
                "• `!ask How do I process a corporate gift order?`\n"
                "• `!ask What's included in the customer success training?`\n"
                "• `!ask Tell me about our product specifications`\n\n"
                "**Note:**\n"
                "After each answer, you can provide feedback using the buttons below the response.\n"
                "To check a folder's visibility, first use `!diagnose` to get folder IDs, then use `!visibility <folder_id>`"
            )
            await ctx.send(help_text)

        @self.bot.command(name='diagnose')
        async def diagnose(ctx):
            await self.diagnose_command(ctx)

        # Add the new visibility command here
        @self.bot.command(name='visibility')
        async def check_visibility(ctx, folder_id: str):
            """Check and update folder visibility"""
            async with ctx.typing():
                await ctx.send(f"Checking visibility for folder {folder_id}...")
                await self.check_folder_visibility(folder_id)
                await ctx.send("Visibility check complete. Please check the console output.")

        @self.bot.command(name='refresh')
        async def refresh(ctx):
            """Manual refresh command to reload all articles"""
            try:
                async with ctx.typing():
                    await ctx.send("🔄 Starting knowledge base refresh...")
                    await self.load_kb_articles()  # Reload all articles
                    await ctx.send(f"✅ Knowledge base refreshed successfully! Total articles in cache: {len(self.kb_cache)}")
            except Exception as e:
                await ctx.send(f"❌ Error refreshing knowledge base: {str(e)}")

    async def check_folder_visibility(self, folder_id):
        """Check and optionally update a folder's visibility settings"""
        auth_str = f"{self.freshdesk_api_key}:X"
        auth_bytes = auth_str.encode('ascii')
        base64_auth = base64.b64encode(auth_bytes).decode('ascii')

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Basic {base64_auth}'
        }

        async with aiohttp.ClientSession() as session:
            # Get current folder settings
            url = f"{self.base_url}/solutions/folders/{folder_id}"
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        folder = await response.json()
                        print(f"\nFolder: {folder['name']}")
                        print(f"Current visibility: {folder.get('visibility', 'Not specified')}")

                        # To update visibility (example to set to "Logged In Users")
                        update_data = {
                            'visibility': 2  # 2 for Logged In Users
                        }

                        update_url = f"{self.base_url}/solutions/folders/{folder_id}"
                        async with session.put(update_url, headers=headers, json=update_data) as update_response:
                            if update_response.status == 200:
                                updated = await update_response.json()
                                print(f"✅ Updated visibility to: {updated.get('visibility')}")
                            else:
                                print(f"❌ Error updating visibility: {update_response.status}")
                    else:
                        print(f"❌ Error getting folder: {response.status}")

            except Exception as e:
                print(f"Error: {str(e)}")
                

    async def async_get(self, session, url, headers):
        """Make async HTTP GET request with timeout"""
        try:
            async with session.get(url, headers=headers, timeout=30) as response:
                if response.status == 401:
                    print("Authentication failed. Please check your Freshdesk API key.")
                    return None
                elif response.status != 200:
                    print(f"Error: Status {response.status} for URL {url}")
                    return None
                return await response.json()
        except asyncio.TimeoutError:
            print(f"Timeout accessing {url}")
            return None
        except Exception as e:
            print(f"Error accessing {url}: {str(e)}")
            return None

    async def diagnose_folder_issues(self):
        """Diagnose issues with Freshdesk folder access"""
        print("\nStarting Freshdesk folder diagnostic...\n")

        auth_str = f"{self.freshdesk_api_key}:X"
        auth_bytes = auth_str.encode('ascii')
        base64_auth = base64.b64encode(auth_bytes).decode('ascii')

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Basic {base64_auth}'
        }

        async with aiohttp.ClientSession() as session:
            # Test API connection
            test_url = f"{self.base_url}/solutions/categories"
            try:
                async with session.get(test_url, headers=headers) as response:
                    print(f"API Connection Test:")
                    print(f"Status: {response.status}")
                    if response.status == 401:
                        print("❌ Authentication failed - Please verify your API key")
                        return "Authentication failed. Please check your API key."
                    elif response.status != 200:
                        print(f"❌ API access error: {response.status}")
                        return f"API access error: {response.status}"
                    print("✅ API connection successful")

                    # Get and print all categories
                    categories = await response.json()
                    print("\nFound Categories:")
                    for category in categories:
                        print(f"\nCategory: {category['name']} (ID: {category['id']})")

                        # Get folders for each category
                        folders_url = f"{self.base_url}/solutions/categories/{category['id']}/folders"
                        async with session.get(folders_url, headers=headers) as folders_response:
                            if folders_response.status == 200:
                                folders = await folders_response.json()
                                print(f"Folders in this category:")
                                if not folders:
                                    print("  - No folders found")
                                for folder in folders:
                                    print(f"  - {folder['name']} (ID: {folder['id']})")
                                    print(f"    Visibility: {folder.get('visibility', 'Not specified')}")
                                    print(f"    Articles Count: {folder.get('articles_count', 'Not specified')}")
                                    if folder.get('company_ids'):
                                        print(f"    Restricted to companies: {folder['company_ids']}")
                            else:
                                print(f"❌ Error listing folders: {folders_response.status}")

            except Exception as e:
                error_msg = f"Error during diagnosis: {str(e)}"
                print(error_msg)
                return error_msg

            return "Diagnostic complete. Please check the console output."

    async def diagnose_command(self, ctx):
        """Run diagnostic tests on Freshdesk folder access"""
        async with ctx.typing():
            await ctx.send("Running Freshdesk folder diagnostic... Please wait.")
            result = await self.diagnose_folder_issues()
            await ctx.send(result)

    async def get_all_articles_from_folder(self, session, folder_id, headers):
        """Fetch all articles from a folder using pagination"""
        all_articles = []
        page = 1
        per_page = 30  # Freshdesk's default page size

        while True:
            print(f"  📄 Fetching page {page} of articles...")
            articles_url = f"{self.base_url}/solutions/folders/{folder_id}/articles?page={page}&per_page={per_page}"

            current_page = await self.async_get(session, articles_url, headers)

            if not current_page or len(current_page) == 0:
                break

            all_articles.extend(current_page)
            print(f"  ✅ Found {len(current_page)} articles on page {page}")

            if len(current_page) < per_page:  # If we got fewer articles than the page size, we've hit the end
                break

            page += 1

        print(f"  📚 Total articles found in folder: {len(all_articles)}")
        return all_articles
    
    async def load_kb_articles(self):
        """Fetch and cache all knowledge base articles with pagination"""
        try:
            print("\n=== Starting Knowledge Base Load with Debug Logging ===")
            print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self.kb_cache = []  # Clear existing cache

            auth_str = f"{self.freshdesk_api_key}:X"
            auth_bytes = auth_str.encode('ascii')
            base64_auth = base64.b64encode(auth_bytes).decode('ascii')

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Basic {base64_auth}'
            }

            async with aiohttp.ClientSession() as session:
                # Test API connection first
                test_url = f"{self.base_url}/solutions/categories"
                async with session.get(test_url, headers=headers) as response:
                    print(f"\n🔑 API Connection Test:")
                    print(f"Status: {response.status}")
                    print(f"Rate Limit Remaining: {response.headers.get('X-Ratelimit-Remaining', 'N/A')}")

                    if response.status != 200:
                        print(f"❌ API access error: {response.status}")
                        return
                    print("✅ API connection successful")

                # Load categories
                print("\n📚 Loading categories...")
                categories = await self.async_get(session, f"{self.base_url}/solutions/categories", headers)

                if not categories:
                    print("❌ No categories returned from API")
                    return

                print(f"Found {len(categories)} total categories")

                for category in categories:
                    category_name = category.get('name', '').strip()
                    category_id = category.get('id', '')

                    print(f"\n==== Category: {category_name} (ID: {category_id}) ====")

                    if category_name.lower() not in [cat.lower() for cat in self.ALLOWED_CATEGORIES]:
                        print(f"⏩ Skipping category {category_name} - not in allowed list")
                        continue

                    print(f"✅ Processing allowed category: {category_name}")

                    # Load folders
                    folders_url = f"{self.base_url}/solutions/categories/{category_id}/folders"
                    folders = await self.async_get(session, folders_url, headers)

                    if not folders:
                        print(f"⚠️ No folders found in category {category_name}")
                        continue

                    print(f"Found {len(folders)} folders in category")

                    for folder in folders:
                        folder_name = folder.get('name', '')
                        folder_id = folder.get('id', '')

                        print(f"\n--- Folder: {folder_name} (ID: {folder_id}) ---")

                        # Use the paginated method to get ALL articles
                        articles = await self.get_all_articles_from_folder(session, folder_id, headers)

                        if not articles:
                            print(f"⚠️ No articles found in folder {folder_name}")
                            continue

                        print(f"Found {len(articles)} total articles in folder")

                        for article in articles:
                            article_id = str(article.get('id', ''))
                            article_status = article.get('status')
                            article_title = article.get('title', 'No Title')

                            print(f"\nArticle: {article_title}")
                            print(f"  ID: {article_id}")
                            print(f"  Status: {article_status}")
                            print(f"  Created: {article.get('created_at')}")
                            print(f"  Updated: {article.get('updated_at')}")

                            if article_status == 2:
                                print("  ✅ Status is published (2)")
                                article_url = f"https://{self.freshdesk_domain}.freshdesk.com/a/solutions/articles/{article_id}"

                                # Get full article content
                                full_article = await self.async_get(
                                    session,
                                    f"{self.base_url}/solutions/articles/{article_id}",
                                    headers
                                )

                                if full_article:
                                    self.kb_cache.append({
                                        'title': full_article.get('title'),
                                        'description': full_article.get('description_text', ''),
                                        'url': article_url,
                                        'category': category_name,
                                        'folder': folder_name,
                                        'id': article_id,
                                        'status': article_status,
                                        'created_at': full_article.get('created_at'),
                                        'updated_at': full_article.get('updated_at')
                                    })
                                    print("  ✅ Successfully added to cache")
                                else:
                                    print("  ❌ Failed to fetch full article content")
                            else:
                                print(f"  ⏩ Skipping - status is not published ({article_status})")

                # Final summary
                print("\n=== Loading Summary ===")
                print(f"Total articles cached: {len(self.kb_cache)}")

                if self.kb_cache:
                    print("\n🔄 Creating embeddings...")
                    texts = [
                        f"Category: {article['category']}\n"
                        f"Folder: {article['folder']}\n"
                        f"Title: {article['title']}\n\n"
                        f"{article['description']}"
                        for article in self.kb_cache
                    ]
                    self.kb_embeddings = self.model.encode(texts)
                    print("✅ Created embeddings for all articles")

                    # Print newest articles
                    print("\n📅 Most Recent Articles:")
                    sorted_articles = sorted(self.kb_cache, 
                                          key=lambda x: x.get('updated_at', ''), 
                                          reverse=True)
                    for article in sorted_articles[:5]:
                        print(f"- {article['title']} (Updated: {article['updated_at']})")
                else:
                    print("\n⚠️ No articles were cached")

        except Exception as e:
            print(f"\n❌ Error loading articles: {str(e)}")
            print("Traceback:", traceback.format_exc())

    async def check_single_article(self):
        """Direct check of a specific article"""
        print("\n🔍 Running direct article check...")

        auth_str = f"{self.freshdesk_api_key}:X"
        auth_bytes = auth_str.encode('ascii')
        base64_auth = base64.b64encode(auth_bytes).decode('ascii')

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Basic {base64_auth}'
        }

        async with aiohttp.ClientSession() as session:
            # Check article directly
            article_id = "151000201537"
            article_url = f"{self.base_url}/solutions/articles/{article_id}"
            print(f"\nChecking article at: {article_url}")

            article = await self.async_get(session, article_url, headers)
            if article:
                print("\n✅ Article exists!")
                print(f"Title: {article.get('title')}")
                print(f"Status: {article.get('status')}")
                print(f"Category ID: {article.get('category_id')}")
                print(f"Folder ID: {article.get('folder_id')}")

                # Get category info
                category_url = f"{self.base_url}/solutions/categories/{article.get('category_id')}"
                category = await self.async_get(session, category_url, headers)
                if category:
                    print(f"Category: {category.get('name')}")

                # Get folder info
                folder_url = f"{self.base_url}/solutions/folders/{article.get('folder_id')}"
                folder = await self.async_get(session, folder_url, headers)
                if folder:
                    print(f"Folder: {folder.get('name')}")
                    print(f"Folder Visibility: {folder.get('visibility')}")
            else:
                print("\n❌ Article not found or not accessible")
    
    async def diagnose_kb_content(self):
        """Diagnose loaded knowledge base content with enhanced debugging"""
        print("\n🔍 Diagnosing Knowledge Base Content:")
        print(f"Total articles in cache: {len(self.kb_cache)}")

        # Search for specific article
        target_id = "151000201537"
        target_url = f"https://{self.freshdesk_domain}.freshdesk.com/a/solutions/articles/{target_id}"
        found = False

        # Debug: Print all categories and their articles
        print("\n📊 Articles by Category:")
        category_articles = {}
        for article in self.kb_cache:
            cat = article['category']
            if cat not in category_articles:
                category_articles[cat] = []
            category_articles[cat].append(article)

        for cat, articles in category_articles.items():
            print(f"\nCategory: {cat}")
            print(f"Number of articles: {len(articles)}")
            print("Articles:")
            for article in articles:
                print(f"  - {article['title']} (ID: {article.get('id')})")
                if target_id in article['url']:
                    print("    ⚠️ Found target article ID in this URL!")
                    print(f"    Current URL: {article['url']}")
                    print(f"    Target URL: {target_url}")
                    found = True

        # Only do detailed URL check if we found the target article
        if found:
            print("\n🔍 Detailed URL Check:")
            for article in self.kb_cache:
                current_url = article['url']
                if target_id in current_url:
                    print(f"\nPotential match found:")
                    print(f"Title: {article['title']}")
                    print(f"Category: {article['category']}")
                    print(f"Current URL: {current_url}")
                    print(f"Target URL: {target_url}")
                    print(f"URL Match: {current_url == target_url}")

    # Add this to your bot's command handlers:

    async def find_relevant_articles(self, question, num_articles=3):
        """Find the most relevant articles for a question"""
        if not self.kb_cache or not self.model:
            return []

        try:
            # Create embedding for the question
            question_embedding = self.model.encode([question])

            if self.kb_embeddings is None:
                print("Creating embeddings for cached articles...")
                texts = [
                    f"Category: {article['category']}\n"
                    f"Folder: {article['folder']}\n"
                    f"Title: {article['title']}\n\n"
                    f"{article['description']}"
                    for article in self.kb_cache
                ]
                self.kb_embeddings = self.model.encode(texts)
                print("Embeddings created successfully")

            # Calculate similarity scores
            similarities = cosine_similarity(question_embedding, self.kb_embeddings)[0]

            # Get top matches
            top_indices = similarities.argsort()[-num_articles:][::-1]
            top_scores = similarities[top_indices]
            top_matches = [self.kb_cache[i] for i in top_indices]

            relevant_articles = []
            for match, score in zip(top_matches, top_scores):
                if score > 0.2:  # Include articles with reasonable relevance
                    relevant_articles.append({
                        'title': match['title'],
                        'content': match['description'],
                        'category': match['category'],
                        'folder': match['folder'],
                        'url': match['url'],
                        'score': score
                    })

            return relevant_articles
        except Exception as e:
            print(f"Error finding relevant articles: {str(e)}")
            return []

    async def get_gpt_answer(self, question):
        """Get GPT to answer the question based on relevant articles"""
        try:
            # Find relevant articles
            relevant_articles = await self.find_relevant_articles(question)

            if not relevant_articles:
                return (
                    "I couldn't find any relevant information in our knowledge base. "
                    "Please try:\n"
                    "• Rephrasing your question\n"
                    "• Being more specific\n"
                    "• Asking about a different topic\n\n"
                    "Available categories:\n"
                    "• General Info\n"
                    "• Training Programme (Customer Success)\n"
                    "• Workflow\n"
                    "• Corporate Gift Products\n"
                    "• Product Specific Articles"
                )

            # Prepare context from relevant articles
            context = "Information from our knowledge base:\n\n"
            for article in relevant_articles:
                context += f"Article: {article['title']}\n"
                context += f"Category: {article['category']} > {article['folder']}\n"
                context += f"Content: {article['content']}\n\n"

            # Prepare prompt for GPT
            prompt = f"""You are a helpful customer service assistant. Use the following information from our knowledge base to answer the user's question. 

Knowledge Base Context:
{context}

User Question: {question}

Important Guidelines:
- Answer based ONLY on the information provided above
- If the information doesn't fully answer the question, acknowledge what you can answer and what you can't
- Include relevant article URLs when appropriate
- Be friendly and professional
- Keep your response concise and to the point

Your response should be in Discord-compatible markdown format.
"""

            # Get response from GPT
            chat_completion = self.openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are a helpful customer service assistant who answers questions based on the company's knowledge base articles."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.7
            )

            answer = chat_completion.choices[0].message.content.strip()

            # Add footer with source articles
            footer = "\n\n**Sources:**\n"
            for article in relevant_articles:
                footer += f"• [{article['title']}]({article['url']}) - {article['category']}\n"

            return answer + footer

        except Exception as e:
            return f"I encountered an error while processing your question: {str(e)}\n\nPlease try again in a moment."

    def run(self):
        """Start the Discord bot"""
        print("Starting bot...")
        self.bot.run(self.discord_token)  # Use stored token


if __name__ == "__main__":
    try:
        print("Starting initialization...")
        start_time = time.time()

        # Load environment variables
        required_env_vars = {
            "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN"),
            "FRESHDESK_DOMAIN": os.getenv("FRESHDESK_DOMAIN"),
            "FRESHDESK_API_KEY": os.getenv("FRESHDESK_API_KEY"),
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
            "GOOGLE_SHEETS_CREDS": os.getenv("GOOGLE_SHEETS_CREDS"),
            "SPREADSHEET_ID": os.getenv("SPREADSHEET_ID")
        }

        # Check for missing variables
        missing_vars = [var for var, value in required_env_vars.items() if not value]
        if missing_vars:
            raise ValueError(f"Missing environment variables: {', '.join(missing_vars)}")

        print("Initializing bot...")
        kb_bot = FreshdeskKBBot(
            required_env_vars["DISCORD_TOKEN"],
            required_env_vars["FRESHDESK_DOMAIN"],
            required_env_vars["FRESHDESK_API_KEY"],
            required_env_vars["OPENAI_API_KEY"],
            required_env_vars["GOOGLE_SHEETS_CREDS"],
            required_env_vars["SPREADSHEET_ID"]
        )

        print(f"Initialization completed in {time.time() - start_time:.2f} seconds")
        print("Starting bot...")

        # Start the keep alive server
        keep_alive()

        # Run the bot
        kb_bot.run()  # Use the class method to run

    except Exception as e:
        print(f"Fatal error during initialization: {str(e)}")
        traceback.print_exc()
        exit(1)
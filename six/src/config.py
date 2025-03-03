import os

API_ID = 2530547
API_HASH = '064b65866cd134e579424153177701dd'

# Database configuration
DATABASE_TYPE = os.environ.get('DATABASE_TYPE', 'sqlite')
DATABASE_PATH = os.environ.get('DATABASE_PATH', '.app-data/sqlite/support-bot.db')

CHAT_ID = -1002447407837
ANONYMOUS_MODE = False
LIMIT_FILE_DOWNLOAD = 20 * 1024 * 1024  # 20 MB

from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))

api_key = os.environ["API_KEY"]
print(api_key[:4] + "...")
print(os.environ["SEC_USER_AGENT"])

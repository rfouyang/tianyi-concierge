"""Call the urs_mrt_stop_right_2 action. This moves the robot arms."""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

response = requests.get(
    "http://127.0.0.1:8088/api/mrt/v1/interventions",
    headers={"Authorization": f"Bearer {os.environ['MRT_API_KEY']}"},
    params={"action": 4},
    timeout=10,
)
response.raise_for_status()
print(response.json())

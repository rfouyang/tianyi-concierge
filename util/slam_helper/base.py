"""Shared configuration for the Slamware REST API."""

import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Base:
    """Connection settings for the robot.

    ``SLAM_BASE_URL`` lets a deployment use its actual robot address without
    changing source code.  The default keeps the original development setup.
    """

    BASE_URL = os.getenv("SLAM_BASE_URL", "http://192.168.11.1:1448").rstrip("/")

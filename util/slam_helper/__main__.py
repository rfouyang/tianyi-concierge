import sys
from pathlib import Path

if __package__:
    from .localization import LocalizationClient
else:
    BASE_DIR = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(BASE_DIR))
    from util.slam_helper.localization import LocalizationClient


def main():
    localization = LocalizationClient()
    result = localization.get_robot_pose()
    print(result)


if __name__ == "__main__":
    main()

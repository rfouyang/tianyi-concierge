# Tianyi Concierge

Operator console for the Tianyi humanoid concierge: build maps, load a map and
localize, manage POIs, navigate, design guide tasks (speech + arm actions), and run
them. A separate page triggers MRT gate interventions.

## Install

```bash
uv sync
npm install
cp env_example .env   # then fill in BYTEPLUS_API_KEY, SLAM_BASE_URL, MRT_API_KEY, NGROK_API_KEY
```

## Run

```bash
source /opt/ros/humble/setup.bash
.venv/bin/python -m app.concierge_main
```

- Console (LAN): `http://<robot>:8085` — Map building, Map & localization, POI management,
  Navigation, Task design, Task execution.
- MRT page (LAN): `http://<robot>:8085/mrt`.
- MRT public API: port 8088, `GET /api/mrt/v1/interventions?action=1..4` with
  `Authorization: Bearer $MRT_API_KEY` (ngrok forwards this port only).

## Workflow

1. **Map building** — start on the charging dock, drive the area, then *Finish and save*:
   the map is persisted on the robot and saved to `data/maps/`.
2. **Map & localization** — stop localization, load a map from `data/maps/` (uploaded to
   robot storage, reloaded, verified), then localize at the dock or by dragging the arrow.
3. **POI management** — drive Tianyi to a spot and record a POI.
4. **Navigation** — send Tianyi to a POI to check it, dock, or undock.
5. **Task design** — order stops, write or upload each stop's speech, add arm actions,
   listen, and rehearse on Tianyi. Saving prepares all speech in `data/tts/`.
6. **Task execution** — confirm arm safety and run, cancel, or resume a task.

Speech files are 16 kHz, mono, 16-bit PCM WAV. Tasks run offline once their speech is
prepared; the robot needs internet only to synthesize speech while designing.

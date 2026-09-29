# Repository Guidelines

## Project architecture

Tianyi Concierge is a Python 3.10 operator console for the Tianyi humanoid: map
building, map loading and localization, POI management, navigation, task design,
and task execution, plus a standalone MRT intervention page. It follows the same
business-capability-first layout as `tianyi-action-recorder`:

- `app/` contains entrypoints and presentation code. `app/api_concierge/` holds one
  FastAPI router per domain (`router.py` + `schemas.py`) and the WebSocket;
  `app/ui_concierge/` holds Jinja templates, Tailwind/Preline CSS, and one JS class per
  page under `static/js/panels/`; `app/api_mrt/` is the public MRT API.
- `component/` contains business capabilities. `app/application.py` assembles them once.
- `util/` contains device and infrastructure adapters (Slamware REST, Tianyi ROS I/O,
  BytePlus TTS, audio, Tailwind build).
- `config/settings.py` resolves paths and `.env`; `config/task.json` stores tasks.
- `data/` holds runtime data: `maps/` (every STCM map), `tts/` (every speech clip),
  `actions/`, `poses/`, `trajectories/`. `asset/tianyi2/` is the pinned model.

The dependency direction is `app -> component -> util`. Do not add generic root folders
such as `controllers/`, `services/`, or `managers/`. The browser UI calls the REST API
and listens to `/api/concierge/ws`; pages never talk to the robot directly.

## Build, test, and run

- `uv sync` and `npm install` prepare Python and frontend dependencies.
- `source /opt/ros/humble/setup.bash && .venv/bin/python -m app.concierge_main` starts the
  console on `CONCIERGE_PORT` (8085) and, when `MRT_API_KEY` is set, the MRT API on
  `MRT_SERVICE_PORT` (8088, exposed through ngrok when `NGROK_API_KEY` is set).
  The CSS rebuilds automatically when templates, JS, or `input.css` change.
- `.venv/bin/python -m unittest discover -s tests` runs the suite; `.venv/bin/ruff check
  app component config util tests` lints it.

## Robot rules (keep these when changing behavior)

- One hardware-affecting operation runs at a time (`RobotOperationRunner`); MRT
  interventions and tours exclude each other. `POST /api/concierge/stop` never queues.
- Every hardware-affecting endpoint requires an explicit confirmation flag.
- Maps load the SLAMTEC way: upload to robot storage, `:reload`, then verify the composite
  map against the file. Never use `PUT /api/core/slam/v1/maps/stcm` (memory only).
- Loading a map is locked while localization runs; stop localization first.
- Relocalize either at the bound charging dock or at an operator-placed pose followed by a
  local search. Tours need localization quality of at least 50.
- `:save` and `:sync` are single-floor only; keep the floor-count guard.
- The robot has no internet in production. Speech is prepared during task design
  (synthesized or uploaded, always 16 kHz mono 16-bit WAV in `data/tts/`). Task
  execution never synthesizes and refuses to start if a stop's speech is missing.
- Mock robot clients in tests; routine tests must not move hardware or need a network.

## Style

PEP 8, four-space indentation, type hints on public interfaces, short docstrings where
behavior is not obvious, ruff with a 100-character line. Commit subjects are short,
imperative, and sentence case. Never commit `.env`.

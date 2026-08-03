# Sky & Space Sentinel Web

Fetch-version без WebSocket:

```bash
pip install fastapi uvicorn
cd sky_space_web
uvicorn backend:app --reload
```

Відкрити:

```text
http://127.0.0.1:8000
```

Структура:
- `simulation.py` - pure Python simulation of the satellite and drone (no PyQt)
- `backend.py` - FastAPI server, JSON API, static files
- `index.html` - tabs for MINISAT LAB / UAV SYSTEMS / AI ANALYTICS
- `styles.css` - futuristic dashboard styling
- `script.js` / `index.js` - fetch requests, UI updates, Earth map (Canvas), charts

Основні endpoints:

- `GET /api/meta`
- `GET /api/telemetry`
- `POST /api/control/toggle`
- `POST /api/control/reset`
- `POST /api/satellite/scenario`
- `POST /api/drone/scenario`

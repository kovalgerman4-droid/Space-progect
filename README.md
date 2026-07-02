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

- `simulation.py` - чиста Python-симуляція супутника і дрона без PyQt
- `backend.py` - FastAPI сервер, JSON API, static файли
- `index.html` - вкладки MINISAT LAB / UAV SYSTEMS / AI ANALYTICS
- `styles.css` - футуристична стилістика dashboard
- `script.js` / `index.js` - fetch, оновлення UI, canvas-карта Землі, графіки

Основні endpoints:

- `GET /api/meta`
- `GET /api/telemetry`
- `POST /api/control/toggle`
- `POST /api/control/reset`
- `POST /api/satellite/scenario`
- `POST /api/drone/scenario`

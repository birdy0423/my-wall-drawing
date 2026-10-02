# Render deployment: wall-sync-20261002-1

Website: https://my-wall-drawing.onrender.com/

Application release: 195716c57133b1eca19216410b8bee37488cb1c8. Public endpoints were verified on 2026-10-02. The homepage and canvas.js match the release source.

## Configuration

render.yaml describes one Python service, my-wall-drawing, in Singapore on the Free plan. Python 3.11 is pinned in .python-version.

- Build: pip install -r requirements.txt
- Start: uvicorn server_qr:app --host 0.0.0.0 --port $PORT
- Health endpoint: /healthz
- PORT and RENDER_EXTERNAL_URL are supplied by Render. QR links use RENDER_EXTERNAL_URL.
- OPENAI_API_KEY is optional for drawing. Without it, story requests return story_unavailable (503) and the button recovers. Configure the key privately in Render to enable AI stories.
- Services created from Public Git Repository require manual deployment after source updates.

## Validation

The health endpoint reports wall-sync-20261002-1. The homepage and versioned canvas.js return 200 with Cache-Control: no-cache. The QR PNG decodes to the new hostname and requested room.

A private four-client room ran for 60 seconds: 1,351 draw messages and 4,053 complete deliveries. Per-sender ordering and common broadcast ordering were preserved; latency p95 was 107.10 ms and maximum 189.95 ms. Pen/eraser, clear, theme and ten connect/close cycles passed. A second browser page displayed the lines drawn by the first page.

## Files and recovery

Deploy server_qr.py, room_sync.py, requirements.txt, render.yaml, Procfile, .python-version, static/index.html and static/canvas.js together. Exclude .env, .venv, node_modules, __pycache__ and private logs.

Disconnected clients stop drawing. This version does not replay history on rejoin. To roll back, redeploy the preceding successful full application release and update entrance links together.

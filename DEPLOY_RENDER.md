# Render drawing deployment: wall-sync-20261002-1

Status: user approved public application source publication and Render deployment on 2026-10-02; the user deferred OPENAI_API_KEY configuration. Drawing is enabled; AI stories remain unavailable until the key is configured.

Deployment source: https://github.com/birdy0423/my-wall-drawing (main).
The original source was kevinhuang02/draw-wall0; the original online service still served the old inline canvas script on 2026-10-02. The project owner approved publishing the fixes to their Render workspace and updating the local entrance URL.

## Service configuration

- Service: my-wall-drawing; Python 3.11 (latest available patch).
- Region: Singapore; instance: Free; one Python process.
- Build: pip install -r requirements.txt
- Start: uvicorn server_qr:app --host 0.0.0.0 --port $PORT
- Health check: /healthz
- Render supplies PORT and RENDER_EXTERNAL_URL; QR links use the latter.
- OPENAI_API_KEY belongs in Render environment settings only. Without it, drawing works and story requests return a clear unavailable error.
- A service created from Public Git Repository requires a manual deploy after source updates. No new GitHub integration permission is needed.

## Files

Deploy server_qr.py, room_sync.py, requirements.txt, render.yaml, Procfile, .python-version, static/index.html and static/canvas.js together. Do not upload .env, .venv, node_modules, __pycache__ or local logs.

## Verification

GET /healthz must report wall-sync-20261002-1. The homepage must reference /static/canvas.js?v=wall-sync-20261002-1, which must return 200. Check four clients in a private test room, draw/eraser/clear/end ordering, and continued relay during AI processing. Check that QR links use the new hostname and that the Electron menu opens the same hostname.

The local queue, cancellation, story and repaint tests passed. Four physical displays passed initial and resume screenshots; the end of the 10-minute transport run was obscured by other windows, so that run is not recorded as a full physical-display acceptance test. The user separately confirmed local drawing works normally.

Disconnected clients stop drawing. This version does not replay history after reconnecting. To roll back, redeploy the preceding successful full application commit and restore the local entrance URL together.

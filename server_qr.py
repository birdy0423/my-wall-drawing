# server_qr.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from openai import AsyncOpenAI
from contextlib import asynccontextmanager
from room_sync import RoomHub, StoryJobs, StoryError

import uvicorn
import os
import json
import asyncio
import qrcode
import io
import random
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server_qr")

hub = RoomHub()
story_jobs = StoryJobs()
story_deliveries = set()
client = None


@asynccontextmanager
async def lifespan(app):
    global client
    api_key = os.environ.get("OPENAI_API_KEY")
    client = AsyncOpenAI(api_key=api_key, timeout=60.0, max_retries=0) if api_key else None
    try:
        yield
    finally:
        await story_jobs.close()
        for task in tuple(story_deliveries):
            task.cancel()
        await asyncio.gather(*tuple(story_deliveries), return_exceptions=True)
        await hub.close()
        if client is not None:
            await client.close()
        client = None


APP_VERSION = "wall-sync-20261002-1"
app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@app.middleware("http")
async def canvas_cache_policy(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/static/canvas.js"}:
        response.headers["Cache-Control"] = "no-cache"
    return response

# --------------------
# CORS
# --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# --------------------
# 靜態
# --------------------
RENDER_BASE_URL = os.environ.get("RENDER_EXTERNAL_URL")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# --------------------
# 主題
# --------------------
def get_random_topic():
    return random.choice([
        "太空冒險", "海底世界", "未來城市", "森林探險",
        "恐龍世界", "機器人王國", "動物村派對", "海盜寶藏",
        "異世界冒險"
    ])

# --------------------
# 房間
# --------------------
room_topics = {}


async def broadcast(room_id, message, sender_ws=None):
    # Enqueue only: one slow connection never blocks room input or healthy peers.
    hub.broadcast(room_id, message, sender_ws)


# --------------------
# AI
# --------------------
async def generate_ai_story(base64_image: str, lang="zh"):
    image = base64_image.replace("data:image/png;base64,", "")

    language_rule = """
請使用繁體中文輸出所有內容。
""" if lang == "zh" else """
Please output everything in English only.
"""

    prompt = f"""
你是一個「兒童繪畫理解 AI + 故事動畫編劇」。

你的任務：
根據使用者提供的繪畫圖片，分析圖片內容，
再根據圖片中的元素創造故事。

========================
【非常重要：圖片分析規則】
========================

請先觀察圖片。

只能使用圖片中真正存在的內容。

禁止：
- 不可以新增圖片沒有的人物
- 不可以新增圖片沒有的動物
- 不可以新增圖片沒有的物品
- 不可以自行加入森林、城市、天空、房屋等背景
- 不可以把普通線條幻想成不存在的大型場景

如果無法確定：
請標記為「未知物件」。

========================
【圖片分析】
========================

請分析：

1. 看見的角色
2. 看見的物件
3. 顏色
4. 形狀
5. 動作
6. 背景

========================
【故事生成規則】
========================

故事必須完全建立在圖片分析結果上。

故事結構：

開頭：
介紹圖片中的角色或物件。

發展：
描述圖片中的角色互動。

結尾：
給故事一個簡單結局。

限制：

- 不加入圖片不存在的新角色。
- 不加入圖片不存在的新道具。
- 不改變圖片中的角色。
- 保持兒童故事風格。
- 約60秒旁白長度。

========================
【動畫設計】
========================

請根據圖片中的元素設計簡單動畫。

例如：

角色：
恐龍

動畫：
走路、眨眼、移動


禁止設計圖片不存在的動畫物件。

========================
【輸出格式】
========================

只能輸出 JSON：

{{
    "world":"",
    
    "title":"",
    
    "image_analysis":[
        ""
    ],

    "objects":[
        ""
    ],

    "characters":[
        {{
            "name":"",
            "description":""
        }}
    ],

    "animation":[
        {{
            "object":"",
            "action":"",
            "time":0
        }}
    ],

    "narration":[
        {{
            "time":0,
            "text":""
        }},
        {{
            "time":10,
            "text":""
        }},
        {{
            "time":20,
            "text":""
        }},
        {{
            "time":40,
            "text":""
        }}
    ]
}}

========================
【語言限制】
========================

{language_rule}

只輸出 JSON。
不要輸出 Markdown。
不要解釋。
"""

    try:
        if client is None:
            raise StoryError("story_unavailable", "AI 故事尚未設定金鑰；繪畫仍可使用。", 503)
        res = await client.chat.completions.create(
            model="gpt-4.1",
            response_format={
                "type": "json_object"
            },
            messages=[
                {
                    "role": "user",
                    "content":[
                        {
                            "type":"text",
                            "text":prompt
                        },
                        {
                            "type":"image_url",
                            "image_url":{
                                "url":
                                f"data:image/png;base64,{image}"
                            }
                        }
                    ]
                }
            ]
        )


        content = res.choices[0].message.content.strip()




        story=json.loads(content)


        return story


    except StoryError:
        raise
    except Exception as exc:
        # Do not log the image, generated content or credentials.
        logger.warning("Story generation failed: %s", type(exc).__name__)
        raise StoryError("story_failed", "故事生成失敗，請稍後再試。") from None


def story_message(story):
    if not isinstance(story, dict):
        raise StoryError("story_invalid", "AI 故事格式不完整，請再試一次。")
    narration = story.get("narration")
    if not isinstance(narration, list) or not narration:
        raise StoryError("story_invalid", "AI 故事格式不完整，請再試一次。")
    text = "\n".join(str(n["text"]) for n in narration if isinstance(n, dict) and isinstance(n.get("text"), str))
    if not text.strip():
        raise StoryError("story_invalid", "AI 故事沒有可顯示的內容，請再試一次。")
    return {"type": "story", "title": story.get("title") or "AI 故事", "story": text}


async def deliver_story(room, peer, task):
    try:
        message = story_message(await task)
        await broadcast(room, message)
    except StoryError as exc:
        hub.send(peer, exc.payload())
    except asyncio.CancelledError:
        raise
    except Exception:
        hub.send(peer, StoryError("story_failed", "故事生成失敗，請稍後再試。").payload())


# --------------------
# WebSocket
# --------------------
@app.websocket("/ws/{room_id}")
async def ws(websocket: WebSocket, room_id: str):
    await websocket.accept()
    peer = hub.join(room_id, websocket)
    room_topics.setdefault(room_id, get_random_topic())
    hub.send(peer, {"type": "topic", "value": room_topics[room_id]})
    try:
        while not peer.closed:
            try:
                data = json.loads(await websocket.receive_text())
            except (ValueError, TypeError):
                hub.send(peer, {"type": "error", "error": "invalid_message", "detail": "訊息格式不正確。"})
                continue
            if not isinstance(data, dict):
                continue
            t = data.get("type")
            if t == "draw":
                await broadcast(room_id, data, websocket)
            elif t == "clear":
                await broadcast(room_id, data)
            elif t == "generateTheme":
                topic = get_random_topic()
                room_topics[room_id] = topic
                await broadcast(room_id, {"type": "topic", "value": topic})
            elif t == "aiStory":
                image = data.get("image")
                if not isinstance(image, str) or not image:
                    hub.send(peer, StoryError("invalid_canvas", "缺少畫布影像。", 400).payload())
                    continue
                try:
                    task = story_jobs.start(room_id, lambda image=image, lang=data.get("lang", "zh"): generate_ai_story(image, lang))
                except StoryError as exc:
                    hub.send(peer, exc.payload())
                    continue
                delivery = asyncio.create_task(deliver_story(room_id, peer, task))
                story_deliveries.add(delivery)
                delivery.add_done_callback(story_deliveries.discard)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await hub.leave(peer)
        if room_id not in hub.rooms and room_id not in story_jobs.jobs:
            room_topics.pop(room_id, None)


@app.post("/ai/story")
async def ai_story(data: dict = Body(...)):
    image = data.get("canvas")
    if not isinstance(image, str) or not image:
        exc = StoryError("invalid_canvas", "缺少畫布影像。", 400)
        return JSONResponse(exc.payload(), status_code=exc.status)
    room_id = str(data.get("room") or "")
    # Requests without a room share a bounded single-job slot too.
    key = room_id or "__http_story__"
    try:
        task = story_jobs.start(key, lambda image=image, lang=data.get("lang", "zh"): generate_ai_story(image, lang))
        msg = story_message(await task)
        if room_id:
            await broadcast(room_id, msg)
        return msg
    except StoryError as exc:
        return JSONResponse(exc.payload(), status_code=exc.status)
    finally:
        if room_id not in hub.rooms and key not in story_jobs.jobs:
            room_topics.pop(room_id, None)


# --------------------
# 首頁
# --------------------
@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# --------------------
# QR
# --------------------
@app.get("/qr-room/{room}")
def qr(room: str):
    base = RENDER_BASE_URL or "http://127.0.0.1:8000"
    url = f"{base}?room={room}"
    img = qrcode.make(url)


    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/png")

# --------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)



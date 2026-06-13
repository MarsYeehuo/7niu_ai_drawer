import asyncio
import json
import os
import sys

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .command_models import CommandRequest, CanvasContext, CanvasObject
from .claude_client import parse_command
from .config import HOST, PORT

app = FastAPI(title="AI 语音绘图工具")

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def root():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
else:
    print(f"Warning: frontend directory not found at {FRONTEND_DIR}", file=sys.stderr)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()

            # Build context if provided
            ctx_data = data.get("context")
            context = None
            if ctx_data:
                objects = [CanvasObject(**o) for o in ctx_data.get("objects", [])]
                context = CanvasContext(
                    width=ctx_data.get("width", 800),
                    height=ctx_data.get("height", 600),
                    objects=objects,
                )

            req = CommandRequest(
                text=data.get("text", ""),
                model=data.get("model"),  # optional model override from frontend
                context=context,
            )
            # Run LLM calls in a thread to keep the event loop responsive (WebSocket pings, etc.)
            response = await asyncio.to_thread(parse_command, req)

            await websocket.send_json(json.loads(response.model_dump_json()))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json(
                {
                    "commands": [{"action": "error"}],
                    "tts_feedback": f"服务器错误: {str(e)}",
                }
            )
        except Exception:
            pass


def main():
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        ws_ping_interval=30,    # seconds between WebSocket pings
        ws_ping_timeout=120,    # wait up to 120s for pong before disconnect
    )


if __name__ == "__main__":
    main()

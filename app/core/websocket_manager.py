from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if job_id not in self._connections:
            self._connections[job_id] = []
        self._connections[job_id].append(websocket)

    def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        if job_id in self._connections:
            self._connections[job_id] = [
                ws for ws in self._connections[job_id] if ws is not websocket
            ]
            if not self._connections[job_id]:
                del self._connections[job_id]

    async def broadcast(self, job_id: str, data: dict) -> None:
        if job_id not in self._connections:
            return
        dead = []
        for ws in self._connections[job_id]:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(job_id, ws)

    def get_connection_count(self, job_id: str) -> int:
        return len(self._connections.get(job_id, []))

    async def close_all(self, job_id: str) -> None:
        if job_id not in self._connections:
            return
        for ws in self._connections[job_id]:
            try:
                await ws.close()
            except Exception:
                pass
        del self._connections[job_id]


ws_manager = WebSocketManager()

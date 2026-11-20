"""Optional loopback-only OBS WebSocket 5 client for OpenNotch."""
import asyncio
import base64
from dataclasses import dataclass
import hashlib
import json
import threading


@dataclass(frozen=True)
class ObsState:
    connected: bool = False
    recording: bool = False
    streaming: bool = False
    error: str = ""


class _ProtocolError(Exception):
    pass


class _RequestRejected(Exception):
    pass


def _gtk_dispatch(callback):
    from gi.repository import GLib

    GLib.idle_add(callback)


def _authentication(password, salt, challenge):
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode()).digest()).decode("ascii")


def _decode(frame):
    try:
        message = json.loads(frame)
        op, data = message["op"], message["d"]
    except (ValueError, TypeError, KeyError) as exc:
        raise _ProtocolError("OBS sent an invalid response.") from exc
    if not isinstance(op, int) or not isinstance(data, dict):
        raise _ProtocolError("OBS sent an invalid response.")
    return op, data


async def _send(socket, op, data):
    await socket.send(json.dumps({"op": op, "d": data}, separators=(",", ":")))


async def _identify(socket, password):
    op, hello = _decode(await asyncio.wait_for(socket.recv(), 3))
    if op != 0 or not isinstance(hello.get("rpcVersion"), int) or hello["rpcVersion"] < 1:
        raise _ProtocolError("The local server does not support OBS WebSocket 5.")
    identify = {"rpcVersion": 1, "eventSubscriptions": 1 << 6}  # Outputs
    if "authentication" in hello:
        auth = hello["authentication"]
        if not isinstance(auth, dict) or not all(isinstance(auth.get(k), str) for k in ("salt", "challenge")):
            raise _ProtocolError("OBS sent an invalid authentication challenge.")
        if not password:
            raise _ProtocolError("OBS requires a WebSocket password.")
        identify["authentication"] = _authentication(password, auth["salt"], auth["challenge"])
    await _send(socket, 1, identify)
    op, identified = _decode(await asyncio.wait_for(socket.recv(), 3))
    if op != 2 or identified.get("negotiatedRpcVersion") != 1:
        raise _ProtocolError("OBS did not accept the WebSocket connection.")


class ObsLink:
    """Call start, toggle_recording, and close from the GTK thread.

    on_state receives ObsState on the GLib main loop. An optional dispatch
    callback can schedule the delivery elsewhere. Construction does no I/O.
    """

    def __init__(self, on_state, password="", port=4455, *, dispatch=None):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid OBS WebSocket port.")
        self._url = f"ws://127.0.0.1:{port}"
        self._password = password
        self._on_state = on_state
        self._dispatch = dispatch or _gtk_dispatch
        self._lock = threading.Lock()
        self._state = ObsState()
        self._thread = self._loop = self._task = self._toggle = None
        self._closed = self._toggle_pending = False

    @property
    def state(self):
        with self._lock:
            return self._state

    def start(self):
        with self._lock:
            if self._closed or self._thread is not None:
                return
            self._thread = threading.Thread(target=self._worker, name="OpenNotch OBS", daemon=True)
            self._thread.start()

    def toggle_recording(self):
        """Queue one explicit toggle, returning False if OBS cannot accept it."""
        with self._lock:
            if not self._state.connected or self._closed or self._toggle_pending or self._toggle is None:
                return False
            self._toggle_pending = True
            self._loop.call_soon_threadsafe(self._toggle.set)
            return True

    def close(self):
        """Stop the connection and reconnect attempts without blocking GTK."""
        with self._lock:
            self._closed = True
            self._state = ObsState()
            if self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)

    def _publish(self, state):
        with self._lock:
            if self._closed or state == self._state:
                return
            self._state = state

        def deliver():
            with self._lock:
                closed = self._closed
            if not closed:
                self._on_state(state)
            return False

        self._dispatch(deliver)

    def _worker(self):
        try:
            from websockets.exceptions import ConnectionClosed, WebSocketException
            from websockets.legacy.client import connect
        except ImportError:
            self._publish(ObsState(error="OBS support requires Python websockets."))
            return
        asyncio.run(self._run(connect, ConnectionClosed, WebSocketException))

    async def _run(self, connect, connection_closed, websocket_error):
        with self._lock:
            if self._closed:
                return
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()

        delay = 1
        try:
            while True:
                try:
                    async with connect(self._url, open_timeout=3, close_timeout=1, max_size=1 << 20) as socket:
                        await _identify(socket, self._password)
                        toggle = asyncio.Event()
                        with self._lock:
                            self._toggle = toggle
                        session = _Session(socket, self._publish)
                        await session.initial_status()
                        delay = 1
                        while True:
                            await session.wait_for_activity(toggle)
                            if toggle.is_set():
                                toggle.clear()
                                try:
                                    await session.toggle_recording()
                                finally:
                                    with self._lock:
                                        self._toggle_pending = False
                except _ProtocolError as exc:
                    error = str(exc)
                except connection_closed as exc:
                    error = "OBS rejected the WebSocket password." if exc.code == 4009 else "OBS disconnected."
                except (OSError, TimeoutError, websocket_error):
                    error = "Could not connect to the local OBS WebSocket server."
                finally:
                    with self._lock:
                        self._toggle = None
                        self._toggle_pending = False
                self._publish(ObsState(error=error))
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8)
        except asyncio.CancelledError:
            pass
        finally:
            with self._lock:
                self._task = None
                self._loop = None


class _Session:
    def __init__(self, socket, publish):
        self.socket = socket
        self.publish = publish
        self.request_number = 0
        self.recording = self.streaming = None
        self.record_event_number = 0

    def _report(self, error=""):
        if self.recording is not None and self.streaming is not None:
            self.publish(ObsState(True, self.recording, self.streaming, error))

    def _event(self, data):
        name, event = data.get("eventType"), data.get("eventData")
        if not isinstance(event, dict) or not isinstance(event.get("outputActive"), bool):
            return
        if name == "RecordStateChanged":
            self.recording = event["outputActive"]
            self.record_event_number += 1
        elif name == "StreamStateChanged":
            self.streaming = event["outputActive"]
        else:
            return
        self._report()

    async def _request(self, name):
        self.request_number += 1
        request_id = str(self.request_number)
        await _send(self.socket, 6, {"requestType": name, "requestId": request_id})
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 4
        while True:
            op, data = _decode(await asyncio.wait_for(self.socket.recv(), deadline - loop.time()))
            if op == 5:
                self._event(data)
            if op != 7 or data.get("requestId") != request_id:
                continue
            status = data.get("requestStatus")
            if not isinstance(status, dict) or status.get("result") is not True:
                raise _RequestRejected
            response = data.get("responseData")
            if not isinstance(response, dict) or not isinstance(response.get("outputActive"), bool):
                raise _ProtocolError("OBS sent an invalid output status.")
            return response["outputActive"]

    async def initial_status(self):
        try:
            recording = await self._request("GetRecordStatus")
            streaming = await self._request("GetStreamStatus")
        except _RequestRejected as exc:
            raise _ProtocolError("OBS did not provide its output status.") from exc
        if self.recording is None:
            self.recording = recording
        if self.streaming is None:
            self.streaming = streaming
        self._report()

    async def toggle_recording(self):
        record_event = self.record_event_number
        try:
            recording = await self._request("ToggleRecord")
        except _RequestRejected:
            self._report("OBS could not toggle recording.")
            return
        if self.record_event_number == record_event:
            self.recording = recording
        self._report()

    async def wait_for_activity(self, toggle):
        receive = asyncio.create_task(self.socket.recv())
        command = asyncio.create_task(toggle.wait())
        try:
            done, _ = await asyncio.wait((receive, command), return_when=asyncio.FIRST_COMPLETED)
            if receive in done:
                op, data = _decode(receive.result())
                if op == 5:
                    self._event(data)
        finally:
            for task in (receive, command):
                if not task.done():
                    task.cancel()
            await asyncio.gather(receive, command, return_exceptions=True)

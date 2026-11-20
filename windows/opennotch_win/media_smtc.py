"""Native Windows SMTC (System Media Transport Controls) watcher & controller."""
from __future__ import annotations

import asyncio
import dataclasses
import sys
import threading
import time
from typing import Callable


@dataclasses.dataclass
class TrackInfo:
    title: str = ""
    artist: str = ""
    album: str = ""
    status: str = "Stopped"   # Playing | Paused | Stopped
    position_s: float = 0.0
    duration_s: float = 0.0
    art_bytes: bytes = b""
    app_id: str = ""
    updated_at: float = 0.0


class SmtcController:
    """Polls Windows SMTC on a background asyncio thread and dispatches Play/Pause/Prev/Next/Seek."""

    def __init__(self, on_update: Callable[[TrackInfo | None], None]):
        self._on_update = on_update
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session = None
        self._last_art_key: tuple[str, str] = ("", "")
        self._art_bytes: bytes = b""
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="opennotch-smtc")

    def start(self) -> None:
        if sys.platform != "win32":
            return
        self._thread.start()

    def stop(self) -> None:
        self._stop = True

    def _run(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._poll_loop())
        except Exception:
            pass

    async def _poll_loop(self) -> None:
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
            )
            from winsdk.windows.storage.streams import Buffer, InputStreamOptions
        except Exception:
            return

        manager = await Manager.request_async()
        while not self._stop:
            try:
                session = manager.get_current_session()
                self._session = session
                if session is None:
                    self._on_update(None)
                else:
                    props = await session.try_get_media_properties_async()
                    pb = session.get_playback_info()
                    tl = session.get_timeline_properties()
                    st_map = {
                        Status.PLAYING: "Playing",
                        Status.PAUSED: "Paused",
                    }
                    st = st_map.get(pb.playback_status, "Stopped") if pb else "Stopped"
                    title = (props.title or "").strip() if props else ""
                    artist = (props.artist or "").strip() if props else ""
                    album = (props.album_title or "").strip() if props else ""
                    dur = max(0.0, tl.end_time.total_seconds()) if (tl and tl.end_time) else 0.0
                    pos = max(0.0, tl.position.total_seconds()) if (tl and tl.position) else 0.0

                    if (title, artist) != self._last_art_key:
                        self._last_art_key = (title, artist)
                        self._art_bytes = b""
                        if props and props.thumbnail:
                            try:
                                stream = await props.thumbnail.open_read_async()
                                size = int(stream.size)
                                if 0 < size < 5_000_000:
                                    buf = Buffer(size)
                                    await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
                                    self._art_bytes = bytes(buf)
                            except Exception:
                                pass

                    self._on_update(TrackInfo(
                        title=title or "Unknown track",
                        artist=artist,
                        album=album,
                        status=st,
                        position_s=pos,
                        duration_s=dur,
                        art_bytes=self._art_bytes,
                        app_id=session.source_app_user_model_id or "",
                        updated_at=time.monotonic(),
                    ))
            except Exception:
                pass
            await asyncio.sleep(0.6)

    def _call_async(self, coro_factory) -> None:
        if self._loop and self._session:
            try:
                asyncio.run_coroutine_threadsafe(coro_factory(self._session), self._loop)
            except Exception:
                pass

    def play_pause(self) -> None:
        self._call_async(lambda s: s.try_toggle_play_pause_async())

    def next_track(self) -> None:
        self._call_async(lambda s: s.try_skip_next_async())

    def prev_track(self) -> None:
        self._call_async(lambda s: s.try_skip_previous_async())

    def seek(self, seconds: float) -> None:
        # Windows SMTC position is in 100-nanosecond ticks
        ticks = max(0, int(seconds * 10_000_000))
        self._call_async(lambda s: s.try_change_playback_position_async(ticks))

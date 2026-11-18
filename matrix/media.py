"""What's playing, from Windows' media controls (same source as the volume pop-up):
Spotify, browsers, media players. Windows only; needs the winrt packages.
Returns (title, artist) while something is playing, else None.
"""
import asyncio

try:
    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as _Manager
except Exception:          # not Windows, or packages missing
    _Manager = None

PLAYING = 4               # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING


async def _query():
    mgr = await _Manager.request_async()
    session = mgr.get_current_session()
    if session is None:
        return None
    if int(session.get_playback_info().playback_status) != PLAYING:
        return None
    props = await session.try_get_media_properties_async()
    title = (props.title or "").strip()
    return (title, (props.artist or "").strip()) if title else None


def available():
    return _Manager is not None


def now_playing():
    if _Manager is None:
        return None
    try:
        return asyncio.run(_query())
    except Exception:
        return None

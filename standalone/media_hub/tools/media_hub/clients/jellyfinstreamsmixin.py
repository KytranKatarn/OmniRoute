import logging
from typing import Any, Dict, List, Optional

from ..services import MediaItem, MediaType

logger = logging.getLogger(__name__)


class JellyfinStreamsMixin:
    """Jellyfin browser streaming URL construction."""

    def get_stream_url(self, media_id: str, direct: bool = True) -> Optional[Dict]:
        """
        Get streaming URL for a media item.

        Args:
            media_id: Jellyfin item ID
            direct: If True, attempt direct stream (no transcoding)

        Returns:
            Dict with stream_url, content_type, and playback info
        """
        user_id = self._get_user_id()
        if not user_id:
            return None

        # Get item details for resume position
        item_info = self._request(f"/Users/{user_id}/Items/{media_id}")
        resume_position_ticks = 0
        if item_info and "UserData" in item_info:
            resume_position_ticks = item_info["UserData"].get("PlaybackPositionTicks", 0)

        # Get playback info first
        playback_info = self._request(f"/Items/{media_id}/PlaybackInfo", {"UserId": user_id}, method="POST")

        if not playback_info or "MediaSources" not in playback_info:
            return None

        media_source = playback_info["MediaSources"][0] if playback_info["MediaSources"] else None
        if not media_source:
            return None

        # Get container/format - handle comma-separated container list
        raw_container = media_source.get("Container", "mp4")
        # Take first container if multiple, and normalize common formats
        container = raw_container.split(",")[0].strip()
        container_map = {
            "mov": "mp4",
            "m4a": "mp4",
            "3gp": "mp4",
            "3g2": "mp4",
            "mj2": "mp4",
            "matroska": "mkv",
            "webm": "webm",
        }
        container = container_map.get(container, container)
        media_source_id = media_source.get("Id", media_id)

        # Check audio codec compatibility - browsers only support AAC, MP3, Opus, FLAC
        browser_audio_codecs = {"aac", "mp3", "opus", "flac", "vorbis", "pcm"}
        audio_codec = None
        needs_audio_transcode = False

        for stream in media_source.get("MediaStreams", []):
            if stream.get("Type") == "Audio":
                audio_codec = stream.get("Codec", "").lower()
                # AC3, EAC3, DTS, TrueHD are not supported by browsers
                if audio_codec not in browser_audio_codecs:
                    needs_audio_transcode = True
                    logger.info(f"Audio codec '{audio_codec}' requires transcoding")
                break

        # Build stream URL
        if direct and media_source.get("SupportsDirectStream", False) and not needs_audio_transcode:
            # Direct stream - no transcoding (video and audio both compatible)
            stream_url = (
                f"{self.public_base_url}/Videos/{media_id}/stream.{container}"
                f"?Static=true&mediaSourceId={media_source_id}&api_key={self.api_key}"
            )
            transcode = False
        else:
            # HLS transcode stream
            stream_url = (
                f"{self.public_base_url}/Videos/{media_id}/master.m3u8"
                f"?mediaSourceId={media_source_id}"
                f"&api_key={self.api_key}"
                f"&VideoCodec=h264"
                f"&AudioCodec=aac"
                f"&MaxStreamingBitrate=20000000"
            )
            container = "m3u8"
            transcode = True

        # Get subtitle tracks
        subtitles = []
        for stream in media_source.get("MediaStreams", []):
            if stream.get("Type") == "Subtitle":
                sub_index = stream.get("Index", 0)
                subtitles.append(
                    {
                        "index": sub_index,
                        "language": stream.get("Language", "und"),
                        "title": stream.get("DisplayTitle", stream.get("Language", "Unknown")),
                        "url": (
                            f"{self.public_base_url}/Videos/{media_id}/{media_source_id}"
                            f"/Subtitles/{sub_index}/Stream.vtt?api_key={self.api_key}"
                        ),
                        "forced": stream.get("IsForced", False),
                        "default": stream.get("IsDefault", False),
                    }
                )

        return {
            "stream_url": stream_url,
            "container": container,
            "transcode": transcode,
            "duration_ticks": media_source.get("RunTimeTicks", 0),
            "duration_seconds": (
                media_source.get("RunTimeTicks", 0) // 10000000 if media_source.get("RunTimeTicks") else 0
            ),
            "resume_position_ticks": resume_position_ticks,
            "resume_position_seconds": (resume_position_ticks // 10000000 if resume_position_ticks else 0),
            "subtitles": subtitles,
            "media_source_id": media_source_id,
            "supports_direct": media_source.get("SupportsDirectStream", False),
        }

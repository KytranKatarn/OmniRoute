import logging
from typing import Any, Dict, List, Optional

from ..services import MediaItem, MediaType

logger = logging.getLogger(__name__)


class PlexExtrasMixin:
    """Optional Plex metadata and history operations."""

    def get_quality_info(self, media_id: str) -> Dict[str, Any]:
        """Get detailed quality information for a media item"""
        result = self._request(f"/library/metadata/{media_id}")
        quality_info = {
            "resolution": None,
            "is_4k": False,
            "is_hdr": False,
            "hdr_type": None,
            "video_codec": None,
            "audio_codec": None,
            "audio_channels": None,
            "is_atmos": False,
            "is_dts_x": False,
            "is_truehd": False,
            "bitrate": None,
            "container": None,
        }

        if result and "MediaContainer" in result:
            metadata = result["MediaContainer"].get("Metadata", [])
            if metadata:
                media_list = metadata[0].get("Media", [])
                if media_list:
                    media = media_list[0]

                    # Video info
                    resolution = media.get("videoResolution", "")
                    quality_info["resolution"] = f"{resolution}p" if resolution.isdigit() else resolution
                    quality_info["is_4k"] = resolution in ("4k", "2160")
                    quality_info["video_codec"] = media.get("videoCodec", "").upper()
                    quality_info["bitrate"] = media.get("bitrate")
                    quality_info["container"] = media.get("container", "").upper()

                    # HDR detection
                    video_profile = media.get("videoProfile", "").lower()
                    if "dolby vision" in video_profile or "dovi" in video_profile:
                        quality_info["is_hdr"] = True
                        quality_info["hdr_type"] = "Dolby Vision"
                    elif "hdr10+" in video_profile:
                        quality_info["is_hdr"] = True
                        quality_info["hdr_type"] = "HDR10+"
                    elif "hdr" in video_profile or "hdr10" in video_profile:
                        quality_info["is_hdr"] = True
                        quality_info["hdr_type"] = "HDR10"

                    # Audio info
                    audio_codec = media.get("audioCodec", "").lower()
                    audio_profile = media.get("audioProfile", "").lower()
                    quality_info["audio_codec"] = audio_codec.upper()
                    quality_info["audio_channels"] = media.get("audioChannels")

                    # Atmos/DTS:X detection
                    if "atmos" in audio_profile or "atmos" in audio_codec:
                        quality_info["is_atmos"] = True
                    if "dts:x" in audio_profile or "dts-x" in audio_codec or "dtsx" in audio_codec:
                        quality_info["is_dts_x"] = True
                    if "truehd" in audio_codec:
                        quality_info["is_truehd"] = True

        return quality_info

    def get_watch_history(self, limit: int = 50) -> List[MediaItem]:
        """Get recently watched items"""
        items = []

        for library in self._get_libraries():
            lib_key = library.get("key")
            lib_type = library.get("type")

            if lib_type not in ("movie", "show"):
                continue

            # Get recently viewed
            result = self._request(f"/library/sections/{lib_key}/recentlyViewed")
            if result and "MediaContainer" in result:
                metadata = result["MediaContainer"].get("Metadata", [])
                for item in metadata[: limit // 2]:
                    media_type = MediaType.MOVIE if lib_type == "movie" else MediaType.EPISODE
                    media_item = self._parse_media_item(item, media_type)
                    media_item.metadata["last_viewed"] = item.get("lastViewedAt")
                    items.append(media_item)

        # Sort by last viewed
        items.sort(key=lambda x: x.metadata.get("last_viewed", 0), reverse=True)
        return items[:limit]

    def get_library_by_type(self, lib_type: str) -> Optional[str]:
        """Get library key by type"""
        for library in self._get_libraries():
            if library.get("type") == lib_type:
                return library.get("key")
        return None

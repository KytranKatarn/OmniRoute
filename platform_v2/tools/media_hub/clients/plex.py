"""
Plex Media Server Client
========================
Client for interacting with Plex Media Server API.
"""

import requests
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin
from ..services import MediaServerInterface, MediaItem, MediaType, LibraryStats

logger = logging.getLogger(__name__)


class PlexClient(MediaServerInterface):
    """Client for Plex Media Server"""

    def __init__(self, host: str, port: int, api_key: str, use_ssl: bool = False):
        """
        Initialize Plex client.

        Args:
            host: Plex server host
            port: Plex server port (usually 32400)
            api_key: Plex authentication token
            use_ssl: Use HTTPS
        """
        protocol = "https" if use_ssl else "http"
        self.base_url = f"{protocol}://{host}:{port}"
        self.token = api_key
        self.timeout = 10

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make authenticated request to Plex API"""
        url = urljoin(self.base_url, endpoint)
        headers = {"X-Plex-Token": self.token, "Accept": "application/json"}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Plex API request failed: {e}")
            return None

    def probe(self) -> tuple[bool, str]:
        """Two-stage reachability + auth probe.

        Returns (is_healthy, message). `/identity` needs no token so it
        tells us server-up vs server-down. Then `/` with token tells us
        token-valid vs token-expired — without that split, an expired
        token looks identical to a dead server.
        """
        identity_url = urljoin(self.base_url, "/identity")
        try:
            resp = requests.get(identity_url, timeout=self.timeout)
            if resp.status_code != 200:
                return False, f"Plex unreachable: /identity returned HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, f"Plex unreachable at {self.base_url}: {e}"

        if not self.token:
            return False, "Plex reachable but no API token configured"

        try:
            resp = requests.get(
                urljoin(self.base_url, "/"),
                headers={"X-Plex-Token": self.token, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            return False, f"Plex root request failed: {e}"

        if resp.status_code == 401:
            return False, "Plex token invalid or expired — re-paste token in Media Hub settings"
        if resp.status_code != 200:
            return False, f"Plex root returned HTTP {resp.status_code}"
        try:
            if "MediaContainer" not in resp.json():
                return False, "Plex responded but payload missing MediaContainer"
        except ValueError:
            return False, "Plex responded with non-JSON body"
        return True, "Connection successful"

    def test_connection(self) -> bool:
        """Backward-compatible boolean check. Use probe() for detail."""
        ok, _ = self.probe()
        return ok

    def _get_libraries(self) -> List[Dict]:
        """Get all library sections"""
        result = self._request("/library/sections")
        if result and "MediaContainer" in result:
            return result["MediaContainer"].get("Directory", [])
        return []

    def _parse_media_item(self, item: Dict, media_type: MediaType) -> MediaItem:
        """Parse Plex media item to unified format"""
        # For episodes use the show poster (grandparentThumb); fall back to episode thumb
        is_episode = bool(item.get("grandparentTitle") or item.get("parentIndex"))
        poster_path = item.get("grandparentThumb") or item.get("thumb", "") if is_episode else item.get("thumb", "")
        poster_url = f"/tools/media-hub/api/proxy/thumb?s=plex&path={poster_path}" if poster_path else None

        # Get backdrop URL
        art_path = item.get("art", "")
        backdrop_url = f"/tools/media-hub/api/proxy/thumb?s=plex&path={art_path}" if art_path else None

        # Parse rating — Plex uses "rating" (critic) or "audienceRating" (audience);
        # some shows only have one or neither
        rating = item.get("rating") or item.get("audienceRating")
        if rating:
            rating = float(rating)

        # Parse genres
        genres = [g.get("tag", "") for g in item.get("Genre", [])]

        # Parse file info and quality badges
        file_size = 0
        quality = None
        file_path = None
        quality_badges = []
        video_codec = None
        audio_codec = None
        is_hdr = False
        is_atmos = False

        media_info = item.get("Media", [])
        if media_info:
            first_media = media_info[0]
            resolution = first_media.get("videoResolution", "")

            # Resolution badge
            if resolution:
                quality = f"{resolution}p" if resolution.isdigit() else resolution
                if resolution in ("4k", "2160"):
                    quality_badges.append("4K")
                elif resolution == "1080":
                    quality_badges.append("1080p")
                elif resolution == "720":
                    quality_badges.append("720p")

            # Video codec
            video_codec = first_media.get("videoCodec", "")

            # HDR detection
            video_profile = first_media.get("videoProfile", "").lower()
            if "dolby vision" in video_profile or "dovi" in video_profile:
                quality_badges.append("DV")
                is_hdr = True
            elif "hdr10+" in video_profile:
                quality_badges.append("HDR10+")
                is_hdr = True
            elif "hdr" in video_profile or "hdr10" in video_profile:
                quality_badges.append("HDR")
                is_hdr = True

            # Audio codec and format
            audio_codec = first_media.get("audioCodec", "").lower()
            audio_profile = first_media.get("audioProfile", "").lower()
            audio_channels = first_media.get("audioChannels", 0)

            if "atmos" in audio_profile or "atmos" in audio_codec:
                quality_badges.append("Atmos")
                is_atmos = True
            elif "dts:x" in audio_profile or "dtsx" in audio_codec:
                quality_badges.append("DTS:X")
            elif "truehd" in audio_codec:
                quality_badges.append("TrueHD")
            elif "dts" in audio_codec and audio_channels >= 6:
                quality_badges.append("DTS")
            elif audio_channels >= 6:
                quality_badges.append(f"{audio_channels}.1")

            parts = first_media.get("Part", [])
            if parts:
                file_size = sum(p.get("size", 0) for p in parts)
                file_path = parts[0].get("file", "")

        # Get show title for episodes
        show_title = item.get("grandparentTitle", "") or item.get("parentTitle", "")

        return MediaItem(
            id=str(item.get("ratingKey", "")),
            title=item.get("title", "Unknown"),
            media_type=media_type,
            year=item.get("year"),
            overview=item.get("summary", ""),
            poster_url=poster_url,
            backdrop_url=backdrop_url,
            rating=rating,
            rating_source="plex",
            genres=genres,
            runtime_minutes=(item.get("duration", 0) // 60000 if item.get("duration") else None),
            quality=quality,
            file_size_bytes=file_size,
            file_path=file_path,
            added_at=item.get("addedAt"),
            season_number=item.get("parentIndex"),
            episode_number=item.get("index"),
            parent_id=(str(item.get("parentRatingKey", "")) if item.get("parentRatingKey") else None),
            in_library=True,
            metadata={
                "guid": item.get("guid", ""),
                "studio": item.get("studio", ""),
                "contentRating": item.get("contentRating", ""),
                "quality_badges": quality_badges,
                "video_codec": video_codec,
                "audio_codec": audio_codec,
                "is_hdr": is_hdr,
                "is_atmos": is_atmos,
                "show_title": show_title,
            },
        )

    def search_library(self, query: str, media_type: Optional[str] = None) -> List[MediaItem]:
        """Search the Plex library"""
        params = {"query": query}

        # Determine search type
        search_type = None
        if media_type == "movie":
            search_type = 1
        elif media_type in ("show", "tv"):
            search_type = 2

        if search_type:
            params["type"] = search_type

        result = self._request("/hubs/search", params)
        items = []

        if result and "MediaContainer" in result:
            hubs = result["MediaContainer"].get("Hub", [])
            for hub in hubs:
                hub_type = hub.get("type", "")
                hub_items = hub.get("Metadata", [])

                for item in hub_items:
                    if hub_type == "movie":
                        items.append(self._parse_media_item(item, MediaType.MOVIE))
                    elif hub_type == "show":
                        items.append(self._parse_media_item(item, MediaType.SHOW))
                    elif hub_type == "episode":
                        items.append(self._parse_media_item(item, MediaType.EPISODE))

        return items

    def get_recent_additions(self, limit: int = 20) -> List[MediaItem]:
        """Get recently added items from all libraries"""
        items = []

        for library in self._get_libraries():
            lib_key = library.get("key")
            lib_type = library.get("type")

            if lib_type not in ("movie", "show"):
                continue

            result = self._request(f"/library/sections/{lib_key}/recentlyAdded")
            if result and "MediaContainer" in result:
                metadata = result["MediaContainer"].get("Metadata", [])
                for item in metadata[: limit // 2]:  # Split limit between libraries
                    media_type = MediaType.MOVIE if lib_type == "movie" else MediaType.SHOW
                    items.append(self._parse_media_item(item, media_type))

        # Sort by added_at and limit
        items.sort(key=lambda x: x.added_at or "", reverse=True)
        return items[:limit]

    def get_library_stats(self) -> LibraryStats:
        """Get library statistics"""
        stats = LibraryStats()

        for library in self._get_libraries():
            lib_key = library.get("key")
            lib_type = library.get("type")

            result = self._request(f"/library/sections/{lib_key}/all")
            if result and "MediaContainer" in result:
                metadata = result["MediaContainer"].get("Metadata", [])

                if lib_type == "movie":
                    stats.movie_count = len(metadata)
                    for item in metadata:
                        media_info = item.get("Media", [])
                        if media_info:
                            for media in media_info:
                                for part in media.get("Part", []):
                                    stats.total_size_bytes += part.get("size", 0)

                elif lib_type == "show":
                    stats.show_count = len(metadata)
                    # Get episode count
                    for show in metadata:
                        show_key = show.get("ratingKey")
                        eps_result = self._request(f"/library/metadata/{show_key}/allLeaves")
                        if eps_result and "MediaContainer" in eps_result:
                            eps = eps_result["MediaContainer"].get("Metadata", [])
                            stats.episode_count += len(eps)
                            for ep in eps:
                                media_info = ep.get("Media", [])
                                if media_info:
                                    for media in media_info:
                                        for part in media.get("Part", []):
                                            stats.total_size_bytes += part.get("size", 0)

        return stats

    def get_media_details(self, media_id: str) -> Optional[MediaItem]:
        """Get detailed information about a media item"""
        result = self._request(f"/library/metadata/{media_id}")
        if result and "MediaContainer" in result:
            metadata = result["MediaContainer"].get("Metadata", [])
            if metadata:
                item = metadata[0]
                item_type = item.get("type", "")

                if item_type == "movie":
                    return self._parse_media_item(item, MediaType.MOVIE)
                elif item_type == "show":
                    return self._parse_media_item(item, MediaType.SHOW)
                elif item_type == "season":
                    return self._parse_media_item(item, MediaType.SEASON)
                elif item_type == "episode":
                    return self._parse_media_item(item, MediaType.EPISODE)

        return None

    def get_all_movies(self, limit: int = 100, offset: int = 0, sort: str = "added") -> List[MediaItem]:
        """Get all movies with pagination and sorting"""
        items = []

        # Map sort options to Plex sort values
        sort_map = {
            "added": "addedAt:desc",
            "title": "titleSort:asc",
            "year": "year:desc",
            "rating": "rating:desc",
        }
        plex_sort = sort_map.get(sort, "addedAt:desc")

        for library in self._get_libraries():
            if library.get("type") == "movie":
                lib_key = library.get("key")
                params = {
                    "X-Plex-Container-Start": offset,
                    "X-Plex-Container-Size": limit,
                    "sort": plex_sort,
                }

                result = self._request(f"/library/sections/{lib_key}/all", params)
                if result and "MediaContainer" in result:
                    metadata = result["MediaContainer"].get("Metadata", [])
                    for item in metadata:
                        items.append(self._parse_media_item(item, MediaType.MOVIE))
                break

        return items

    def get_all_shows(self, limit: int = 100, offset: int = 0, sort: str = "added") -> List[MediaItem]:
        """Get all TV shows with pagination and sorting"""
        items = []

        # Map sort options to Plex sort values
        sort_map = {
            "added": "addedAt:desc",
            "title": "titleSort:asc",
            "year": "year:desc",
            "rating": "rating:desc",
        }
        plex_sort = sort_map.get(sort, "addedAt:desc")

        for library in self._get_libraries():
            if library.get("type") == "show":
                lib_key = library.get("key")
                params = {
                    "X-Plex-Container-Start": offset,
                    "X-Plex-Container-Size": limit,
                    "sort": plex_sort,
                }

                result = self._request(f"/library/sections/{lib_key}/all", params)
                if result and "MediaContainer" in result:
                    metadata = result["MediaContainer"].get("Metadata", [])
                    for item in metadata:
                        items.append(self._parse_media_item(item, MediaType.SHOW))
                break

        return items

    def get_seasons(self, series_id: str) -> List[Dict]:
        """Get seasons for a TV series"""
        result = self._request(f"/library/metadata/{series_id}/children")
        seasons = []

        if result and "MediaContainer" in result:
            metadata = result["MediaContainer"].get("Metadata", [])
            for item in metadata:
                if item.get("type") == "season":
                    thumb = item.get("thumb", "")
                    seasons.append(
                        {
                            "id": str(item.get("ratingKey", "")),
                            "name": item.get("title", f"Season {item.get('index', 0)}"),
                            "season_number": item.get("index", 0),
                            "episode_count": item.get("leafCount", 0),
                            "poster_url": (f"/tools/media-hub/api/proxy/thumb?s=plex&path={thumb}" if thumb else None),
                            "overview": item.get("summary", ""),
                            "year": item.get("year"),
                        }
                    )

        # Sort by season number
        seasons.sort(key=lambda x: x.get("season_number", 0))
        return seasons

    def get_episodes(self, series_id: str, season_number: int = None) -> List[Dict]:
        """Get episodes for a TV series, optionally filtered by season"""
        episodes = []

        # First get seasons to find the right season ID
        if season_number is not None:
            seasons = self.get_seasons(series_id)
            season_id = None
            for s in seasons:
                if s.get("season_number") == season_number:
                    season_id = s.get("id")
                    break
            if season_id:
                result = self._request(f"/library/metadata/{season_id}/children")
            else:
                return []
        else:
            # Get all episodes using allLeaves
            result = self._request(f"/library/metadata/{series_id}/allLeaves")

        if result and "MediaContainer" in result:
            metadata = result["MediaContainer"].get("Metadata", [])
            for item in metadata:
                thumb = item.get("thumb", "")

                # Get quality info
                quality = None
                media_list = item.get("Media", [])
                if media_list:
                    media = media_list[0]
                    resolution = media.get("videoResolution", "")
                    if resolution in ("4k", "2160"):
                        quality = "4K"
                    elif resolution == "1080":
                        quality = "1080p"
                    elif resolution == "720":
                        quality = "720p"
                    else:
                        quality = "SD"

                # Get watched status and progress
                view_count = item.get("viewCount", 0)
                played = view_count > 0
                view_offset = item.get("viewOffset", 0)  # Playback position in ms
                duration = item.get("duration", 0)  # Total duration in ms
                watch_progress = 0
                if duration > 0 and view_offset > 0:
                    watch_progress = round((view_offset / duration) * 100)

                # Get runtime in minutes
                runtime_minutes = duration // 60000 if duration else None

                episodes.append(
                    {
                        "id": str(item.get("ratingKey", "")),
                        "title": item.get("title", ""),
                        "season_number": item.get("parentIndex", 0),
                        "episode_number": item.get("index", 0),
                        "overview": item.get("summary", ""),
                        "runtime_minutes": runtime_minutes,
                        "quality": quality,
                        "poster_url": (f"/tools/media-hub/api/proxy/thumb?s=plex&path={thumb}" if thumb else None),
                        "air_date": item.get("originallyAvailableAt"),
                        "has_file": len(media_list) > 0,
                        "played": played,
                        "view_count": view_count,
                        "watch_progress": watch_progress,
                    }
                )

        # Sort by season and episode number
        episodes.sort(key=lambda x: (x.get("season_number", 0), x.get("episode_number", 0)))
        return episodes

    def mark_watched(self, media_id: str, watched: bool = True) -> bool:
        """Mark a media item as watched or unwatched"""
        try:
            endpoint = "/:/scrobble" if watched else "/:/unscrobble"
            url = (
                f"{self.base_url}{endpoint}?key={media_id}"
                f"&identifier=com.plexapp.plugins.library&X-Plex-Token={self.token}"
            )
            response = requests.get(url, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error marking watched status: {e}")
            return False

    def get_on_deck(self, limit: int = 10) -> List[MediaItem]:
        """Get on deck (continue watching) items"""
        result = self._request("/library/onDeck")
        items = []

        if result and "MediaContainer" in result:
            metadata = result["MediaContainer"].get("Metadata", [])
            for item in metadata[:limit]:
                item_type = item.get("type", "")
                media_item = None
                if item_type == "movie":
                    media_item = self._parse_media_item(item, MediaType.MOVIE)
                elif item_type == "episode":
                    media_item = self._parse_media_item(item, MediaType.EPISODE)

                if media_item:
                    # Add watch progress
                    view_offset = item.get("viewOffset", 0)
                    duration = item.get("duration", 0)
                    if duration > 0:
                        media_item.metadata["watch_progress"] = round((view_offset / duration) * 100)
                        media_item.metadata["view_offset_ms"] = view_offset
                    items.append(media_item)

        return items

    def get_collections(self) -> List[Dict[str, Any]]:
        """Get all collections from the library"""
        collections = []

        for library in self._get_libraries():
            lib_key = library.get("key")
            lib_type = library.get("type")

            if lib_type not in ("movie", "show"):
                continue

            result = self._request(f"/library/sections/{lib_key}/collections")
            if result and "MediaContainer" in result:
                for coll in result["MediaContainer"].get("Metadata", []):
                    thumb = coll.get("thumb", "")
                    art = coll.get("art", "")
                    collections.append(
                        {
                            "id": str(coll.get("ratingKey", "")),
                            "title": coll.get("title", ""),
                            "summary": coll.get("summary", ""),
                            "poster_url": (f"/tools/media-hub/api/proxy/thumb?s=plex&path={thumb}" if thumb else None),
                            "backdrop_url": (f"{self.base_url}{art}?X-Plex-Token={self.token}" if art else None),
                            "child_count": coll.get("childCount", 0),
                            "library_type": lib_type,
                            "added_at": coll.get("addedAt"),
                        }
                    )

        return collections

    def get_collection_items(self, collection_id: str) -> List[MediaItem]:
        """Get items in a collection"""
        result = self._request(f"/library/collections/{collection_id}/children")
        items = []

        if result and "MediaContainer" in result:
            metadata = result["MediaContainer"].get("Metadata", [])
            for item in metadata:
                item_type = item.get("type", "")
                if item_type == "movie":
                    items.append(self._parse_media_item(item, MediaType.MOVIE))
                elif item_type == "show":
                    items.append(self._parse_media_item(item, MediaType.SHOW))

        return items

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

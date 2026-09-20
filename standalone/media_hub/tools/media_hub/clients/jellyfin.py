"""
Jellyfin Media Server Client
============================
Client for interacting with Jellyfin Media Server API.
"""

import os
import requests
import logging
from typing import List, Optional, Dict
from urllib.parse import urljoin
from ..services import MediaServerInterface, MediaItem, MediaType, LibraryStats

logger = logging.getLogger(__name__)


class JellyfinClient(MediaServerInterface):
    """Client for Jellyfin Media Server"""

    def __init__(self, host: str, port: int, api_key: str, use_ssl: bool = False):
        """
        Initialize Jellyfin client.

        Args:
            host: Jellyfin server host
            port: Jellyfin server port (usually 8096)
            api_key: Jellyfin API key
            use_ssl: Use HTTPS
        """
        protocol = "https" if use_ssl else "http"
        self.base_url = f"{protocol}://{host}:{port}"
        # Browser-facing base for STREAM + subtitle URLs. base_url is a LAN IP
        # over plain HTTP, which a browser on the HTTPS Media Hub page blocks as
        # mixed content (and cannot reach off-LAN). Hand the browser the public
        # HTTPS Jellyfin URL instead; server-side API calls keep using base_url.
        self.public_base_url = os.environ.get("JELLYFIN_PUBLIC_URL", "https://jellyfin.kytranempowerment.com").rstrip(
            "/"
        )
        self.api_key = api_key
        self.timeout = 10
        self._user_id = None

    def _request(self, endpoint: str, params: Optional[Dict] = None, method: str = "GET") -> Optional[Dict]:
        """Make authenticated request to Jellyfin API"""
        url = urljoin(self.base_url, endpoint)
        headers = {"X-MediaBrowser-Token": self.api_key, "Accept": "application/json"}

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            else:
                response = requests.post(url, headers=headers, json=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.RequestException as e:
            logger.error(f"Jellyfin API request failed: {e}")
            return None

    def _get_user_id(self) -> Optional[str]:
        """Get the first user ID for API calls"""
        if self._user_id:
            return self._user_id

        result = self._request("/Users")
        if result and isinstance(result, list) and len(result) > 0:
            self._user_id = result[0].get("Id")
            return self._user_id
        return None

    def probe(self) -> tuple[bool, str]:
        """Two-stage reachability + auth probe.

        `/System/Info/Public` needs no token so it tells us server-up vs
        server-down. Then `/System/Info` with token tells us token-valid
        vs token-expired — without the split, a bad key looks identical
        to a dead server.
        """
        public_url = urljoin(self.base_url, "/System/Info/Public")
        try:
            resp = requests.get(public_url, timeout=self.timeout)
            if resp.status_code != 200:
                return False, f"Jellyfin unreachable: /System/Info/Public returned HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, f"Jellyfin unreachable at {self.base_url}: {e}"

        if not self.api_key:
            return False, "Jellyfin reachable but no API key configured"

        try:
            resp = requests.get(
                urljoin(self.base_url, "/System/Info"),
                headers={"X-MediaBrowser-Token": self.api_key, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            return False, f"Jellyfin /System/Info request failed: {e}"

        if resp.status_code == 401:
            return False, "Jellyfin API key invalid or expired — re-paste key in Media Hub settings"
        if resp.status_code != 200:
            return False, f"Jellyfin /System/Info returned HTTP {resp.status_code}"
        try:
            if "ServerName" not in resp.json():
                return False, "Jellyfin responded but payload missing ServerName"
        except ValueError:
            return False, "Jellyfin responded with non-JSON body"
        return True, "Connection successful"

    def test_connection(self) -> bool:
        """Backward-compatible boolean check. Use probe() for detail."""
        ok, _ = self.probe()
        return ok

    def _get_image_url(self, item_id: str, image_type: str = "Primary") -> Optional[str]:
        """Get image URL via server-side proxy so it works on HTTPS / external access."""
        if not item_id:
            return None
        return f"/tools/media-hub/api/proxy/thumb?s=jellyfin&id={item_id}&type={image_type}"

    def _parse_media_item(self, item: Dict, media_type: Optional[MediaType] = None) -> MediaItem:
        """Parse Jellyfin media item to unified format"""
        item_id = item.get("Id", "")
        item_type_str = item.get("Type", "").lower()

        # Determine media type
        if media_type is None:
            if item_type_str == "movie":
                media_type = MediaType.MOVIE
            elif item_type_str == "series":
                media_type = MediaType.SHOW
            elif item_type_str == "season":
                media_type = MediaType.SEASON
            elif item_type_str == "episode":
                media_type = MediaType.EPISODE
            else:
                media_type = MediaType.MOVIE  # Default

        # Build image URLs
        poster_url = self._get_image_url(item_id, "Primary") if item.get("ImageTags", {}).get("Primary") else None
        backdrop_url = self._get_image_url(item_id, "Backdrop") if item.get("BackdropImageTags") else None

        # Parse rating
        rating = item.get("CommunityRating")

        # Parse genres
        genres = item.get("Genres", [])

        # Parse file info
        file_size = 0
        quality = None
        file_path = None
        media_sources = item.get("MediaSources", [])
        if media_sources:
            first_source = media_sources[0]
            file_size = first_source.get("Size", 0)
            file_path = first_source.get("Path", "")

            # Get quality from video stream
            streams = first_source.get("MediaStreams", [])
            for stream in streams:
                if stream.get("Type") == "Video":
                    height = stream.get("Height", 0)
                    if height >= 2160:
                        quality = "4K"
                    elif height >= 1080:
                        quality = "1080p"
                    elif height >= 720:
                        quality = "720p"
                    else:
                        quality = "SD"
                    break

        # Parse external IDs
        provider_ids = item.get("ProviderIds", {})

        return MediaItem(
            id=item_id,
            title=item.get("Name", "Unknown"),
            media_type=media_type,
            year=item.get("ProductionYear"),
            overview=item.get("Overview", ""),
            poster_url=poster_url,
            backdrop_url=backdrop_url,
            rating=rating,
            rating_source="jellyfin",
            genres=genres,
            runtime_minutes=(item.get("RunTimeTicks", 0) // 600000000 if item.get("RunTimeTicks") else None),
            quality=quality,
            file_size_bytes=file_size,
            file_path=file_path,
            added_at=item.get("DateCreated"),
            tmdb_id=int(provider_ids.get("Tmdb")) if provider_ids.get("Tmdb") else None,
            imdb_id=provider_ids.get("Imdb"),
            tvdb_id=int(provider_ids.get("Tvdb")) if provider_ids.get("Tvdb") else None,
            season_number=item.get("ParentIndexNumber"),
            episode_number=item.get("IndexNumber"),
            parent_id=item.get("ParentId"),
            in_library=True,
            metadata={
                "studios": [s.get("Name", "") for s in item.get("Studios", [])],
                "officialRating": item.get("OfficialRating", ""),
                "show_title": item.get("SeriesName"),  # For episodes
            },
        )

    def search_library(self, query: str, media_type: Optional[str] = None) -> List[MediaItem]:
        """Search the Jellyfin library"""
        user_id = self._get_user_id()
        if not user_id:
            return []

        params = {
            "searchTerm": query,
            "Limit": 50,
            "Recursive": True,
            "Fields": "Overview,Genres,ProviderIds,MediaSources,DateCreated",
        }

        # Filter by type
        if media_type == "movie":
            params["IncludeItemTypes"] = "Movie"
        elif media_type in ("show", "tv"):
            params["IncludeItemTypes"] = "Series"
        else:
            params["IncludeItemTypes"] = "Movie,Series"

        result = self._request(f"/Users/{user_id}/Items", params)
        items = []

        if result and "Items" in result:
            for item in result["Items"]:
                items.append(self._parse_media_item(item))

        return items

    def get_recent_additions(self, limit: int = 20) -> List[MediaItem]:
        """Get recently added items"""
        user_id = self._get_user_id()
        if not user_id:
            return []

        params = {
            "Limit": limit,
            "Recursive": True,
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "IncludeItemTypes": "Movie,Series",
            "Fields": "Overview,Genres,ProviderIds,DateCreated",
        }

        result = self._request(f"/Users/{user_id}/Items", params)
        items = []

        if result and "Items" in result:
            for item in result["Items"]:
                items.append(self._parse_media_item(item))

        return items

    def get_library_stats(self) -> LibraryStats:
        """Get library statistics"""
        stats = LibraryStats()
        user_id = self._get_user_id()
        if not user_id:
            return stats

        # Get movie count and size
        movie_result = self._request(
            f"/Users/{user_id}/Items",
            {"IncludeItemTypes": "Movie", "Recursive": True, "Fields": "MediaSources"},
        )
        if movie_result and "Items" in movie_result:
            stats.movie_count = movie_result.get("TotalRecordCount", len(movie_result["Items"]))
            for movie in movie_result["Items"]:
                for source in movie.get("MediaSources", []):
                    stats.total_size_bytes += source.get("Size", 0)

        # Get show count
        show_result = self._request(f"/Users/{user_id}/Items", {"IncludeItemTypes": "Series", "Recursive": True})
        if show_result and "Items" in show_result:
            stats.show_count = show_result.get("TotalRecordCount", len(show_result["Items"]))

        # Get episode count and size
        episode_result = self._request(
            f"/Users/{user_id}/Items",
            {
                "IncludeItemTypes": "Episode",
                "Recursive": True,
                "Fields": "MediaSources",
            },
        )
        if episode_result and "Items" in episode_result:
            stats.episode_count = episode_result.get("TotalRecordCount", len(episode_result["Items"]))
            for episode in episode_result["Items"]:
                for source in episode.get("MediaSources", []):
                    stats.total_size_bytes += source.get("Size", 0)

        return stats

    def get_media_details(self, media_id: str) -> Optional[MediaItem]:
        """Get detailed information about a media item"""
        user_id = self._get_user_id()
        if not user_id:
            return None

        result = self._request(
            f"/Users/{user_id}/Items/{media_id}",
            {"Fields": "Overview,Genres,ProviderIds,MediaSources,DateCreated,People,Studios"},
        )

        if result:
            return self._parse_media_item(result)

        return None

    def get_all_movies(self, limit: int = 100, offset: int = 0, sort: str = "added") -> List[MediaItem]:
        """Get all movies with pagination and sorting"""
        user_id = self._get_user_id()
        if not user_id:
            return []

        # Map sort options to Jellyfin SortBy values
        sort_map = {
            "added": ("DateCreated", "Descending"),
            "title": ("SortName", "Ascending"),
            "year": ("ProductionYear", "Descending"),
            "rating": ("CommunityRating", "Descending"),
        }
        sort_by, sort_order = sort_map.get(sort, ("DateCreated", "Descending"))

        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": True,
            "SortBy": sort_by,
            "SortOrder": sort_order,
            "Limit": limit,
            "StartIndex": offset,
            "Fields": "Overview,Genres,ProviderIds,MediaSources,DateCreated",
        }

        result = self._request(f"/Users/{user_id}/Items", params)
        items = []

        if result and "Items" in result:
            for item in result["Items"]:
                items.append(self._parse_media_item(item, MediaType.MOVIE))

        return items

    def get_all_shows(self, limit: int = 100, offset: int = 0, sort: str = "added") -> List[MediaItem]:
        """Get all TV shows with pagination and sorting"""
        user_id = self._get_user_id()
        if not user_id:
            return []

        # Map sort options to Jellyfin SortBy values
        sort_map = {
            "added": ("DateCreated", "Descending"),
            "title": ("SortName", "Ascending"),
            "year": ("ProductionYear", "Descending"),
            "rating": ("CommunityRating", "Descending"),
        }
        sort_by, sort_order = sort_map.get(sort, ("DateCreated", "Descending"))

        params = {
            "IncludeItemTypes": "Series",
            "Recursive": True,
            "SortBy": sort_by,
            "SortOrder": sort_order,
            "Limit": limit,
            "StartIndex": offset,
            "Fields": "Overview,Genres,ProviderIds,DateCreated",
        }

        result = self._request(f"/Users/{user_id}/Items", params)
        items = []

        if result and "Items" in result:
            for item in result["Items"]:
                items.append(self._parse_media_item(item, MediaType.SHOW))

        return items

    def get_continue_watching(self, limit: int = 10) -> List[MediaItem]:
        """Get items to continue watching"""
        user_id = self._get_user_id()
        if not user_id:
            return []

        result = self._request(
            f"/Users/{user_id}/Items/Resume",
            {"Limit": limit, "Fields": "Overview,Genres,ProviderIds"},
        )
        items = []

        if result and "Items" in result:
            for item in result["Items"]:
                media_item = self._parse_media_item(item)
                # Add watch progress from user data
                user_data = item.get("UserData", {})
                if user_data:
                    ticks = user_data.get("PlaybackPositionTicks", 0)
                    run_ticks = item.get("RunTimeTicks", 0)
                    if run_ticks > 0:
                        media_item.metadata["watch_progress"] = round((ticks / run_ticks) * 100)
                        media_item.metadata["view_offset_ms"] = ticks // 10000
                items.append(media_item)

        return items

    def get_on_deck(self, limit: int = 10) -> List[MediaItem]:
        """Alias for get_continue_watching (compatibility with Plex API naming)"""
        return self.get_continue_watching(limit)

    def get_watch_history(self, limit: int = 50) -> List[MediaItem]:
        """Get recently watched/played items"""
        user_id = self._get_user_id()
        if not user_id:
            return []

        # Get played items sorted by last played date
        result = self._request(
            f"/Users/{user_id}/Items",
            {
                "Limit": limit,
                "Recursive": True,
                "IsPlayed": True,
                "SortBy": "DatePlayed",
                "SortOrder": "Descending",
                "IncludeItemTypes": "Movie,Episode",
                "Fields": "Overview,Genres,ProviderIds,DateLastMediaAdded",
            },
        )
        items = []

        if result and "Items" in result:
            for item in result["Items"]:
                media_item = self._parse_media_item(item)
                # Add last viewed timestamp
                user_data = item.get("UserData", {})
                if user_data and user_data.get("LastPlayedDate"):
                    media_item.metadata["last_viewed"] = user_data.get("LastPlayedDate")
                items.append(media_item)

        return items

    def get_seasons(self, series_id: str) -> List[Dict]:
        """Get seasons for a TV series"""
        user_id = self._get_user_id()
        if not user_id:
            return []

        result = self._request(
            f"/Shows/{series_id}/Seasons",
            {"UserId": user_id, "Fields": "Overview,DateCreated,ChildCount"},
        )

        seasons = []
        if result and "Items" in result:
            for item in result["Items"]:
                seasons.append(
                    {
                        "id": item.get("Id"),
                        "name": item.get("Name", f"Season {item.get('IndexNumber', 0)}"),
                        "season_number": item.get("IndexNumber", 0),
                        "episode_count": item.get("ChildCount", 0),
                        "poster_url": self._get_image_url(item.get("Id"), "Primary"),
                        "overview": item.get("Overview", ""),
                    }
                )
        return seasons

    def get_episodes(self, series_id: str, season_number: int = None) -> List[Dict]:
        """Get episodes for a TV series, optionally filtered by season"""
        user_id = self._get_user_id()
        if not user_id:
            return []

        params = {
            "UserId": user_id,
            "Fields": "Overview,DateCreated,MediaSources",
        }
        if season_number is not None:
            params["Season"] = season_number

        result = self._request(f"/Shows/{series_id}/Episodes", params)

        episodes = []
        if result and "Items" in result:
            for item in result["Items"]:
                # Get quality info from media sources
                quality = None
                runtime = item.get("RunTimeTicks", 0) // 600000000 if item.get("RunTimeTicks") else None
                media_sources = item.get("MediaSources", [])
                if media_sources:
                    for stream in media_sources[0].get("MediaStreams", []):
                        if stream.get("Type") == "Video":
                            height = stream.get("Height", 0)
                            if height >= 2160:
                                quality = "4K"
                            elif height >= 1080:
                                quality = "1080p"
                            elif height >= 720:
                                quality = "720p"
                            else:
                                quality = "SD"
                            break

                # Get played status and progress from user data
                user_data = item.get("UserData", {})
                played = user_data.get("Played", False)
                playback_ticks = user_data.get("PlaybackPositionTicks", 0)
                runtime_ticks = item.get("RunTimeTicks", 0)
                watch_progress = 0
                if runtime_ticks > 0 and playback_ticks > 0:
                    watch_progress = round((playback_ticks / runtime_ticks) * 100)

                episodes.append(
                    {
                        "id": item.get("Id"),
                        "title": item.get("Name", ""),
                        "season_number": item.get("ParentIndexNumber", 0),
                        "episode_number": item.get("IndexNumber", 0),
                        "overview": item.get("Overview", ""),
                        "runtime_minutes": runtime,
                        "quality": quality,
                        "poster_url": self._get_image_url(item.get("Id"), "Primary"),
                        "air_date": item.get("PremiereDate"),
                        "has_file": len(media_sources) > 0,
                        "played": played,
                        "watch_progress": watch_progress,
                    }
                )
        return episodes

    def get_next_episode(self, episode_id: str) -> Optional[Dict]:
        """Given a currently-playing episode's item id, resolve the next episode
        in its series: same season episode_number+1, or episode 1 of the next
        season if the given episode was the season finale."""
        user_id = self._get_user_id()
        if not user_id:
            return None

        item = self._request(
            f"/Users/{user_id}/Items/{episode_id}",
            {"Fields": "SeriesId,ParentIndexNumber,IndexNumber"},
        )
        if not item:
            return None

        series_id = item.get("SeriesId")
        season_number = item.get("ParentIndexNumber")
        episode_number = item.get("IndexNumber")
        if not series_id or season_number is None or episode_number is None:
            return None

        for ep in self.get_episodes(series_id, season_number):
            if ep.get("episode_number") == episode_number + 1:
                return ep

        next_season = self.get_episodes(series_id, season_number + 1)
        if next_season:
            return min(next_season, key=lambda e: e.get("episode_number", 0))

        return None

    def mark_watched(self, media_id: str, watched: bool = True) -> bool:
        """Mark a media item as watched or unwatched"""
        user_id = self._get_user_id()
        if not user_id:
            return False

        headers = {"X-MediaBrowser-Token": self.api_key, "Accept": "application/json"}

        try:
            url = f"{self.base_url}/Users/{user_id}/PlayedItems/{media_id}"
            if watched:
                response = requests.post(url, headers=headers, timeout=10)
            else:
                response = requests.delete(url, headers=headers, timeout=10)

            return response.status_code in [200, 204]
        except Exception as e:
            logger.error(f"Error marking watched status: {e}")
            return False

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

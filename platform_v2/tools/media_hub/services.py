"""
Media Hub Service Abstraction Layer
====================================
Abstract interfaces and factory for media server clients.

Provides a unified interface for Plex/Jellyfin and *arr services,
enabling seamless migration between media servers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ServiceType(Enum):
    """Supported service types"""

    PLEX = "plex"
    JELLYFIN = "jellyfin"
    SONARR = "sonarr"
    RADARR = "radarr"
    PROWLARR = "prowlarr"
    OVERSEERR = "overseerr"
    JELLYSEERR = "jellyseerr"
    SABNZBD = "sabnzbd"


class MediaType(Enum):
    """Media types"""

    MOVIE = "movie"
    SHOW = "show"
    SEASON = "season"
    EPISODE = "episode"


@dataclass
class MediaItem:
    """Unified media item representation"""

    id: str
    title: str
    media_type: MediaType
    year: Optional[int] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    rating: Optional[float] = None
    rating_source: Optional[str] = None
    genres: List[str] = field(default_factory=list)
    runtime_minutes: Optional[int] = None
    quality: Optional[str] = None
    file_size_bytes: Optional[int] = None
    file_path: Optional[str] = None
    added_at: Optional[str] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    tvdb_id: Optional[int] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    parent_id: Optional[str] = None
    in_library: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "id": self.id,
            "title": self.title,
            "media_type": self.media_type.value,
            "year": self.year,
            "overview": self.overview,
            "poster_url": self.poster_url,
            "backdrop_url": self.backdrop_url,
            "rating": self.rating,
            "rating_source": self.rating_source,
            "genres": self.genres,
            "runtime_minutes": self.runtime_minutes,
            "quality": self.quality,
            "file_size_bytes": self.file_size_bytes,
            "file_path": self.file_path,
            "added_at": self.added_at,
            "tmdb_id": self.tmdb_id,
            "imdb_id": self.imdb_id,
            "tvdb_id": self.tvdb_id,
            "season_number": self.season_number,
            "episode_number": self.episode_number,
            "parent_id": self.parent_id,
            "in_library": self.in_library,
            "metadata": self.metadata,
        }


@dataclass
class UpcomingEpisode:
    """Upcoming episode representation"""

    series_id: int
    series_title: str
    season_number: int
    episode_number: int
    episode_title: Optional[str]
    air_date: str
    air_time: Optional[str] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    runtime_minutes: Optional[int] = None
    has_file: bool = False
    monitored: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_id": self.series_id,
            "series_title": self.series_title,
            "season_number": self.season_number,
            "episode_number": self.episode_number,
            "episode_title": self.episode_title,
            "air_date": self.air_date,
            "air_time": self.air_time,
            "overview": self.overview,
            "poster_url": self.poster_url,
            "runtime_minutes": self.runtime_minutes,
            "has_file": self.has_file,
            "monitored": self.monitored,
        }


@dataclass
class MediaRequest:
    """Media request representation"""

    id: str
    media_type: str
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    tmdb_id: Optional[int] = None
    status: str = "pending"
    requested_by: Optional[str] = None
    requested_at: Optional[str] = None
    download_status: Optional[str] = None
    download_progress: Optional[int] = None
    seasons_requested: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "media_type": self.media_type,
            "title": self.title,
            "year": self.year,
            "poster_url": self.poster_url,
            "tmdb_id": self.tmdb_id,
            "status": self.status,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "download_status": self.download_status,
            "download_progress": self.download_progress,
            "seasons_requested": self.seasons_requested,
        }


@dataclass
class DownloadItem:
    """Download queue item representation"""

    id: str
    filename: str
    category: Optional[str] = None
    size_bytes: Optional[int] = None
    size_left_bytes: Optional[int] = None
    progress_percent: int = 0
    eta_seconds: Optional[int] = None
    speed_bytes_sec: Optional[int] = None
    status: str = "queued"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "category": self.category,
            "size_bytes": self.size_bytes,
            "size_left_bytes": self.size_left_bytes,
            "progress_percent": self.progress_percent,
            "eta_seconds": self.eta_seconds,
            "speed_bytes_sec": self.speed_bytes_sec,
            "status": self.status,
        }


@dataclass
class LibraryStats:
    """Library statistics"""

    movie_count: int = 0
    show_count: int = 0
    episode_count: int = 0
    total_size_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "movie_count": self.movie_count,
            "show_count": self.show_count,
            "episode_count": self.episode_count,
            "total_size_bytes": self.total_size_bytes,
            "total_size_formatted": self._format_size(self.total_size_bytes),
        }

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes to human readable"""
        if size_bytes == 0:
            return "0 B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(size_bytes) < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"


class MediaServerInterface(ABC):
    """Abstract interface for media servers (Plex, Jellyfin)"""

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the service is reachable and authenticated"""
        pass

    @abstractmethod
    def search_library(self, query: str, media_type: Optional[str] = None) -> List[MediaItem]:
        """Search the local library"""
        pass

    @abstractmethod
    def get_recent_additions(self, limit: int = 20) -> List[MediaItem]:
        """Get recently added items"""
        pass

    @abstractmethod
    def get_library_stats(self) -> LibraryStats:
        """Get library statistics"""
        pass

    @abstractmethod
    def get_media_details(self, media_id: str) -> Optional[MediaItem]:
        """Get detailed information about a media item"""
        pass

    @abstractmethod
    def get_all_movies(self, limit: int = 100, offset: int = 0) -> List[MediaItem]:
        """Get all movies with pagination"""
        pass

    @abstractmethod
    def get_all_shows(self, limit: int = 100, offset: int = 0) -> List[MediaItem]:
        """Get all TV shows with pagination"""
        pass


class ArrServiceInterface(ABC):
    """Abstract interface for *arr services (Sonarr, Radarr)"""

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the service is reachable and authenticated"""
        pass

    @abstractmethod
    def get_queue(self) -> List[Dict[str, Any]]:
        """Get download queue"""
        pass

    @abstractmethod
    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search for media"""
        pass


class RequestServiceInterface(ABC):
    """Abstract interface for request services (Overseerr, Jellyseerr)"""

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the service is reachable and authenticated"""
        pass

    @abstractmethod
    def search(self, query: str) -> List[MediaItem]:
        """Search TMDB/TVDB for media"""
        pass

    @abstractmethod
    def get_requests(self, status: Optional[str] = None) -> List[MediaRequest]:
        """Get media requests"""
        pass

    @abstractmethod
    def create_request(self, media_type: str, tmdb_id: int, seasons: Optional[List[int]] = None) -> Dict[str, Any]:
        """Create a new media request"""
        pass


class DownloaderInterface(ABC):
    """Abstract interface for download clients (SABnzbd)"""

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the service is reachable"""
        pass

    @abstractmethod
    def get_queue(self) -> List[DownloadItem]:
        """Get current download queue"""
        pass

    @abstractmethod
    def get_history(self, limit: int = 20) -> List[DownloadItem]:
        """Get download history"""
        pass

    @abstractmethod
    def get_speed(self) -> Dict[str, Any]:
        """Get current download speed"""
        pass


class CalendarServiceInterface(ABC):
    """Abstract interface for calendar data (from Sonarr)"""

    @abstractmethod
    def get_upcoming_episodes(self, days: int = 7) -> List[UpcomingEpisode]:
        """Get upcoming episodes for the next N days"""
        pass


def get_service_client(service_type: str, host: str, port: int, api_key: str, use_ssl: bool = False):
    """
    Factory function to get the appropriate service client.

    Args:
        service_type: Type of service ('plex', 'jellyfin', 'sonarr', etc.)
        host: Service host
        port: Service port
        api_key: API key or token
        use_ssl: Use HTTPS

    Returns:
        Appropriate service client instance
    """
    from .clients.plex import PlexClient
    from .clients.jellyfin import JellyfinClient
    from .clients.sonarr import SonarrClient
    from .clients.radarr import RadarrClient
    from .clients.prowlarr import ProwlarrClient
    from .clients.overseerr import OverseerrClient
    from .clients.sabnzbd import SABnzbdClient

    clients = {
        "plex": PlexClient,
        "jellyfin": JellyfinClient,
        "sonarr": SonarrClient,
        "radarr": RadarrClient,
        "prowlarr": ProwlarrClient,
        "overseerr": OverseerrClient,
        "jellyseerr": OverseerrClient,  # Uses same API as Overseerr
        "sabnzbd": SABnzbdClient,
    }

    client_class = clients.get(service_type.lower())
    if not client_class:
        raise ValueError(f"Unknown service type: {service_type}")

    return client_class(host=host, port=port, api_key=api_key, use_ssl=use_ssl)

"""Media Hub route registration facade."""

from .library_routes import *  # noqa: F401,F403
from .library_delete_routes import *  # noqa: F401,F403
from .library_delete_routes import _arr_base, _delete_library_item
from .request_routes import *  # noqa: F401,F403
from .calendar_routes import *  # noqa: F401,F403
from .service_routes import *  # noqa: F401,F403
from .playback_routes import *  # noqa: F401,F403
from .download_routes import *  # noqa: F401,F403
from .tmdb_routes import *  # noqa: F401,F403
from .stats_routes import *  # noqa: F401,F403

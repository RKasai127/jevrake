"""jevrake: selector-free web scraping with TypeSafe AI's Jev."""

from ._internal.api import rake
from ._internal.models import ExtractedValue, RakeResult
from ._internal.version import VERSION as __version__

__all__ = [
    "ExtractedValue",
    "RakeResult",
    "__version__",
    "rake",
]

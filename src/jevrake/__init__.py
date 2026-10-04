"""jevrake: selector-free web scraping with TypeSafe AI's Jev."""

from ._internal.api import arake, arake_many, rake, rake_many
from ._internal.models import FieldResult, RakeResult
from ._internal.version import VERSION as __version__

__all__ = [
    "FieldResult",
    "RakeResult",
    "__version__",
    "arake",
    "arake_many",
    "rake",
    "rake_many",
]

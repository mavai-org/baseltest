"""Single source of the package version, importable without the API surface.

Lives apart from the package ``__init__`` so a lower layer (the reporting
renderers stamp the version into the verdict record) can read the version
without importing the top-level authoring surface that ``__init__``
re-exports — which would make a lower layer depend on a higher one.
"""

from importlib import metadata

__version__ = metadata.version("baseltest")

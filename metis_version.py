"""Single source of truth for the Metis product version and public links.

Keep METIS_VERSION in sync with:
  - site public build (METIS_VERSION / NEXT_PUBLIC_METIS_VERSION)
  - pyproject [project].version
  - Inno Setup (build_installer.ps1 passes /DMyAppVersion=... from this file)
"""

import os

METIS_VERSION = "0.54.0"

# Match site/lib/brand.ts defaults (override with env in packaged builds if needed)
METIS_PRODUCT_NAME = "Metis Command"
METIS_SUPPORT_URL = os.getenv(
    "METIS_SUPPORT_URL",
    "https://github.com/om1o/Metis_Command/discussions",
)
METIS_RELEASES_URL = os.getenv(
    "METIS_RELEASES_URL",
    "https://github.com/om1o/Metis_Command/releases",
)
METIS_MARKETING_SITE = os.getenv(
    "METIS_MARKETING_SITE",
    "",  # e.g. https://metis.example.com — empty = show paths only
)


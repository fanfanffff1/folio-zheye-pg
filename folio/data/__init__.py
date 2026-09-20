"""Literary map and related static content data."""

from .literary_regions import LITERARY_REGIONS, get_region, regions_for_filter
from .region_groups import FILTER_PILLS, OVERSEAS_ISLANDS, REGION_GROUPS

__all__ = [
    "FILTER_PILLS",
    "LITERARY_REGIONS",
    "OVERSEAS_ISLANDS",
    "REGION_GROUPS",
    "get_region",
    "regions_for_filter",
]

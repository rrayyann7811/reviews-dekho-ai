"""Shared building blocks for website adapters."""
from dataclasses import dataclass, field
from urllib.parse import ParseResult

from ..errors import AppError


# ---------- Errors (each carries a plain-language message and an HTTP status) ----------

class CollectionError(AppError):
    """Base class: something stopped reviews from being collected."""


class UnsupportedLink(CollectionError):
    def __init__(self, message: str):
        super().__init__(message, 422)


class CollectionNotPermitted(CollectionError):
    def __init__(self, message: str):
        super().__init__(message, 422)


class ProductNotFound(CollectionError):
    def __init__(self, message: str):
        super().__init__(message, 404)


class NoReviewsFound(CollectionError):
    def __init__(self, message: str):
        super().__init__(message, 422)


class SourceUnavailable(CollectionError):
    """The website/API couldn't be reached or answered unexpectedly. Trying again later may work."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message, status_code)


# ---------- Data passed between adapter and service ----------

@dataclass
class ProductRef:
    """A product identified from a link, before anything is downloaded."""
    site: str          # adapter id
    product_id: str    # the website's own ID
    region: str        # storefront / country, or "" if the site has none
    url: str           # canonical link shown to the user


@dataclass
class CollectedProduct:
    name: str
    url: str
    brand: str | None = None
    category: str | None = None
    # Raw review records: id, text, rating, date, title, reviewer. Cleaned later by services/ingestion.
    reviews: list[dict] = field(default_factory=list)
    # Extra facts shown to the user, e.g. how many pages were read and any limits of the source.
    details: dict = field(default_factory=dict)


class SourceAdapter:
    """Override `parse` and `collect` in a supported adapter."""

    id: str = ""
    name: str = ""
    hosts: tuple[str, ...] = ()
    status: str = "supported"      # or "unavailable": recognised, but reviews can't be collected
    domain: str = "product"        # what the site's reviews are about: "product" or "app"
    note: str = ""                 # one sentence shown in the list of websites
    example: str | None = None     # example link shown in the UI and docs

    def matches(self, host: str) -> bool:
        return any(host == h or host.endswith(f".{h}") for h in self.hosts)

    def parse(self, url: ParseResult) -> ProductRef:
        raise NotImplementedError

    def collect(self, ref: ProductRef, http) -> CollectedProduct:
        raise NotImplementedError

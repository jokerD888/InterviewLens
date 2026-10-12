"""Shared trust boundary for browser navigation and manual ingest."""

from urllib.parse import urlparse

from .metadata_api import detail_endpoint

ALLOWED_HOSTS = {"www.nowcoder.com", "gw-c.nowcoder.com"}
RESOURCE_HOSTS = ALLOWED_HOSTS | {
    "static.nowcoder.com", "images.nowcoder.com", "uploadfiles.nowcoder.com",
}


def allowed_request_url(url: str) -> bool:
    parsed = urlparse(url)
    try:
        return (
            parsed.scheme == "https"
            and parsed.hostname in RESOURCE_HOSTS
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def validate_post_url(url: str):
    if not isinstance(url, str) or not allowed_request_url(url) or not detail_endpoint(url):
        raise ValueError("Only HTTPS Nowcoder post URLs are accepted")


def validate_page_url(url: str):
    if not allowed_request_url(url) or urlparse(url).hostname != "www.nowcoder.com":
        raise ValueError("Only HTTPS www.nowcoder.com pages are accepted")

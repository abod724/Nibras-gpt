"""Optional Travelpayouts partner-link adapter for Nibras GP.
This module has NO side effects on import and is not wired into chat automatically.
Enable only after verifying the program accepts the Nibras use case.
Docs: https://support.travelpayouts.com/hc/en-us/articles/25289759198226-API-for-Travelpayouts-partner-links
"""
import ipaddress
import os
from urllib.parse import urlsplit
import requests

_API_URL = "https://api.travelpayouts.com/links/v1/create"

class TravelAffiliateError(Exception):
    pass

def travel_affiliate_ready():
    """No outbound calls and no chat impact unless explicitly enabled."""
    return (os.getenv("TRAVELPAYOUTS_ENABLED", "false").lower() == "true"
            and all(os.getenv(name) for name in (
                "TRAVELPAYOUTS_API_TOKEN", "TRAVELPAYOUTS_MARKER",
                "TRAVELPAYOUTS_PROJECT_ID")))

def _validate_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise TravelAffiliateError("Invalid destination URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise TravelAffiliateError("Only public HTTPS travel links are allowed")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise TravelAffiliateError("Internal links are not allowed")
    try:
        ipaddress.ip_address(host)
        raise TravelAffiliateError("IP-address links are not allowed")
    except ValueError:
        pass
    return value

def create_partner_links(urls, sub_id=None):
    """Convert approved travel-brand URLs to partner URLs.

    No booking, payment, user data transfer, search, or price verification.
    Returns original URL when its conversion fails; caller should disclose
    which links are affiliate links. No user-specific information in sub_id.
    """
    if not travel_affiliate_ready():
        raise TravelAffiliateError("Travelpayouts integration is disabled or not configured")
    if not isinstance(urls, (list, tuple)) or not (1 <= len(urls) <= 10):
        raise TravelAffiliateError("Provide between 1 and 10 URLs")
    validated = [_validate_url(url) for url in urls]
    try:
        marker = int(os.environ["TRAVELPAYOUTS_MARKER"])
        project = int(os.environ["TRAVELPAYOUTS_PROJECT_ID"])
    except (ValueError, KeyError) as exc:
        raise TravelAffiliateError("Invalid partner or project ID") from exc
    if sub_id is not None and (not isinstance(sub_id, str) or
                               len(sub_id) > 64 or not sub_id.isascii() or
                               not all(c.isalnum() or c in "_-" for c in sub_id)):
        raise TravelAffiliateError("Invalid non-personal tracking tag")
    links = [{"url": url, **({"sub_id": sub_id} if sub_id else {})}
             for url in validated]
    try:
        response = requests.post(
            _API_URL,
            headers={"X-Access-Token": os.environ["TRAVELPAYOUTS_API_TOKEN"],
                     "Content-Type": "application/json"},
            json={"trs": project, "marker": marker, "shorten": False, "links": links},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TravelAffiliateError("Partner-link service is unavailable") from exc
    returned = payload.get("result", {}).get("links", [])
    if not isinstance(returned, list):
        raise TravelAffiliateError("Unexpected partner-link response")
    output = []
    for original, item in zip(validated, returned):
        partner_url = item.get("partner_url") if isinstance(item, dict) else None
        if isinstance(item, dict) and item.get("code") == "success" and isinstance(partner_url, str):
            try:
                _validate_url(partner_url)
                output.append({"original_url": original, "url": partner_url, "affiliate": True})
                continue
            except TravelAffiliateError:
                pass
        output.append({"original_url": original, "url": original, "affiliate": False})
    while len(output) < len(validated):
        original = validated[len(output)]
        output.append({"original_url": original, "url": original, "affiliate": False})
    return output

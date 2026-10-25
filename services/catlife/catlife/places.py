"""Nearby veterinaries through Google Places Text Search (New). The HTTP client is injected."""

from __future__ import annotations

import httpx

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join((
    "places.displayName", "places.formattedAddress", "places.nationalPhoneNumber", "places.rating",
    "places.userRatingCount", "places.currentOpeningHours.openNow", "places.googleMapsUri", "places.websiteUri",
))
RADIUS_M = 10_000


def find_veterinaries(client: httpx.Client, api_key: str, location: str | None, latitude: float | None,
                      longitude: float | None, emergency: bool = False, limit: int = 10) -> list[dict]:
    query = "veterinaria de urgencias 24 horas" if emergency else "veterinaria para gatos"
    body: dict = {"textQuery": f"{query} en {location}" if location else query, "languageCode": "es",
                  "maxResultCount": limit}
    if latitude is not None and longitude is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": latitude, "longitude": longitude},
                                           "radius": RADIUS_M}}
    response = client.post(SEARCH_URL, json=body,
                           headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS})
    response.raise_for_status()
    return [
        {
            "name": place.get("displayName", {}).get("text"),
            "address": place.get("formattedAddress"),
            "phone": place.get("nationalPhoneNumber"),
            "rating": place.get("rating"),
            "reviews": place.get("userRatingCount"),
            "open_now": place.get("currentOpeningHours", {}).get("openNow"),
            "maps_url": place.get("googleMapsUri"),
            "website": place.get("websiteUri"),
        }
        for place in response.json().get("places", [])
    ]

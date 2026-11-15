from __future__ import annotations

import os
from typing import Any

import requests


TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/"


class MetadataConfigError(RuntimeError):
    pass


class MetadataProviderError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        raise MetadataConfigError(
            "TMDB_API_KEY is not configured. Add it to your environment to enable metadata import."
        )
    return key


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = dict(params or {})
    params["api_key"] = _api_key()
    try:
        resp = requests.get(f"{TMDB_BASE}{path}", params=params, timeout=15)
    except requests.RequestException as exc:
        raise MetadataProviderError(f"Could not reach metadata provider: {exc}") from exc
    if resp.status_code == 401:
        raise MetadataConfigError("TMDB_API_KEY is invalid or unauthorized.")
    if resp.status_code == 429:
        raise MetadataProviderError("Metadata provider rate limit reached. Try again later.")
    if not resp.ok:
        raise MetadataProviderError(f"Metadata provider error ({resp.status_code}).")
    return resp.json()


def search_movies(query: str, page: int = 1) -> dict[str, Any]:
    return _get("/search/movie", {"query": query, "page": page, "include_adult": "false"})


def get_movie(movie_id: int) -> dict[str, Any]:
    return _get(f"/movie/{movie_id}", {"append_to_response": "credits,videos"})


def image_url(path: str | None, size: str = "w500") -> str | None:
    if not path:
        return None
    return f"{TMDB_IMAGE_BASE}{size}{path}"


def map_tmdb_movie(data: dict[str, Any]) -> dict[str, Any]:
    genres = data.get("genres") or []
    genre_names = [g.get("name") for g in genres if g.get("name")]
    credits = data.get("credits") or {}
    crew = credits.get("crew") or []
    cast = credits.get("cast") or []
    directors = [p.get("name") for p in crew if p.get("job") == "Director" and p.get("name")]
    cast_names = [p.get("name") for p in cast[:10] if p.get("name")]
    videos = (data.get("videos") or {}).get("results") or []
    trailer = None
    for v in videos:
        if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser") and v.get("key"):
            trailer = f"https://www.youtube.com/watch?v={v['key']}"
            if v.get("type") == "Trailer":
                break
    release_date = data.get("release_date") or ""
    year = None
    if len(release_date) >= 4 and release_date[:4].isdigit():
        year = int(release_date[:4])
    return {
        "title": (data.get("title") or data.get("name") or "").strip()[:255],
        "description": (data.get("overview") or "").strip(),
        "release_year": year,
        "genre": ", ".join(genre_names[:3])[:100] if genre_names else None,
        "director": ", ".join(directors[:3])[:255] if directors else None,
        "language": (data.get("original_language") or "").strip()[:100] or None,
        "rating": data.get("vote_average"),
        "poster_url": image_url(data.get("poster_path"), "w500"),
        "backdrop_url": image_url(data.get("backdrop_path"), "w1280"),
        "trailer_url": trailer,
        "runtime_minutes": data.get("runtime"),
        "cast_members": ", ".join(cast_names)[:5000] if cast_names else None,
        "keywords": None,
        "tmdb_id": data.get("id"),
        "attribution": "Metadata sourced from TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. Importing metadata does not grant distribution rights.",
    }

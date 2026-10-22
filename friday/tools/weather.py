"""
Weather tools — current conditions and forecast via Open-Meteo (no API key).
"""

import httpx

_HEADERS = {"User-Agent": "Friday-AI/1.0"}

# Open-Meteo WMO weather codes → spoken descriptions
_WEATHER_CODES = {
    0: "clear sky",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "snow showers",
    86: "snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "severe thunderstorms with hail",
}


async def _geocode(client: httpx.AsyncClient, city: str) -> dict | None:
    """Look up a city's coordinates via Open-Meteo geocoding."""
    resp = await client.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en"},
    )
    resp.raise_for_status()
    results = resp.json().get("results")
    return results[0] if results else None


def register(mcp):

    @mcp.tool()
    async def get_weather(city: str) -> str:
        """
        Get current weather conditions for a city (temperature, wind, sky).
        Use when the user asks about weather, temperature, or rain.
        """
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            try:
                place = await _geocode(client, city)
                if not place:
                    return f"I couldn't find a city called '{city}', boss."

                resp = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": place["latitude"],
                        "longitude": place["longitude"],
                        "current": "temperature_2m,relative_humidity_2m,"
                                   "weather_code,wind_speed_10m",
                        "temperature_unit": "celsius",
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                return "The weather grid is unresponsive right now, boss."

        current = resp.json().get("current", {})
        temp_c = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        wind = current.get("wind_speed_10m")
        code = current.get("weather_code")
        sky = _WEATHER_CODES.get(code, "unknown conditions")

        label = place.get("name", city)
        country = place.get("country_code", "")
        where = f"{label}, {country}" if country else label

        return (
            f"Weather for {where}: {temp_c}°C, {sky}. "
            f"Humidity {humidity}%, wind {wind} km/h."
        )

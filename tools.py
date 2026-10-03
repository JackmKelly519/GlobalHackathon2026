"""
Tools that Claude can call.

Each tool has:
  1. a schema in TOOLS (what Claude sees: name, description, inputs)
  2. a Python function with the same name (what actually runs)

To add a tool: write the function, add its schema to TOOLS, register it in TOOL_FUNCTIONS.
"""

import json
import os
import re
import urllib.parse
import urllib.request

# ───────────────────────── CONFIG ─────────────────────────
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
REGION = "ke"          # Google Maps region bias (Kenya)
HTTP_TIMEOUT = 10
# ──────────────────────────────────────────────────────────


def _get_json(url: str, params: dict) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=HTTP_TIMEOUT) as r:
        return json.load(r)


def maps_link(origin: str, destination: str, mode: str = "transit") -> str:
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(
        {"api": 1, "origin": origin, "destination": destination, "travelmode": mode}
    )


# ───────────────────────── Tool implementations ─────────────────────────
def get_directions(origin: str, destination: str, mode: str = "transit") -> dict:
    """Directions via Google Directions API. Transit falls back to driving. Always returns a Maps link."""
    out = {"maps_link": maps_link(origin, destination, mode)}
    if not GOOGLE_MAPS_API_KEY:
        out["note"] = "No GOOGLE_MAPS_API_KEY set; only a Maps link is available."
        return out

    modes = [mode, "driving"] if mode == "transit" else [mode]
    for m in modes:
        try:
            data = _get_json(
                "https://maps.googleapis.com/maps/api/directions/json",
                {"origin": origin, "destination": destination, "mode": m,
                 "region": REGION, "key": GOOGLE_MAPS_API_KEY},
            )
        except Exception as e:
            out["error"] = str(e)
            continue
        if data.get("status") == "OK":
            leg = data["routes"][0]["legs"][0]
            out.update({
                "mode": m,
                "distance": leg["distance"]["text"],
                "duration": leg["duration"]["text"],
                "steps": [re.sub(r"<[^>]+>", "", s["html_instructions"]) for s in leg["steps"][:6]],
                "maps_link": maps_link(origin, destination, m),
            })
            return out
    return out


def find_nearby_facilities(query: str, near: str) -> dict:
    """Google Places text search, e.g. query='dialysis clinic', near='Kibera, Nairobi'."""
    if not GOOGLE_MAPS_API_KEY:
        return {"note": "No GOOGLE_MAPS_API_KEY set; cannot search facilities."}
    try:
        data = _get_json(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            {"query": f"{query} near {near}", "region": REGION, "key": GOOGLE_MAPS_API_KEY},
        )
    except Exception as e:
        return {"error": str(e)}
    return {"facilities": [
        {"name": p["name"], "address": p.get("formatted_address", "")}
        for p in data.get("results", [])[:3]
    ]}


# ───────────────────────── Schemas Claude sees ─────────────────────────
TOOLS = [
    {
        "name": "get_directions",
        "description": (
            "Get public-transport (matatu/bus) or driving directions between two places, "
            "with distance, duration, first steps and a Google Maps link. "
            "Use when the patient can't get to the hospital or doesn't know the way."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Starting address (the patient's home)"},
                "destination": {"type": "string", "description": "Hospital name and/or address"},
                "mode": {"type": "string", "enum": ["transit", "driving", "walking"], "default": "transit"},
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "find_nearby_facilities",
        "description": (
            "Search for health facilities near a location. Use when the patient says the hospital "
            "doesn't offer the service they need, or it is the wrong place."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Service or facility type, e.g. 'HIV clinic'"},
                "near": {"type": "string", "description": "Location to search near"},
            },
            "required": ["query", "near"],
        },
    },
]

TOOL_FUNCTIONS = {
    "get_directions": get_directions,
    "find_nearby_facilities": find_nearby_facilities,
}


def run_tool(name: str, tool_input: dict) -> str:
    """Execute a tool Claude asked for and return a JSON string for the tool_result."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return json.dumps(fn(**tool_input), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def make_classify_tool(barriers: list[str]) -> dict:
    """Schema for the forced-classification call (built from the barrier list)."""
    return {
        "name": "record_barrier",
        "description": "Record the single best barrier category for the patient's message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "barrier": {"type": "string", "enum": barriers},
                "confidence": {"type": "number", "description": "0 to 1"},
                "reason": {"type": "string", "description": "One short sentence"},
            },
            "required": ["barrier", "confidence", "reason"],
        },
    }
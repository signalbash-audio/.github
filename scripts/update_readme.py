#!/usr/bin/env python3
"""Generate the Signalbash organization profile README from API data."""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_PATH = os.path.join(BASE_DIR, "profile", "README.template.md")
OUTPUT_PATH = os.path.join(BASE_DIR, "profile", "README.md")

START_MARKER = "<!-- LIVE_STATS_START -->"
END_MARKER = "<!-- LIVE_STATS_END -->"

CONTAINER_KEYS = ("data", "results", "items", "daws", "top", "stats", "activity")
NAME_KEYS = ("daw", "name", "daw_name", "application", "app", "title")
VALUE_KEYS = ("count", "value", "activity", "sessions", "total", "plays")


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def fetch_activity(endpoint, token):
    payload = json.dumps({"token": token}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"API request failed: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("API response was not valid JSON") from exc


def find_entries(payload):
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        raise RuntimeError("API response must be a JSON array or object")

    for key in CONTAINER_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value

    for value in payload.values():
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value

    raise RuntimeError("Could not find a list of activity entries in the API response")


def first_present(item, keys):
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def normalize_activity(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            try:
                number = float(cleaned)
                return int(number) if number.is_integer() else number
            except ValueError:
                return value.strip()
    return None


def normalize_entries(entries):
    rows = []

    for item in entries[:5]:
        if not isinstance(item, dict):
            continue

        name = first_present(item, NAME_KEYS)
        value = first_present(item, VALUE_KEYS)
        activity = normalize_activity(value)

        if name is None or activity is None:
            continue

        rows.append((str(name).strip(), activity))

    if not rows:
        raise RuntimeError("API response did not contain usable DAW activity entries")

    return rows


def escape_markdown_cell(value):
    text = str(value).replace("\\", "\\\\").replace("|", "\\|")
    return " ".join(text.splitlines()).strip()


def format_activity(value):
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    return escape_markdown_cell(value)


def render_stats(rows):
    lines = [
        "| Rank | DAW | Activity |",
        "| ---: | --- | ---: |",
    ]

    for rank, (name, activity) in enumerate(rows, start=1):
        lines.append(
            f"| {rank} | {escape_markdown_cell(name)} | {format_activity(activity)} |"
        )

    now = dt.datetime.now(dt.timezone.utc)
    timestamp = f"{now.strftime('%B')} {now.day}, {now.year} at {now:%H:%M} UTC"
    lines.extend(["", f"_Last updated: {timestamp}._"])
    return "\n".join(lines)


def replace_live_stats(template, stats):
    start = template.find(START_MARKER)
    end = template.find(END_MARKER)

    if start == -1 or end == -1 or end < start:
        raise RuntimeError("Template is missing valid live stats markers")

    before = template[: start + len(START_MARKER)]
    after = template[end:]
    return f"{before}\n{stats}\n{after}"


def main():
    endpoint = required_env("README_DATA_ENDPOINT")
    token = required_env("README_DATA_TOKEN")

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as template_file:
        template = template_file.read()

    payload = fetch_activity(endpoint, token)
    entries = find_entries(payload)
    rows = normalize_entries(entries)
    rendered = replace_live_stats(template, render_stats(rows))

    with open(OUTPUT_PATH, "w", encoding="utf-8") as output_file:
        output_file.write(rendered)
        if not rendered.endswith("\n"):
            output_file.write("\n")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

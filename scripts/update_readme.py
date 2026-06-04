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

CONTAINER_KEYS = (
    "daw_stats",
    "data",
    "results",
    "items",
    "daws",
    "top",
    "stats",
    "activity",
)
NAME_KEYS = (
    "daw",
    "name",
    "daw_name",
    "dawName",
    "host",
    "host_name",
    "hostName",
    "application",
    "app",
    "title",
)
VALUE_KEYS = (
    "total_activity_ms",
    "totalActivityMs",
    "total_activity_seconds",
    "totalActivitySeconds",
    "total_activity",
    "totalActivity",
    "total_time_ms",
    "totalTimeMs",
    "duration_ms",
    "durationMs",
    "count",
    "value",
    "activity",
    "sessions",
    "total",
    "plays",
)
USER_KEYS = (
    "total_users",
    "totalUsers",
    "users",
    "user_count",
    "userCount",
    "unique_users",
    "uniqueUsers",
)


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
            return key, item[key]
    return None, None


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


def normalize_schema_key(value):
    return "".join(char for char in str(value).lower() if char.isalnum())


def schema_index(schema, aliases):
    normalized_aliases = {normalize_schema_key(alias) for alias in aliases}

    for index, name in enumerate(schema):
        if normalize_schema_key(name) in normalized_aliases:
            return index

    return None


def schema_value_kind(name):
    normalized = normalize_schema_key(name)
    if "ms" in normalized or "milliseconds" in normalized:
        return "milliseconds"
    if "seconds" in normalized:
        return "seconds"
    if normalized in ("totaltime", "totalactivity", "activitytime"):
        return "milliseconds"
    return "count"


def value_kind(key):
    normalized = key.lower()
    if normalized.endswith("ms") or "milliseconds" in normalized:
        return "milliseconds"
    if normalized.endswith("seconds") or normalized.endswith("_seconds"):
        return "seconds"
    return "count"


def normalize_schema_entries(payload):
    if not isinstance(payload, dict):
        return None

    schema = payload.get("schema")
    data = payload.get("data")
    if not isinstance(schema, list) or not isinstance(data, list):
        return None

    name_index = schema_index(schema, ("DAW Name", "DAW", "Name", "Host", "Host Name"))
    users_index = schema_index(
        schema,
        ("Total Users", "Users", "User Count", "Unique Users"),
    )
    activity_index = schema_index(
        schema,
        (
            "Total Time",
            "Total Time MS",
            "Total Time Milliseconds",
            "Total Activity",
            "Total Activity MS",
            "Total Activity Milliseconds",
            "Activity",
        ),
    )

    if name_index is None or activity_index is None:
        return None

    rows = []
    activity_kind = schema_value_kind(schema[activity_index])

    for item in data:
        if not isinstance(item, list):
            continue
        if len(item) <= max(name_index, activity_index):
            continue

        name = item[name_index]
        activity = normalize_activity(item[activity_index])
        users = None

        if users_index is not None and len(item) > users_index:
            users = normalize_activity(item[users_index])

        if name is None or activity is None:
            continue

        rows.append(
            {
                "name": str(name).strip(),
                "users": users if isinstance(users, int) else None,
                "activity": activity,
                "kind": activity_kind,
            }
        )
        if len(rows) == 5:
            break

    return rows


def normalize_entries(entries):
    rows = []

    for item in entries:
        if not isinstance(item, dict):
            continue

        _, name = first_present(item, NAME_KEYS)
        _, users = first_present(item, USER_KEYS)
        value_key, value = first_present(item, VALUE_KEYS)
        activity = normalize_activity(value)

        if name is None or activity is None:
            continue

        normalized_users = normalize_activity(users)
        rows.append(
            {
                "name": str(name).strip(),
                "users": normalized_users if isinstance(normalized_users, int) else None,
                "activity": activity,
                "kind": value_kind(value_key),
            }
        )
        if len(rows) == 5:
            break

    if not rows:
        raise RuntimeError(
            "API response did not contain usable DAW activity entries. "
            f"Entry keys found: {describe_entry_keys(entries)}"
        )

    return rows


def normalize_payload(payload):
    rows = normalize_schema_entries(payload)
    if rows is not None:
        return rows

    entries = find_entries(payload)
    return normalize_entries(entries)


def describe_entry_keys(entries):
    key_sets = []

    for item in entries[:3]:
        if isinstance(item, dict):
            key_sets.append(", ".join(sorted(str(key) for key in item.keys())))
        else:
            key_sets.append(type(item).__name__)

    return "; ".join(key_sets) if key_sets else "none"


def escape_markdown_cell(value):
    text = str(value).replace("\\", "\\\\").replace("|", "\\|")
    return " ".join(text.splitlines()).strip()


def format_activity(value):
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    return escape_markdown_cell(value)


def format_duration(total_seconds):
    total_seconds = max(0, int(round(total_seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def format_activity_with_kind(value, kind):
    if isinstance(value, (int, float)):
        if kind == "milliseconds":
            return format_duration(value / 1000)
        if kind == "seconds":
            return format_duration(value)

    return format_activity(value)


def render_stats(rows):
    include_users = any(row.get("users") is not None for row in rows)

    if include_users:
        lines = [
            "| Rank | DAW | Users | Activity |",
            "| ---: | --- | ---: | ---: |",
        ]
    else:
        lines = [
            "| Rank | DAW | Activity |",
            "| ---: | --- | ---: |",
        ]

    for rank, row in enumerate(rows, start=1):
        name = escape_markdown_cell(row["name"])
        activity = format_activity_with_kind(row["activity"], row["kind"])

        if include_users:
            users = row["users"] if row["users"] is not None else ""
            lines.append(f"| {rank} | {name} | {users} | {activity} |")
        else:
            lines.append(f"| {rank} | {name} | {activity} |")

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
    rows = normalize_payload(payload)
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

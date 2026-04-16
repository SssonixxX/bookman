from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
VENDOR_DIR = BASE_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import certifi
import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from PIL import Image

DATABASE_PATH = BASE_DIR / "data" / "booking_manager.db"
ENV_PATHS = [BASE_DIR / ".env", BASE_DIR / "apikey.env", BASE_DIR / "supabase.env"]

CONTACT_STATUSES = [
    "da scremare",
    "da contattare",
    "contattato",
    "in attesa",
    "risposto",
    "interessato",
    "call da fare",
    "trattativa",
    "data opzionata",
    "data chiusa",
    "non interessato",
]
PRIORITIES = ["A", "B", "C"]
CATEGORIES = [
    "Beach Club",
    "Lounge Bar",
    "Club",
    "Lido",
    "Hotel",
    "Evento",
    "Altro",
]
SEASONALITY_OPTIONS = ["Annuale", "Estiva", "Invernale", "Primaverile", "Autunnale", "Altro"]
NEXT_ACTION_OPTIONS = [
    "Prima chiamata introduttiva",
    "Inviare presentazione artistica",
    "Inviare proposta economica",
    "Inviare disponibilita date",
    "Richiamare tra 3 giorni",
    "Richiamare la prossima settimana",
    "Scrivere su WhatsApp",
    "Scrivere via email",
    "Fissare call",
    "Fissare incontro",
    "Inviare contratto",
    "Inviare rider tecnico",
    "Confermare dettagli evento",
]
LOGIN_USERNAME = "Admin"
LOGIN_PASSWORD = "Appalla!"
BOOKING_META_PREFIX = "[[CRM_BOOKING_META]]"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "booking-manager-local-secret")


def load_dotenv() -> None:
    for env_path in ENV_PATHS:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv()


def get_supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").strip()


def get_supabase_service_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def using_supabase() -> bool:
    return bool(get_supabase_url() and get_supabase_service_key())


def is_authenticated() -> bool:
    return bool(session.get("authenticated"))


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.json_ld_blocks: list[str] = []
        self._capture_title = False
        self._capture_json_ld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            content = attributes.get("content", "").strip()
            if key and content:
                self.meta[key.lower()] = content
        elif tag == "title":
            self._capture_title = True
        elif tag == "script" and "ld+json" in attributes.get("type", "").lower():
            self._capture_json_ld = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._capture_title = False
        elif tag == "script":
            self._capture_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._capture_title and data.strip():
            self.title_parts.append(data.strip())
        if self._capture_json_ld and data.strip():
            self.json_ld_blocks.append(data.strip())

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def supabase_headers() -> dict[str, str]:
    key = get_supabase_service_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def supabase_request(
    method: str,
    path: str,
    query: str = "",
    payload: Any | None = None,
    prefer: str | None = None,
) -> Any:
    url = f"{get_supabase_url().rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"
    headers = supabase_headers()
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_object = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request_object, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"Supabase HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise ValueError(f"Supabase non raggiungibile: {exc.reason}") from exc


def supabase_select(table: str, query: str = "select=*") -> list[dict[str, Any]]:
    result = supabase_request("GET", f"/rest/v1/{table}", query=query)
    return result if isinstance(result, list) else []


def serialize_venue_record(record: dict[str, Any]) -> dict[str, Any]:
    venue = dict(record)
    tags_raw = venue.pop("tags_json", "[]")
    venue["active_events"] = bool(venue.get("active_events"))
    try:
        venue["tags"] = json.loads(tags_raw or "[]") if isinstance(tags_raw, str) else (tags_raw or [])
    except json.JSONDecodeError:
        venue["tags"] = []
    return venue


def apply_python_filters(venues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = venues
    exact_keys = ["country", "region", "city", "category", "priority", "status", "seasonality", "custom_area"]
    for key in exact_keys:
        value = request.args.get(key)
        if value:
            filtered = [item for item in filtered if (item.get(key) or "") == value]

    active_events = request.args.get("active_events")
    if active_events in {"true", "false"}:
        expected = active_events == "true"
        filtered = [item for item in filtered if bool(item.get("active_events")) == expected]

    tag = request.args.get("tag", "").strip().lower()
    if tag:
        filtered = [
            item for item in filtered
            if any(tag in str(existing_tag).lower() for existing_tag in item.get("tags", []))
        ]

    search = request.args.get("q", "").strip().lower()
    if search:
        filtered = [
            item for item in filtered
            if any(
                search in (str(item.get(field) or "").lower())
                for field in ["name", "contact_person", "city", "notes", "target_mood"]
            )
        ]

    def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        priority_order = {"A": 1, "B": 2, "C": 3}
        status_order = {"trattativa": 1, "interessato": 2}
        return (
            priority_order.get(item.get("priority") or "", 4),
            status_order.get(item.get("status") or "", 3),
            str(item.get("updated_at") or ""),
        )

    return sorted(filtered, key=sort_key, reverse=False)


def build_facets_from_venues(venues: list[dict[str, Any]]) -> dict[str, list[str]]:
    facet_map = {
        "countries": "country",
        "regions": "region",
        "cities": "city",
        "categories": "category",
        "priorities": "priority",
        "statuses": "status",
        "seasonalities": "seasonality",
        "customAreas": "custom_area",
    }
    facets: dict[str, list[str]] = {}
    for label, field in facet_map.items():
        values = sorted({str(item.get(field) or "").strip() for item in venues if str(item.get(field) or "").strip()})
        facets[label] = values
    return facets


@app.before_request
def require_login():
    allowed_endpoints = {"login", "logout", "static"}
    if request.endpoint in allowed_endpoints:
        return None
    if is_authenticated():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Sessione scaduta o accesso non autorizzato"}), 401
    return redirect(url_for("login"))


def build_closed_date_entries(
    venues: list[dict[str, Any]],
    booking_dates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    venue_map = {item["id"]: item for item in venues if item.get("id") is not None}
    entries: list[dict[str, Any]] = []
    venues_with_real_booking_dates = {item.get("venue_id") for item in booking_dates if item.get("venue_id") is not None}

    for item in booking_dates:
        venue = venue_map.get(item.get("venue_id"), {})
        booking_meta = parse_booking_date_notes(item.get("notes"))
        entries.append(
            {
                "id": item.get("id"),
                "venue_id": item.get("venue_id"),
                "event_title": item.get("event_title", "") or venue.get("name", "Data chiusa"),
                "event_date": item.get("event_date", "") or venue.get("follow_up_date", ""),
                "status": item.get("status", ""),
                "notes": booking_meta["user_notes"],
                "budget": booking_meta["budget"],
                "radio_package": booking_meta["radio_package"],
                "total_budget": booking_meta["total_budget"],
                "venue_name": venue.get("name", ""),
                "city": venue.get("city", ""),
                "country": venue.get("country", ""),
                "derived": False,
            }
        )

    for venue in venues:
        if venue.get("status") != "data chiusa":
            continue
        if venue.get("id") in venues_with_real_booking_dates:
            continue
        entries.append(
            {
                "id": f"derived-{venue['id']}",
                "venue_id": venue.get("id"),
                "event_title": venue.get("name", "Data chiusa"),
                "event_date": venue.get("follow_up_date", "") or "",
                "status": "data chiusa",
                "notes": venue.get("notes") or "Data chiusa registrata nel CRM senza evento dettagliato.",
                "budget": None,
                "radio_package": False,
                "total_budget": None,
                "venue_name": venue.get("name", ""),
                "city": venue.get("city", ""),
                "country": venue.get("country", ""),
                "derived": True,
            }
        )

    entries.sort(key=lambda item: str(item.get("event_date") or ""), reverse=True)
    return entries


def normalize_budget_value(raw_value: Any) -> float | None:
    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, (int, float)):
        return round(float(raw_value), 2)
    cleaned = str(raw_value).strip().replace(",", ".")
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def format_budget_value(value: float | None) -> str | None:
    if value is None:
        return None
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"


def parse_booking_date_notes(raw_notes: Any) -> dict[str, Any]:
    text = str(raw_notes or "")
    default_result = {
        "user_notes": text,
        "budget": None,
        "radio_package": False,
        "total_budget": None,
    }
    if not text.startswith(BOOKING_META_PREFIX):
        return default_result
    _, _, remainder = text.partition("\n")
    meta_line = remainder.splitlines()[0] if remainder else ""
    notes_body = remainder[len(meta_line):].lstrip("\n").strip() if meta_line else ""
    try:
        meta = json.loads(meta_line)
    except json.JSONDecodeError:
        return default_result
    budget = normalize_budget_value(meta.get("budget"))
    radio_package = bool(meta.get("radio_package"))
    total_budget = round((budget or 0) + (200 if radio_package else 0), 2) if budget is not None else None
    return {
        "user_notes": notes_body,
        "budget": budget,
        "radio_package": radio_package,
        "total_budget": total_budget,
    }


def serialize_booking_date_notes(user_notes: str, budget: float | None, radio_package: bool) -> str | None:
    cleaned_notes = (user_notes or "").strip()
    normalized_budget = normalize_budget_value(budget)
    if normalized_budget is None and not radio_package:
        return cleaned_notes or None
    meta = {
        "budget": normalized_budget,
        "radio_package": bool(radio_package),
    }
    payload = f"{BOOKING_META_PREFIX}\n{json.dumps(meta, ensure_ascii=True)}"
    return f"{payload}\n{cleaned_notes}".strip() if cleaned_notes else payload


def compute_closed_dates_totals(booking_dates: list[dict[str, Any]]) -> dict[str, float]:
    gross_total = 0.0
    for item in booking_dates:
        parsed = parse_booking_date_notes(item.get("notes"))
        if parsed["total_budget"] is not None:
            gross_total += float(parsed["total_budget"])
    gross_total = round(gross_total, 2)
    commission_total = round(gross_total * 0.15, 2)
    return {
        "gross_total": gross_total,
        "commission_rate": 0.15,
        "commission_total": commission_total,
    }


def build_auto_booking_date_payload(venue_id: int, venue_data: dict[str, Any]) -> dict[str, Any]:
    venue_name = (venue_data.get("name") or "Data chiusa").strip()
    fallback_date = datetime.utcnow().date().isoformat()
    event_date = (venue_data.get("follow_up_date") or "").strip() or fallback_date
    notes = (venue_data.get("notes") or "").strip() or "Data chiusa generata automaticamente dal cambio stato del CRM."
    return {
        "venue_id": venue_id,
        "event_title": venue_name,
        "event_date": event_date,
        "status": "confirmed",
        "notes": notes,
        "created_at": utc_now(),
    }


def ensure_closed_booking_date_supabase(venue_id: int, venue_data: dict[str, Any]) -> bool:
    if venue_data.get("status") != "data chiusa":
        return False
    existing = supabase_select("booking_dates", f"select=id&venue_id=eq.{venue_id}&limit=1")
    if existing:
        return False
    payload = build_auto_booking_date_payload(venue_id, venue_data)
    supabase_request("POST", "/rest/v1/booking_dates", "", payload=payload, prefer="return=minimal")
    supabase_request(
        "POST",
        "/rest/v1/venue_activities",
        "",
        payload={
            "venue_id": venue_id,
            "activity_type": "booking",
            "title": "Data chiusa creata automaticamente",
            "details": f"{payload['event_title']} - {payload['event_date']}",
            "created_at": utc_now(),
        },
        prefer="return=minimal",
    )
    return True


def ensure_closed_booking_date_sqlite(
    connection: sqlite3.Connection,
    venue_id: int,
    venue_data: dict[str, Any],
) -> bool:
    if venue_data.get("status") != "data chiusa":
        return False
    existing = connection.execute(
        "SELECT id FROM booking_dates WHERE venue_id = ? LIMIT 1",
        (venue_id,),
    ).fetchone()
    if existing is not None:
        return False
    payload = build_auto_booking_date_payload(venue_id, venue_data)
    connection.execute(
        """
        INSERT INTO booking_dates (venue_id, event_title, event_date, status, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            payload["venue_id"],
            payload["event_title"],
            payload["event_date"],
            payload["status"],
            payload["notes"],
            payload["created_at"],
        ),
    )
    log_activity(
        connection,
        venue_id,
        "booking",
        "Data chiusa creata automaticamente",
        f"{payload['event_title']} - {payload['event_date']}",
    )
    return True


def reopen_venue_if_no_booking_dates_supabase(venue_id: int) -> bool:
    remaining = supabase_select("booking_dates", f"select=id&venue_id=eq.{venue_id}&limit=1")
    if remaining:
        return False
    venues = supabase_select("venues", f"select=id,status&id=eq.{venue_id}&limit=1")
    if not venues or venues[0].get("status") != "data chiusa":
        return False
    now = utc_now()
    supabase_request(
        "PATCH",
        "/rest/v1/venues",
        f"id=eq.{venue_id}",
        payload={"status": "da contattare", "updated_at": now},
        prefer="return=minimal",
    )
    supabase_request(
        "POST",
        "/rest/v1/venue_activities",
        "",
        payload={
            "venue_id": venue_id,
            "activity_type": "update",
            "title": "Contatto riaperto",
            "details": "Ultima data chiusa eliminata: stato riportato a da contattare.",
            "created_at": now,
        },
        prefer="return=minimal",
    )
    return True


def reopen_venue_if_no_booking_dates_sqlite(connection: sqlite3.Connection, venue_id: int) -> bool:
    remaining = connection.execute(
        "SELECT id FROM booking_dates WHERE venue_id = ? LIMIT 1",
        (venue_id,),
    ).fetchone()
    if remaining is not None:
        return False
    venue = connection.execute(
        "SELECT status FROM venues WHERE id = ?",
        (venue_id,),
    ).fetchone()
    if venue is None or venue["status"] != "data chiusa":
        return False
    now = utc_now()
    connection.execute(
        "UPDATE venues SET status = ?, updated_at = ? WHERE id = ?",
        ("da contattare", now, venue_id),
    )
    log_activity(
        connection,
        venue_id,
        "update",
        "Contatto riaperto",
        "Ultima data chiusa eliminata: stato riportato a da contattare.",
    )
    return True


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection()) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS venues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                city TEXT,
                admin_area TEXT,
                region TEXT,
                country TEXT,
                address TEXT,
                custom_area TEXT,
                category TEXT,
                target_mood TEXT,
                contact_person TEXT,
                contact_role TEXT,
                phone TEXT,
                whatsapp TEXT,
                email TEXT,
                instagram TEXT,
                website TEXT,
                active_events INTEGER NOT NULL DEFAULT 0,
                seasonality TEXT,
                status TEXT NOT NULL DEFAULT 'da scremare',
                priority TEXT,
                notes TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                next_action TEXT,
                follow_up_date TEXT,
                inserted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS venue_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venue_id INTEGER NOT NULL,
                activity_type TEXT NOT NULL,
                title TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS booking_dates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venue_id INTEGER NOT NULL,
                event_title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed',
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE
            );
            """
        )
        connection.commit()


def seed_if_empty() -> None:
    with closing(get_connection()) as connection:
        count = connection.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        if count:
            return

        now = utc_now()
        samples = [
            {
                "name": "Aurora Beach Club",
                "city": "Rimini",
                "admin_area": "RN",
                "region": "Emilia-Romagna",
                "country": "Italia",
                "address": "Lungomare 12",
                "custom_area": "Riviera",
                "category": "Beach Club",
                "target_mood": "Sunset premium, house commerciale",
                "contact_person": "Marco Bianchi",
                "contact_role": "Event Manager",
                "phone": "+39 333 1112222",
                "whatsapp": "+39 333 1112222",
                "email": "booking@aurorabeach.it",
                "instagram": "@aurorabeachclub",
                "website": "https://aurorabeach.example",
                "active_events": 1,
                "seasonality": "Estiva",
                "status": "interessato",
                "priority": "A",
                "notes": "Target coerente con live set estivi. Interessati a format weekend.",
                "tags_json": json.dumps(["mare", "sunset", "premium"]),
                "next_action": "Inviare proposta economica con pack DJ + voce",
                "follow_up_date": "2026-04-20",
                "inserted_at": now,
                "updated_at": now,
            },
            {
                "name": "Hotel Skyline Rooftop",
                "city": "Milano",
                "admin_area": "MI",
                "region": "Lombardia",
                "country": "Italia",
                "address": "Via Centrale 9",
                "custom_area": "Centro",
                "category": "Hotel",
                "target_mood": "Corporate chic, aperitivo live",
                "contact_person": "Elisa Ferri",
                "contact_role": "Marketing Manager",
                "phone": "+39 347 2003000",
                "whatsapp": "",
                "email": "events@skylinehotel.example",
                "instagram": "@skyline.rooftop",
                "website": "https://skylinehotel.example",
                "active_events": 1,
                "seasonality": "Annuale",
                "status": "da contattare",
                "priority": "B",
                "notes": "Location elegante, possibile fit per showcase o dinner set.",
                "tags_json": json.dumps(["rooftop", "corporate"]),
                "next_action": "Prima chiamata introduttiva",
                "follow_up_date": "2026-04-18",
                "inserted_at": now,
                "updated_at": now,
            },
            {
                "name": "Club Magnetica",
                "city": "Ibiza",
                "admin_area": "Baleari",
                "region": "Baleari",
                "country": "Spagna",
                "address": "Av. Marina 44",
                "custom_area": "West Coast",
                "category": "Club",
                "target_mood": "Nightlife internazionale, elettronica",
                "contact_person": "Sofia Torres",
                "contact_role": "Talent Buyer",
                "phone": "+34 600 123456",
                "whatsapp": "+34 600 123456",
                "email": "talent@magnetica.example",
                "instagram": "@clubmagnetica",
                "website": "https://magnetica.example",
                "active_events": 1,
                "seasonality": "Estiva",
                "status": "trattativa",
                "priority": "A",
                "notes": "Richiesti dettagli su fee, hospitality e supporti tecnici.",
                "tags_json": json.dumps(["internazionale", "clubbing"]),
                "next_action": "Condividere rider e disponibilita luglio",
                "follow_up_date": "2026-04-17",
                "inserted_at": now,
                "updated_at": now,
            },
        ]

        for sample in samples:
            columns = ", ".join(sample.keys())
            placeholders = ", ".join("?" for _ in sample)
            cursor = connection.execute(
                f"INSERT INTO venues ({columns}) VALUES ({placeholders})",
                list(sample.values()),
            )
            venue_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO venue_activities (venue_id, activity_type, title, details, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    venue_id,
                    "system",
                    "Contatto creato",
                    "Inserito come dato dimostrativo iniziale.",
                    now,
                ),
            )

        connection.execute(
            """
            INSERT INTO booking_dates (venue_id, event_title, event_date, status, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "Sunset Live Showcase", "2026-07-11", "confirmed", "Prima data confermata estiva.", now),
        )
        connection.commit()


def parse_tags(raw_tags: Any) -> str:
    if raw_tags is None:
        return "[]"
    if isinstance(raw_tags, list):
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    else:
        tags = [tag.strip() for tag in str(raw_tags).split(",") if tag.strip()]
    return json.dumps(tags, ensure_ascii=True)


def serialize_venue(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    record["active_events"] = bool(record["active_events"])
    record["tags"] = json.loads(record.pop("tags_json") or "[]")
    return record


def build_filters() -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    query_map = {
        "country": "country",
        "region": "region",
        "city": "city",
        "category": "category",
        "priority": "priority",
        "status": "status",
        "seasonality": "seasonality",
        "custom_area": "custom_area",
    }

    for arg_name, column in query_map.items():
        value = request.args.get(arg_name)
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)

    active_events = request.args.get("active_events")
    if active_events in {"true", "false"}:
        clauses.append("active_events = ?")
        params.append(1 if active_events == "true" else 0)

    tag = request.args.get("tag")
    if tag:
        clauses.append("tags_json LIKE ?")
        params.append(f'%"{tag}"%')

    search = request.args.get("q", "").strip()
    if search:
        clauses.append(
            """
            (
                name LIKE ? OR
                contact_person LIKE ? OR
                city LIKE ? OR
                notes LIKE ? OR
                target_mood LIKE ?
            )
            """
        )
        token = f"%{search}%"
        params.extend([token, token, token, token, token])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def log_activity(
    connection: sqlite3.Connection,
    venue_id: int,
    activity_type: str,
    title: str,
    details: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO venue_activities (venue_id, activity_type, title, details, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (venue_id, activity_type, title, details, utc_now()),
    )


def flatten_json_ld(payload: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if "@graph" in payload and isinstance(payload["@graph"], list):
            for item in payload["@graph"]:
                records.extend(flatten_json_ld(item))
        else:
            records.append(payload)
    elif isinstance(payload, list):
        for item in payload:
            records.extend(flatten_json_ld(item))
    return records


def extract_handle_from_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    path = parsed.path.strip("/").split("/")
    if not path or not path[0]:
        return ""
    return f"@{path[0]}"


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = normalize_text(str(value)) if value is not None else ""
        if text:
            return text
    return ""


def clamp_text(value: str, limit: int) -> str:
    text = normalize_text(value)
    return text[:limit]


def infer_category(raw_text: str) -> str:
    text = raw_text.lower()
    keyword_map = {
        "Beach Club": ["beach club", "beachclub", "lido", "spiaggia", "seaside"],
        "Lounge Bar": ["lounge", "cocktail bar", "aperitif", "aperitivo", "bar"],
        "Club": ["club", "nightclub", "discoteca"],
        "Hotel": ["hotel", "resort", "suite", "rooftop hotel"],
        "Evento": ["festival", "event", "evento", "show"],
    }
    for category, keywords in keyword_map.items():
        if any(keyword in text for keyword in keywords):
            return category
    return ""


def derive_name_from_title(title: str, domain: str) -> str:
    if not title and not domain:
        return ""
    separators = ["|", "-", "•", "·", "–", "—", ":"]
    candidate = title
    for separator in separators:
        if separator in candidate:
            candidate = candidate.split(separator)[0]
            break
    candidate = normalize_text(candidate)
    if candidate:
        return candidate
    domain_name = domain.replace("www.", "").split(".")[0]
    return domain_name.replace("-", " ").title()


def detect_source_type(domain: str) -> str:
    normalized = domain.lower()
    if "instagram.com" in normalized:
        return "instagram"
    if "facebook.com" in normalized or "fb.com" in normalized:
        return "facebook"
    return "website"


def extract_contact_details(raw_html: str) -> dict[str, str]:
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", raw_html, re.IGNORECASE)
    instagram_match = re.search(
        r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?",
        raw_html,
        re.IGNORECASE,
    )
    contextual_phone_match = re.search(
        r"(?:whatsapp|phone|telefono|tel|info|reservations|reservation|booking)[^\d+]{0,20}(\+?\d[\d\s()./-]{7,}\d)",
        raw_html,
        re.IGNORECASE,
    )
    generic_phone_match = re.search(r"(\+\d[\d\s()./-]{7,}\d)", raw_html)
    phone_value = ""
    if contextual_phone_match:
        phone_value = normalize_text(contextual_phone_match.group(1))
    elif generic_phone_match:
        phone_value = normalize_text(generic_phone_match.group(1))
    return {
        "email": email_match.group(0) if email_match else "",
        "phone": phone_value,
        "instagram": f"@{instagram_match.group(1)}" if instagram_match else "",
    }


def extract_contact_details_from_text(raw_text: str) -> dict[str, str]:
    normalized_text = normalize_text(raw_text)
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", normalized_text, re.IGNORECASE)
    instagram_match = re.search(r"@([A-Za-z0-9._]+)", normalized_text)
    whatsapp_match = re.search(
        r"(?:whatsapp|wa)[^\d+]{0,15}(\+?\d[\d\s()./-]{7,}\d)",
        normalized_text,
        re.IGNORECASE,
    )
    contextual_phone_match = re.search(
        r"(?:info|reservation|reservations|booking|telefono|tel|phone)[^\d+]{0,20}(\+?\d[\d\s()./-]{7,}\d)",
        normalized_text,
        re.IGNORECASE,
    )
    generic_phone_match = re.search(r"(\+?\d[\d\s()./-]{7,}\d)", normalized_text)
    phone_value = ""
    if contextual_phone_match:
        phone_value = normalize_text(contextual_phone_match.group(1))
    elif generic_phone_match:
        phone_value = normalize_text(generic_phone_match.group(1))
    return {
        "email": email_match.group(0) if email_match else "",
        "phone": phone_value,
        "whatsapp": normalize_text(whatsapp_match.group(1)) if whatsapp_match else "",
        "instagram": f"@{instagram_match.group(1)}" if instagram_match else "",
    }


def merge_contact_details(*items: dict[str, str]) -> dict[str, str]:
    merged = {"email": "", "phone": "", "instagram": ""}
    for item in items:
        if not item:
            continue
        for key in merged:
            if not merged[key]:
                merged[key] = normalize_text(item.get(key, ""))
    return merged


def extract_text_from_html(raw_html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("\\n", " ").replace("\\/", "/").replace("&amp;", "&")
    return normalize_text(text)


def extract_external_urls(raw_html: str, base_domain: str) -> list[str]:
    matches = re.findall(r"https?://[^\s'\"<>]+", raw_html, re.IGNORECASE)
    blocked_domains = ["instagram.com", "facebook.com", "fb.com", "cdninstagram.com"]
    urls: list[str] = []
    for match in matches:
        candidate = match.replace("\\/", "/").rstrip(").,]")
        lower_candidate = candidate.lower()
        if any(blocked in lower_candidate for blocked in blocked_domains):
            continue
        if base_domain.lower() in lower_candidate:
            continue
        if candidate not in urls:
            urls.append(candidate)
    return urls[:3]


def extract_internal_candidate_urls(raw_html: str, base_url: str) -> list[str]:
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    hrefs = re.findall(r"""href=["']([^"'#]+)""", raw_html, re.IGNORECASE)
    keywords = ["contact", "contatti", "about", "chi-siamo", "booking", "prenot", "info", "location", "dove-siamo"]
    urls: list[str] = []
    for href in hrefs:
        candidate = urljoin(base_url, href.replace("\\/", "/").strip())
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != base_domain:
            continue
        lower_path = parsed.path.lower()
        if keywords and not any(keyword in lower_path for keyword in keywords):
            continue
        normalized = parsed._replace(fragment="", query="").geturl().rstrip("/")
        if normalized != base_url.rstrip("/") and normalized not in urls:
            urls.append(normalized)
    return urls[:5]


def extract_image_urls(raw_html: str, base_url: str) -> list[str]:
    candidates = re.findall(r"""(?:src|content)=["']([^"']+\.(?:png|jpg|jpeg|webp))[^"']*["']""", raw_html, re.IGNORECASE)
    urls: list[str] = []
    for candidate in candidates:
        image_url = urljoin(base_url, candidate.replace("\\/", "/").strip())
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        normalized = parsed._replace(fragment="", query="").geturl()
        if normalized not in urls:
            urls.append(normalized)
    return urls[:3]


def find_headless_browser_path() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return ""


def render_page_in_browser(target_url: str) -> dict[str, str]:
    browser_path = find_headless_browser_path()
    if not browser_path:
        return {}

    with tempfile.TemporaryDirectory(prefix="booking-render-", dir=str(BASE_DIR)) as temp_dir:
        temp_path = Path(temp_dir)
        profile_dir = temp_path / "profile"
        screenshot_path = temp_path / "page.png"
        profile_dir.mkdir(parents=True, exist_ok=True)

        common_args = [
            browser_path,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--window-size=1440,3200",
            "--virtual-time-budget=8000",
        ]

        rendered_html = ""
        screenshot_ocr = ""

        try:
            dom_result = subprocess.run(
                [*common_args, "--dump-dom", target_url],
                capture_output=True,
                text=True,
                timeout=35,
                check=False,
            )
            if dom_result.returncode == 0:
                rendered_html = dom_result.stdout or ""
        except Exception:
            rendered_html = ""

        try:
            screenshot_result = subprocess.run(
                [*common_args, f"--screenshot={screenshot_path}", target_url],
                capture_output=True,
                text=True,
                timeout=40,
                check=False,
            )
            if screenshot_result.returncode == 0 and screenshot_path.exists():
                screenshot_ocr = run_tesseract_ocr(screenshot_path.read_bytes())
        except Exception:
            screenshot_ocr = ""

        return {
            "rendered_html": rendered_html,
            "rendered_text": clamp_text(extract_text_from_html(rendered_html), 3000) if rendered_html else "",
            "screenshot_ocr": clamp_text(screenshot_ocr, 3000),
        }


def safe_fetch_page(target_url: str) -> dict[str, Any]:
    content_type, raw_bytes = fetch_html_page(target_url, timeout=12)
    if "text/html" not in content_type.lower():
        raise ValueError("Pagina non HTML")
    html = raw_bytes.decode("utf-8", errors="ignore")
    parser = MetadataParser()
    parser.feed(html)
    return {
        "url": target_url,
        "title": clamp_text(parser.title, 240),
        "meta": {key: clamp_text(value, 280) for key, value in list(parser.meta.items())[:18]},
        "text_excerpt": clamp_text(extract_text_from_html(html), 2000),
        "contact_details": extract_contact_details(html),
        "html": html,
    }


def extract_instagram_embedded_profile(raw_html: str) -> dict[str, str]:
    full_name = re.search(r'"full_name"\s*:\s*"([^"]+)"', raw_html)
    biography = re.search(r'"biography"\s*:\s*"([^"]+)"', raw_html)
    business_phone = re.search(r'"business_phone_number"\s*:\s*"([^"]+)"', raw_html)
    business_email = re.search(r'"business_email"\s*:\s*"([^"]+)"', raw_html)
    external_url = re.search(r'"external_url"\s*:\s*"([^"]+)"', raw_html)
    city_name = re.search(r'"city_name"\s*:\s*"([^"]+)"', raw_html)
    category_name = re.search(r'"category_name"\s*:\s*"([^"]+)"', raw_html)
    return {
        "name": normalize_text(full_name.group(1)) if full_name else "",
        "notes": normalize_text(biography.group(1)).replace("\\u003C", "<") if biography else "",
        "phone": normalize_text(business_phone.group(1)) if business_phone else "",
        "email": normalize_text(business_email.group(1)) if business_email else "",
        "website": normalize_text(external_url.group(1)).replace("\\/", "/") if external_url else "",
        "city": normalize_text(city_name.group(1)) if city_name else "",
        "category": normalize_text(category_name.group(1)) if category_name else "",
    }


def extract_instagram_username(target_url: str) -> str:
    parsed = urlparse(target_url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    return parts[0] if parts else ""


def fetch_instagram_profile_data(target_url: str) -> dict[str, str]:
    username = extract_instagram_username(target_url)
    if not username:
        return {}

    headers = dict(DEFAULT_HEADERS)
    headers.update(
        {
            "Referer": "https://www.instagram.com/",
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    endpoints = [
        f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
        f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}",
    ]

    payload: dict[str, Any] | None = None
    for endpoint in endpoints:
        try:
            response = requests.get(endpoint, headers=headers, timeout=(8, 20), verify=certifi.where())
            response.raise_for_status()
            candidate = response.json()
            if isinstance(candidate, dict):
                payload = candidate
                break
        except Exception:
            continue

    if not payload:
        return {}

    user = (
        payload.get("data", {}).get("user")
        if isinstance(payload.get("data"), dict)
        else payload.get("user")
    )
    if not isinstance(user, dict):
        return {}

    biography = normalize_text(user.get("biography"))
    phone = first_non_empty(
        user.get("business_phone_number"),
        user.get("public_phone_number"),
    )
    email = first_non_empty(
        user.get("business_email"),
        user.get("public_email"),
    )
    website = first_non_empty(
        user.get("external_url"),
        user.get("external_url_linkshimmed"),
    )
    category = first_non_empty(
        user.get("category_name"),
        user.get("business_category_name"),
    )
    city = first_non_empty(
        user.get("city_name"),
        user.get("city"),
    )

    return {
        "name": first_non_empty(user.get("full_name")),
        "notes": biography,
        "phone": phone,
        "email": email,
        "website": website,
        "city": city,
        "category": category,
    }


def extract_instagram_embed_context(raw_html: str) -> dict[str, Any]:
    marker = 'contextJSON":"'
    start = raw_html.find(marker)
    if start < 0:
        return {}

    index = start + len(marker)
    buffer: list[str] = []
    escaped = False
    while index < len(raw_html):
        character = raw_html[index]
        if escaped:
            buffer.append(character)
            escaped = False
        elif character == "\\":
            buffer.append(character)
            escaped = True
        elif character == '"':
            break
        else:
            buffer.append(character)
        index += 1

    try:
        decoded_string = json.loads(f"\"{''.join(buffer)}\"")
        payload = json.loads(decoded_string)
    except Exception:
        return {}
    return payload.get("context", {}) if isinstance(payload, dict) else {}


def fetch_instagram_embed_data(target_url: str) -> dict[str, str]:
    username = extract_instagram_username(target_url)
    if not username:
        return {}
    embed_url = f"https://www.instagram.com/{username}/embed/"
    try:
        response = requests.get(embed_url, headers=DEFAULT_HEADERS, timeout=(8, 20), verify=certifi.where())
        response.raise_for_status()
    except Exception:
        return {}

    context = extract_instagram_embed_context(response.text)
    if not context:
        return {}

    return {
        "name": first_non_empty(context.get("full_name")),
        "instagram": f"@{username}",
    }


def infer_name_from_rendered_text(target_url: str, rendered_text: str) -> str:
    lines = [normalize_text(line) for line in re.split(r"[\r\n]+", rendered_text) if normalize_text(line)]
    if not lines:
        return ""

    parsed = urlparse(target_url)
    username = extract_instagram_username(target_url).lower()
    skip_keywords = {
        "segui",
        "messaggio",
        "follow",
        "message",
        "account seguito",
        "followers",
        "seguaci",
        "seguiti",
        "post",
    }

    if "instagram.com" in parsed.netloc.lower():
        inline_match = re.search(
            rf"{re.escape(username)}\s+(.+?)\s+\d[\d.,]*\s+(?:follower|seguaci)",
            rendered_text,
            re.IGNORECASE,
        )
        if inline_match:
            candidate = normalize_text(inline_match.group(1))
            if candidate and len(candidate) > 2:
                return candidate
        for index, line in enumerate(lines):
            lowered = line.lower()
            if username and username in lowered:
                for next_line in lines[index + 1:index + 6]:
                    candidate = normalize_text(next_line)
                    lowered_candidate = candidate.lower()
                    if not candidate or username in lowered_candidate:
                        continue
                    if any(keyword in lowered_candidate for keyword in skip_keywords):
                        continue
                    if re.search(r"\d+\s+(post|follower|seguaci|seguiti)", lowered_candidate):
                        continue
                    if len(candidate) < 3:
                        continue
                    return candidate
    return ""


def infer_category_from_rendered_text(rendered_text: str) -> str:
    text = normalize_text(rendered_text)
    category_map = [
        ("Club", ["locale notturno", "night club", "nightclub", "discoteca"]),
        ("Beach Club", ["beach club", "stabilimento balneare", "lido"]),
        ("Lounge Bar", ["cocktail bar", "lounge bar", "bar"]),
        ("Hotel", ["hotel", "resort"]),
        ("Evento", ["festival", "evento"]),
    ]
    lowered = text.lower()
    for category, keywords in category_map:
        if any(keyword in lowered for keyword in keywords):
            return category
    return ""


def infer_website_from_text(raw_text: str) -> str:
    match = re.search(r"\b(?:https?://)?(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?\b", raw_text, re.IGNORECASE)
    if not match:
        return ""
    candidate = match.group(0).rstrip(").,")
    if candidate.startswith("@"):
        return ""
    if not candidate.lower().startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    return candidate


def should_use_rendered_fallback(suggested: dict[str, Any], source_type: str, confidence: float) -> bool:
    if source_type in {"instagram", "facebook"}:
        return True
    important_missing = [
        not suggested.get("phone"),
        not suggested.get("email"),
        not suggested.get("category"),
        not suggested.get("website"),
    ]
    return confidence < 0.45 or any(important_missing)


def clean_social_description(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"\b\d[\d.,]*\s+(Followers|Following|Posts|Mi piace|followers|following|posts)\b", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" -|,")


def extract_instagram_fields(
    target_url: str,
    parser: MetadataParser,
    meta: dict[str, str],
    embedded_profile: dict[str, str],
) -> dict[str, Any]:
    title = first_non_empty(meta.get("og:title"), parser.title)
    description = first_non_empty(meta.get("description"), meta.get("og:description"))
    handle = extract_handle_from_url(target_url)

    name = first_non_empty(embedded_profile.get("name"))
    title_match = re.search(r"^(.*?)\s*\((@[A-Za-z0-9._]+)\)", title)
    if title_match:
        name = normalize_text(title_match.group(1))
        handle = title_match.group(2)
    elif not name and handle:
        name = handle.lstrip("@").replace(".", " ").replace("_", " ").title()

    return {
        "name": name,
        "instagram": handle,
        "website": embedded_profile.get("website", ""),
        "notes": first_non_empty(
            clean_social_description(embedded_profile.get("notes", "")),
            clean_social_description(description),
        ),
        "category": first_non_empty(
            embedded_profile.get("category"),
            infer_category(" ".join([title, description])),
        ),
        "phone": embedded_profile.get("phone", ""),
        "email": embedded_profile.get("email", ""),
        "city": embedded_profile.get("city", ""),
    }


def extract_facebook_fields(
    target_url: str,
    parser: MetadataParser,
    meta: dict[str, str],
) -> dict[str, Any]:
    title = first_non_empty(meta.get("og:title"), parser.title)
    description = first_non_empty(meta.get("description"), meta.get("og:description"))
    name = derive_name_from_title(title, urlparse(target_url).netloc)
    return {
        "name": name,
        "website": "",
        "notes": clean_social_description(description),
        "category": infer_category(" ".join([title, description])),
    }


def extract_json_ld_fields(records: list[dict[str, Any]]) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for record in records:
        record_type = record.get("@type")
        types = record_type if isinstance(record_type, list) else [record_type]
        normalized_types = {str(item).lower() for item in types if item}
        if normalized_types & {
            "localbusiness",
            "organization",
            "restaurant",
            "barorpub",
            "nightclub",
            "hotel",
            "eventvenue",
        }:
            address = record.get("address") if isinstance(record.get("address"), dict) else {}
            extracted["name"] = extracted.get("name") or normalize_text(record.get("name"))
            extracted["website"] = extracted.get("website") or normalize_text(record.get("url"))
            extracted["phone"] = extracted.get("phone") or normalize_text(record.get("telephone"))
            extracted["email"] = extracted.get("email") or normalize_text(record.get("email"))
            extracted["address"] = extracted.get("address") or normalize_text(address.get("streetAddress"))
            extracted["city"] = extracted.get("city") or normalize_text(address.get("addressLocality"))
            extracted["region"] = extracted.get("region") or normalize_text(address.get("addressRegion"))
            extracted["country"] = extracted.get("country") or normalize_text(address.get("addressCountry"))
            extracted["admin_area"] = extracted.get("admin_area") or normalize_text(address.get("postalCode"))
            extracted["notes"] = extracted.get("notes") or normalize_text(record.get("description"))
            same_as = record.get("sameAs")
            if isinstance(same_as, list):
                instagram_url = next((item for item in same_as if "instagram.com" in str(item).lower()), "")
                if instagram_url:
                    extracted["instagram"] = extracted.get("instagram") or extract_handle_from_url(instagram_url)
    return extracted


def compute_import_confidence(suggested: dict[str, Any], source_type: str) -> float:
    score = 0.18 if suggested.get("name") else 0.0
    score += 0.12 if suggested.get("phone") else 0.0
    score += 0.12 if suggested.get("email") else 0.0
    score += 0.1 if suggested.get("city") else 0.0
    score += 0.1 if suggested.get("country") else 0.0
    score += 0.08 if suggested.get("address") else 0.0
    score += 0.08 if suggested.get("website") else 0.0
    score += 0.05 if suggested.get("instagram") else 0.0
    score += 0.07 if suggested.get("category") else 0.0
    score += 0.1 if suggested.get("notes") else 0.0
    if source_type in {"instagram", "facebook"}:
        score -= 0.08
    return max(0.0, min(round(score, 2), 0.99))


def run_tesseract_ocr(image_bytes: bytes) -> str:
    tesseract_path = os.environ.get("TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if not Path(tesseract_path).exists():
        return ""
    temp_input_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_input:
            temp_input_path = temp_input.name
            with Image.open(io.BytesIO(image_bytes)) as image:
                normalized = image.convert("L")
                normalized.save(temp_input, format="PNG")
        completed = subprocess.run(
            [tesseract_path, temp_input_path, "stdout", "-l", "ita+eng", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            return ""
        return clamp_text(normalize_text(completed.stdout), 1200)
    except Exception:
        return ""
    finally:
        if temp_input_path:
            try:
                Path(temp_input_path).unlink(missing_ok=True)
            except Exception:
                pass


def extract_ocr_text_from_images(raw_html: str, base_url: str) -> str:
    collected: list[str] = []
    for image_url in extract_image_urls(raw_html, base_url):
        try:
            response = requests.get(image_url, headers=DEFAULT_HEADERS, timeout=(8, 15), verify=certifi.where())
            response.raise_for_status()
            ocr_text = run_tesseract_ocr(response.content)
            if ocr_text:
                collected.append(ocr_text)
        except Exception:
            continue
    return clamp_text(" ".join(collected), 2000)


def fetch_supporting_pages(target_url: str, raw_html: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    candidate_urls = extract_internal_candidate_urls(raw_html, target_url)
    for candidate_url in candidate_urls:
        try:
            pages.append(safe_fetch_page(candidate_url))
        except Exception:
            continue
    return pages


def fetch_html_page(target_url: str, timeout: int = 10) -> tuple[str, bytes]:
    try:
        response = requests.get(
            target_url,
            headers=DEFAULT_HEADERS,
            timeout=(timeout, timeout + 8),
            allow_redirects=True,
            verify=certifi.where(),
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        return content_type, response.content
    except requests.RequestException:
        request_object = Request(target_url, headers=DEFAULT_HEADERS)
        with urlopen(request_object, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            raw_bytes = response.read()
        return content_type, raw_bytes


def fetch_url_metadata(target_url: str) -> dict[str, Any]:
    content_type, raw_bytes = fetch_html_page(target_url, timeout=10)
    if "text/html" not in content_type.lower():
        raise ValueError("Il link non punta a una pagina HTML analizzabile.")

    html = raw_bytes.decode("utf-8", errors="ignore")
    parser = MetadataParser()
    parser.feed(html)
    records: list[dict[str, Any]] = []
    for block in parser.json_ld_blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        records.extend(flatten_json_ld(payload))

    parsed_url = urlparse(target_url)
    source_type = detect_source_type(parsed_url.netloc)
    json_ld_fields = extract_json_ld_fields(records)
    base_contact_details = extract_contact_details(html)
    supporting_pages = fetch_supporting_pages(target_url, html) if source_type == "website" else []
    supporting_contact_details = merge_contact_details(*(page.get("contact_details", {}) for page in supporting_pages))
    contact_details = merge_contact_details(base_contact_details, supporting_contact_details)
    supporting_text = " ".join(page.get("text_excerpt", "") for page in supporting_pages)
    ocr_text = extract_ocr_text_from_images(html, target_url) if source_type == "website" else ""
    instagram_embedded = {}
    if source_type == "instagram":
        instagram_embedded = extract_instagram_embedded_profile(html)
        instagram_api_data = fetch_instagram_profile_data(target_url)
        instagram_embed_data = fetch_instagram_embed_data(target_url)
        if instagram_api_data:
            instagram_embedded = {
                "name": first_non_empty(instagram_api_data.get("name"), instagram_embedded.get("name")),
                "notes": first_non_empty(instagram_api_data.get("notes"), instagram_embedded.get("notes")),
                "phone": first_non_empty(instagram_api_data.get("phone"), instagram_embedded.get("phone")),
                "email": first_non_empty(instagram_api_data.get("email"), instagram_embedded.get("email")),
                "website": first_non_empty(instagram_api_data.get("website"), instagram_embedded.get("website")),
                "city": first_non_empty(instagram_api_data.get("city"), instagram_embedded.get("city")),
                "category": first_non_empty(instagram_api_data.get("category"), instagram_embedded.get("category")),
            }
        if instagram_embed_data:
            instagram_embedded = {
                "name": first_non_empty(instagram_embed_data.get("name"), instagram_embedded.get("name")),
                "notes": first_non_empty(instagram_embed_data.get("notes"), instagram_embedded.get("notes")),
                "phone": first_non_empty(instagram_embed_data.get("phone"), instagram_embedded.get("phone")),
                "email": first_non_empty(instagram_embed_data.get("email"), instagram_embedded.get("email")),
                "website": first_non_empty(instagram_embed_data.get("website"), instagram_embedded.get("website")),
                "city": first_non_empty(instagram_embed_data.get("city"), instagram_embedded.get("city")),
                "category": first_non_empty(instagram_embed_data.get("category"), instagram_embedded.get("category")),
            }
    meta = parser.meta
    social_fields: dict[str, Any] = {}
    if source_type == "instagram":
        social_fields = extract_instagram_fields(target_url, parser, meta, instagram_embedded)
    elif source_type == "facebook":
        social_fields = extract_facebook_fields(target_url, parser, meta)
    combined_text = " ".join(
        [
            parser.title,
            meta.get("description", ""),
            meta.get("og:description", ""),
            json_ld_fields.get("notes", ""),
            parsed_url.netloc,
            supporting_text,
            ocr_text,
        ]
    )

    city = first_non_empty(
        json_ld_fields.get("city"),
        meta.get("business:contact_data:locality"),
        meta.get("place:location:locality"),
    )
    region = first_non_empty(
        json_ld_fields.get("region"),
        meta.get("business:contact_data:region"),
        meta.get("place:location:region"),
    )
    country = first_non_empty(
        json_ld_fields.get("country"),
        meta.get("business:contact_data:country_name"),
        meta.get("og:locale"),
    )

    suggested = {
        "name": first_non_empty(
            social_fields.get("name"),
            json_ld_fields.get("name"),
            meta.get("og:site_name"),
            meta.get("og:title"),
            derive_name_from_title(parser.title, parsed_url.netloc),
        ),
        "city": city,
        "admin_area": first_non_empty(json_ld_fields.get("admin_area")),
        "region": region,
        "country": country.replace("_", "-") if country else "",
        "address": first_non_empty(
            json_ld_fields.get("address"),
            meta.get("business:contact_data:street_address"),
        ),
        "custom_area": "",
        "category": first_non_empty(
            social_fields.get("category"),
            json_ld_fields.get("category"),
            infer_category(combined_text),
        ),
        "target_mood": "",
        "contact_person": "",
        "contact_role": "",
        "phone": first_non_empty(social_fields.get("phone"), json_ld_fields.get("phone"), contact_details["phone"]),
        "whatsapp": "",
        "email": first_non_empty(social_fields.get("email"), json_ld_fields.get("email"), contact_details["email"]),
        "instagram": first_non_empty(
            social_fields.get("instagram"),
            json_ld_fields.get("instagram"),
            contact_details["instagram"],
            extract_handle_from_url(target_url) if "instagram.com" in parsed_url.netloc.lower() else "",
        ),
        "website": first_non_empty(social_fields.get("website"), target_url if source_type == "website" else ""),
        "active_events": any(keyword in combined_text.lower() for keyword in ["event", "festival", "line up", "tickets"]),
        "seasonality": "",
        "status": "da scremare",
        "priority": "",
        "notes": first_non_empty(
            social_fields.get("notes"),
            meta.get("description"),
            meta.get("og:description"),
            json_ld_fields.get("notes"),
            supporting_text,
            ocr_text,
        ),
        "tags": [],
        "next_action": "",
        "follow_up_date": "",
        "source_url": target_url,
    }

    if suggested["category"] == "Beach Club" and not suggested["seasonality"]:
        suggested["seasonality"] = "Estiva"
    if suggested["category"] == "Hotel" and not suggested["seasonality"]:
        suggested["seasonality"] = "Annuale"

    local_confidence = compute_import_confidence(suggested, source_type)
    rendered_used = False
    rendered_ocr_used = False
    if should_use_rendered_fallback(suggested, source_type, local_confidence):
        render_target_url = target_url
        if source_type == "instagram":
            username = extract_instagram_username(target_url)
            if username:
                render_target_url = f"https://www.instagram.com/{username}/embed/"
        rendered_artifacts = render_page_in_browser(render_target_url)
        rendered_text = " ".join(
            [
                rendered_artifacts.get("rendered_text", ""),
                rendered_artifacts.get("screenshot_ocr", ""),
            ]
        )
        if rendered_text.strip():
            rendered_contacts = extract_contact_details_from_text(rendered_text)
            rendered_name = infer_name_from_rendered_text(target_url, rendered_text)
            rendered_category = infer_category_from_rendered_text(rendered_text)
            rendered_website = infer_website_from_text(rendered_text)
            suggested.update(
                {
                    "name": first_non_empty(rendered_name, suggested.get("name")),
                    "category": first_non_empty(rendered_category, suggested.get("category")),
                    "phone": first_non_empty(rendered_contacts.get("phone"), suggested.get("phone")),
                    "whatsapp": first_non_empty(rendered_contacts.get("whatsapp"), suggested.get("whatsapp")),
                    "email": first_non_empty(rendered_contacts.get("email"), suggested.get("email")),
                    "instagram": first_non_empty(rendered_contacts.get("instagram"), suggested.get("instagram")),
                    "website": first_non_empty(rendered_website, suggested.get("website")),
                    "notes": first_non_empty(suggested.get("notes"), rendered_text),
                }
            )
            local_confidence = compute_import_confidence(suggested, source_type)
            rendered_used = bool(rendered_artifacts.get("rendered_text"))
            rendered_ocr_used = bool(rendered_artifacts.get("screenshot_ocr"))

    evidence = {
        "source_type": source_type,
        "source_url": target_url,
        "title": parser.title,
        "meta_keys": sorted(parser.meta.keys())[:12],
        "json_ld_records": len(records),
        "local_confidence": local_confidence,
        "pages_scanned": len(supporting_pages),
        "ocr_used": bool(ocr_text or rendered_ocr_used),
        "rendered_used": rendered_used,
    }
    evidence["confidence"] = local_confidence
    return {"suggested": suggested, "evidence": evidence, "source": source_type, "ai_used": False}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if username == LOGIN_USERNAME and password == LOGIN_PASSWORD:
            session["authenticated"] = True
            session["username"] = username
            return redirect(url_for("index"))
        return render_template("login.html", error="Credenziali non valide.")
    if is_authenticated():
        return redirect(url_for("index"))
    return render_template("login.html", error=None)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    return render_template(
        "index.html",
        username=session.get("username", LOGIN_USERNAME),
        contact_statuses=CONTACT_STATUSES,
        priorities=PRIORITIES,
        categories=CATEGORIES,
        seasonalities=SEASONALITY_OPTIONS,
        next_actions=NEXT_ACTION_OPTIONS,
    )


@app.get("/api/meta")
def api_meta():
    return jsonify(
        {
            "statuses": CONTACT_STATUSES,
            "priorities": PRIORITIES,
            "categories": CATEGORIES,
            "seasonalities": SEASONALITY_OPTIONS,
            "next_actions": NEXT_ACTION_OPTIONS,
        }
    )


@app.post("/api/reset-crm")
def api_reset_crm():
    if using_supabase():
        supabase_request("DELETE", "/rest/v1/booking_dates", "id=not.is.null", prefer="return=minimal")
        supabase_request("DELETE", "/rest/v1/venue_activities", "id=not.is.null", prefer="return=minimal")
        supabase_request("DELETE", "/rest/v1/venues", "id=not.is.null", prefer="return=minimal")
        return jsonify({"ok": True})

    with closing(get_connection()) as connection:
        connection.execute("DELETE FROM booking_dates")
        connection.execute("DELETE FROM venue_activities")
        connection.execute("DELETE FROM venues")
        connection.commit()
    return jsonify({"ok": True})


@app.post("/api/import-from-url")
def api_import_from_url():
    payload = request.get_json(force=True)
    target_url = (payload.get("url") or "").strip()
    if not target_url:
        return jsonify({"error": "Inserisci un link da analizzare"}), 400
    if not target_url.startswith(("http://", "https://")):
        target_url = f"https://{target_url}"

    try:
        result = fetch_url_metadata(target_url)
    except Exception as exc:
        return jsonify(
            {
                "error": (
                    "Non sono riuscito a leggere automaticamente questo link. "
                    "Verifica che il sito sia raggiungibile e che la pagina sia pubblica."
                ),
                "details": str(exc),
            }
        ), 400

    return jsonify(result)


@app.get("/api/dashboard")
def api_dashboard():
    if using_supabase():
        venues = [serialize_venue_record(item) for item in supabase_select("venues", "select=*")]
        activities = supabase_select("venue_activities", "select=title,details,created_at,venue_id&order=created_at.desc&limit=20")
        booking_dates = supabase_select("booking_dates", "select=*&status=eq.confirmed")
        closed_date_totals = compute_closed_dates_totals(booking_dates)
        venue_names = {item["id"]: item.get("name", "") for item in venues}
        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for venue in venues:
            by_status[venue.get("status", "")] = by_status.get(venue.get("status", ""), 0) + 1
            by_priority[venue.get("priority") or "senza"] = by_priority.get(venue.get("priority") or "senza", 0) + 1
        today = datetime.utcnow().date().isoformat()
        scheduled = sum(1 for venue in venues if venue.get("follow_up_date"))
        overdue = sum(1 for venue in venues if venue.get("follow_up_date") and venue["follow_up_date"] < today)
        due_today = sum(1 for venue in venues if venue.get("follow_up_date") == today)
        recent_updates = [
            {
                "title": item.get("title", ""),
                "details": item.get("details"),
                "created_at": item.get("created_at", ""),
                "name": venue_names.get(item.get("venue_id"), ""),
            }
            for item in activities[:6]
        ]
        return jsonify(
            {
                "total_contacts": len(venues),
                "status_counts": by_status,
                "priority_counts": by_priority,
                "follow_up_summary": {"scheduled": scheduled, "overdue": overdue, "today": due_today},
                "closed_dates": len(booking_dates),
                "closed_dates_gross_total": closed_date_totals["gross_total"],
                "agent_commission_rate": closed_date_totals["commission_rate"],
                "agent_commission_total": closed_date_totals["commission_total"],
                "recent_updates": recent_updates,
            }
        )

    with closing(get_connection()) as connection:
        total = connection.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
        by_status = {
            row["status"]: row["total"]
            for row in connection.execute(
                "SELECT status, COUNT(*) AS total FROM venues GROUP BY status ORDER BY total DESC"
            )
        }
        by_priority = {
            (row["priority"] or "senza"): row["total"]
            for row in connection.execute(
                "SELECT priority, COUNT(*) AS total FROM venues GROUP BY priority"
            )
        }
        follow_ups = connection.execute(
            """
            SELECT
                SUM(CASE WHEN follow_up_date IS NOT NULL THEN 1 ELSE 0 END) AS scheduled,
                SUM(CASE WHEN follow_up_date < date('now') THEN 1 ELSE 0 END) AS overdue,
                SUM(CASE WHEN follow_up_date = date('now') THEN 1 ELSE 0 END) AS today
            FROM venues
            """
        ).fetchone()
        closed_dates = connection.execute(
            "SELECT COUNT(*) FROM booking_dates WHERE status = 'confirmed'"
        ).fetchone()[0]
        booking_date_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT notes FROM booking_dates WHERE status = 'confirmed'"
            )
        ]
        closed_date_totals = compute_closed_dates_totals(booking_date_rows)

        recent_updates = [
            dict(row)
            for row in connection.execute(
                """
                SELECT venue_activities.title, venue_activities.details, venue_activities.created_at, venues.name
                FROM venue_activities
                JOIN venues ON venues.id = venue_activities.venue_id
                ORDER BY venue_activities.created_at DESC
                LIMIT 6
                """
            )
        ]

    return jsonify(
        {
            "total_contacts": total,
            "status_counts": by_status,
            "priority_counts": by_priority,
            "follow_up_summary": dict(follow_ups),
            "closed_dates": closed_dates,
            "closed_dates_gross_total": closed_date_totals["gross_total"],
            "agent_commission_rate": closed_date_totals["commission_rate"],
            "agent_commission_total": closed_date_totals["commission_total"],
            "recent_updates": recent_updates,
        }
    )


@app.get("/api/venues")
def api_venues():
    if using_supabase():
        venues = [serialize_venue_record(item) for item in supabase_select("venues", "select=*")]
        filtered = apply_python_filters(venues)
        facets = build_facets_from_venues(venues)
        return jsonify({"items": filtered, "facets": facets})

    where_sql, params = build_filters()
    with closing(get_connection()) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM venues
            {where_sql}
            ORDER BY
                CASE priority WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END,
                CASE status WHEN 'trattativa' THEN 1 WHEN 'interessato' THEN 2 ELSE 3 END,
                updated_at DESC
            """,
            params,
        ).fetchall()

        facets = {
            key: [
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT {column} FROM venues WHERE {column} IS NOT NULL AND {column} <> '' ORDER BY {column}"
                )
            ]
            for key, column in {
                "countries": "country",
                "regions": "region",
                "cities": "city",
                "categories": "category",
                "priorities": "priority",
                "statuses": "status",
                "seasonalities": "seasonality",
                "customAreas": "custom_area",
            }.items()
        }

    return jsonify({"items": [serialize_venue(row) for row in rows], "facets": facets})


@app.get("/api/venues/<int:venue_id>")
def api_venue_detail(venue_id: int):
    if using_supabase():
        venues = [serialize_venue_record(item) for item in supabase_select("venues", f"select=*&id=eq.{venue_id}&limit=1")]
        if not venues:
            return jsonify({"error": "Contatto non trovato"}), 404
        activities = supabase_select(
            "venue_activities",
            f"select=id,activity_type,title,details,created_at,venue_id&venue_id=eq.{venue_id}&order=created_at.desc",
        )
        booking_dates = supabase_select(
            "booking_dates",
            f"select=id,event_title,event_date,status,notes,created_at,venue_id&venue_id=eq.{venue_id}&order=event_date.desc",
        )
        closed_entries = build_closed_date_entries(venues, booking_dates)
        return jsonify({"venue": venues[0], "activities": activities, "booking_dates": closed_entries})

    with closing(get_connection()) as connection:
        venue = connection.execute("SELECT * FROM venues WHERE id = ?", (venue_id,)).fetchone()
        if venue is None:
            return jsonify({"error": "Contatto non trovato"}), 404

        activities = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, activity_type, title, details, created_at
                FROM venue_activities
                WHERE venue_id = ?
                ORDER BY created_at DESC
                """,
                (venue_id,),
            )
        ]
        booking_dates = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, event_title, event_date, status, notes, created_at
                FROM booking_dates
                WHERE venue_id = ?
                ORDER BY event_date DESC
                """,
                (venue_id,),
            )
        ]
        closed_entries = build_closed_date_entries([serialize_venue(venue)], [{**item, "venue_id": venue_id} for item in booking_dates])

    return jsonify(
        {
            "venue": serialize_venue(venue),
            "activities": activities,
            "booking_dates": closed_entries,
        }
    )


def read_payload() -> dict[str, Any]:
    payload = request.get_json(force=True)
    now = utc_now()
    return {
        "name": (payload.get("name") or "").strip(),
        "city": (payload.get("city") or "").strip(),
        "admin_area": (payload.get("admin_area") or "").strip(),
        "region": (payload.get("region") or "").strip(),
        "country": (payload.get("country") or "").strip(),
        "address": (payload.get("address") or "").strip(),
        "custom_area": (payload.get("custom_area") or "").strip(),
        "category": (payload.get("category") or "").strip(),
        "target_mood": (payload.get("target_mood") or "").strip(),
        "contact_person": (payload.get("contact_person") or "").strip(),
        "contact_role": (payload.get("contact_role") or "").strip(),
        "phone": (payload.get("phone") or "").strip(),
        "whatsapp": (payload.get("whatsapp") or "").strip(),
        "email": (payload.get("email") or "").strip(),
        "instagram": (payload.get("instagram") or "").strip(),
        "website": (payload.get("website") or "").strip(),
        "active_events": bool(payload.get("active_events")),
        "seasonality": (payload.get("seasonality") or "").strip(),
        "status": (payload.get("status") or "da scremare").strip(),
        "priority": (payload.get("priority") or "").strip() or None,
        "notes": (payload.get("notes") or "").strip(),
        "tags_json": parse_tags(payload.get("tags")),
        "next_action": (payload.get("next_action") or "").strip(),
        "follow_up_date": (payload.get("follow_up_date") or "").strip() or None,
        "updated_at": now,
        "inserted_at": payload.get("inserted_at") or now,
    }


@app.post("/api/venues")
def api_create_venue():
    data = read_payload()
    if not data["name"]:
        return jsonify({"error": "Il nome locale e obbligatorio"}), 400

    if using_supabase():
        created = supabase_request("POST", "/rest/v1/venues", "select=id", payload=data, prefer="return=representation")
        venue_id = created[0]["id"]
        auto_created_booking = ensure_closed_booking_date_supabase(venue_id, data)
        supabase_request(
            "POST",
            "/rest/v1/venue_activities",
            "",
            payload={
                "venue_id": venue_id,
                "activity_type": "system",
                "title": "Contatto creato",
                "details": "Nuovo locale inserito nel CRM.",
                "created_at": utc_now(),
            },
            prefer="return=minimal",
        )
        return jsonify({"id": venue_id, "auto_created_booking_date": auto_created_booking}), 201

    with closing(get_connection()) as connection:
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        cursor = connection.execute(
            f"INSERT INTO venues ({columns}) VALUES ({placeholders})",
            list(data.values()),
        )
        venue_id = cursor.lastrowid
        log_activity(connection, venue_id, "system", "Contatto creato", "Nuovo locale inserito nel CRM.")
        auto_created_booking = ensure_closed_booking_date_sqlite(connection, venue_id, data)
        connection.commit()

    return jsonify({"id": venue_id, "auto_created_booking_date": auto_created_booking}), 201


@app.put("/api/venues/<int:venue_id>")
def api_update_venue(venue_id: int):
    data = read_payload()
    if not data["name"]:
        return jsonify({"error": "Il nome locale e obbligatorio"}), 400

    if using_supabase():
        existing_rows = supabase_select("venues", f"select=*&id=eq.{venue_id}&limit=1")
        if not existing_rows:
            return jsonify({"error": "Contatto non trovato"}), 404
        existing = existing_rows[0]
        data["inserted_at"] = existing["inserted_at"]
        supabase_request("PATCH", "/rest/v1/venues", f"id=eq.{venue_id}", payload=data, prefer="return=minimal")
        changes: list[str] = []
        if existing.get("status") != data["status"]:
            changes.append(f"Stato: {existing.get('status')} -> {data['status']}")
        if (existing.get("priority") or "") != (data["priority"] or ""):
            old_priority = existing.get("priority") or "non assegnata"
            new_priority = data["priority"] or "non assegnata"
            changes.append(f"Priorita: {old_priority} -> {new_priority}")
        if existing.get("follow_up_date") != data["follow_up_date"]:
            changes.append(
                f"Follow-up: {(existing.get('follow_up_date') or 'nessuno')} -> {(data['follow_up_date'] or 'nessuno')}"
            )
        supabase_request(
            "POST",
            "/rest/v1/venue_activities",
            "",
            payload={
                "venue_id": venue_id,
                "activity_type": "update",
                "title": "Contatto aggiornato",
                "details": " | ".join(changes) if changes else "Scheda aggiornata.",
                "created_at": utc_now(),
            },
            prefer="return=minimal",
        )
        auto_created_booking = ensure_closed_booking_date_supabase(venue_id, data)
        return jsonify({"ok": True, "auto_created_booking_date": auto_created_booking})

    with closing(get_connection()) as connection:
        existing = connection.execute("SELECT * FROM venues WHERE id = ?", (venue_id,)).fetchone()
        if existing is None:
            return jsonify({"error": "Contatto non trovato"}), 404

        data["inserted_at"] = existing["inserted_at"]
        assignments = ", ".join(f"{column} = ?" for column in data.keys())
        connection.execute(
            f"UPDATE venues SET {assignments} WHERE id = ?",
            [*data.values(), venue_id],
        )

        changes: list[str] = []
        if existing["status"] != data["status"]:
            changes.append(f"Stato: {existing['status']} -> {data['status']}")
        if (existing["priority"] or "") != (data["priority"] or ""):
            old_priority = existing["priority"] or "non assegnata"
            new_priority = data["priority"] or "non assegnata"
            changes.append(f"Priorita: {old_priority} -> {new_priority}")
        if existing["follow_up_date"] != data["follow_up_date"]:
            changes.append(
                f"Follow-up: {(existing['follow_up_date'] or 'nessuno')} -> {(data['follow_up_date'] or 'nessuno')}"
            )

        details = " | ".join(changes) if changes else "Scheda aggiornata."
        log_activity(connection, venue_id, "update", "Contatto aggiornato", details)
        auto_created_booking = ensure_closed_booking_date_sqlite(connection, venue_id, data)
        connection.commit()

    return jsonify({"ok": True, "auto_created_booking_date": auto_created_booking})


@app.delete("/api/venues/<int:venue_id>")
def api_delete_venue(venue_id: int):
    if using_supabase():
        existing = supabase_select("venues", f"select=id&id=eq.{venue_id}&limit=1")
        if not existing:
            return jsonify({"error": "Contatto non trovato"}), 404
        supabase_request("DELETE", "/rest/v1/venues", f"id=eq.{venue_id}", prefer="return=minimal")
        return jsonify({"ok": True})

    with closing(get_connection()) as connection:
        deleted = connection.execute("DELETE FROM venues WHERE id = ?", (venue_id,))
        connection.commit()
        if deleted.rowcount == 0:
            return jsonify({"error": "Contatto non trovato"}), 404
    return jsonify({"ok": True})


@app.delete("/api/booking-dates/<booking_date_id>")
def api_delete_booking_date(booking_date_id: str):
    if using_supabase():
        existing = supabase_select(
            "booking_dates",
            f"select=id,venue_id,event_title,event_date&id=eq.{booking_date_id}&limit=1",
        )
        if not existing:
            return jsonify({"error": "Data chiusa non trovata"}), 404
        booking_date = existing[0]
        supabase_request("DELETE", "/rest/v1/booking_dates", f"id=eq.{booking_date_id}", prefer="return=minimal")
        supabase_request(
            "POST",
            "/rest/v1/venue_activities",
            "",
            payload={
                "venue_id": booking_date["venue_id"],
                "activity_type": "booking",
                "title": "Data chiusa eliminata",
                "details": f"{booking_date.get('event_title', 'Evento')} - {booking_date.get('event_date', '')}",
                "created_at": utc_now(),
            },
            prefer="return=minimal",
        )
        reopened = reopen_venue_if_no_booking_dates_supabase(booking_date["venue_id"])
        return jsonify({"ok": True, "reopened_venue": reopened})

    with closing(get_connection()) as connection:
        booking_date = connection.execute(
            """
            SELECT id, venue_id, event_title, event_date
            FROM booking_dates
            WHERE id = ?
            """,
            (booking_date_id,),
        ).fetchone()
        if booking_date is None:
            return jsonify({"error": "Data chiusa non trovata"}), 404
        connection.execute("DELETE FROM booking_dates WHERE id = ?", (booking_date_id,))
        log_activity(
            connection,
            booking_date["venue_id"],
            "booking",
            "Data chiusa eliminata",
            f"{booking_date['event_title']} - {booking_date['event_date']}",
        )
        reopened = reopen_venue_if_no_booking_dates_sqlite(connection, booking_date["venue_id"])
        connection.commit()
    return jsonify({"ok": True, "reopened_venue": reopened})


@app.patch("/api/booking-dates/<booking_date_id>")
def api_update_booking_date(booking_date_id: str):
    payload = request.get_json(force=True)
    budget = normalize_budget_value(payload.get("budget"))
    radio_package = bool(payload.get("radio_package"))

    if using_supabase():
        existing = supabase_select(
            "booking_dates",
            f"select=id,venue_id,event_title,event_date,notes&id=eq.{booking_date_id}&limit=1",
        )
        if not existing:
            return jsonify({"error": "Data chiusa non trovata"}), 404
        booking_date = existing[0]
        existing_meta = parse_booking_date_notes(booking_date.get("notes"))
        user_notes = (
            (payload.get("notes") or "").strip()
            if "notes" in payload
            else existing_meta["user_notes"]
        )
        serialized_notes = serialize_booking_date_notes(user_notes, budget, radio_package)
        supabase_request(
            "PATCH",
            "/rest/v1/booking_dates",
            f"id=eq.{booking_date_id}",
            payload={"notes": serialized_notes},
            prefer="return=minimal",
        )
        total_budget = round((budget or 0) + (200 if radio_package else 0), 2) if budget is not None else None
        supabase_request(
            "POST",
            "/rest/v1/venue_activities",
            "",
            payload={
                "venue_id": booking_date["venue_id"],
                "activity_type": "booking",
                "title": "Data chiusa aggiornata",
                "details": (
                    f"{booking_date.get('event_title', 'Evento')} - budget {format_budget_value(total_budget) or 'n/d'} euro"
                    + (" con pacchetto radio" if radio_package else "")
                ),
                "created_at": utc_now(),
            },
            prefer="return=minimal",
        )
        return jsonify({"ok": True, "total_budget": total_budget})

    with closing(get_connection()) as connection:
        booking_date = connection.execute(
            """
            SELECT id, venue_id, event_title, notes
            FROM booking_dates
            WHERE id = ?
            """,
            (booking_date_id,),
        ).fetchone()
        if booking_date is None:
            return jsonify({"error": "Data chiusa non trovata"}), 404
        existing_meta = parse_booking_date_notes(booking_date["notes"])
        user_notes = (
            (payload.get("notes") or "").strip()
            if "notes" in payload
            else existing_meta["user_notes"]
        )
        serialized_notes = serialize_booking_date_notes(user_notes, budget, radio_package)
        connection.execute(
            "UPDATE booking_dates SET notes = ? WHERE id = ?",
            (serialized_notes, booking_date_id),
        )
        total_budget = round((budget or 0) + (200 if radio_package else 0), 2) if budget is not None else None
        log_activity(
            connection,
            booking_date["venue_id"],
            "booking",
            "Data chiusa aggiornata",
            (
                f"{booking_date['event_title']} - budget {format_budget_value(total_budget) or 'n/d'} euro"
                + (" con pacchetto radio" if radio_package else "")
            ),
        )
        connection.commit()
    return jsonify({"ok": True, "total_budget": total_budget})


@app.post("/api/venues/<int:venue_id>/activities")
def api_add_activity(venue_id: int):
    payload = request.get_json(force=True)
    title = (payload.get("title") or "").strip()
    details = (payload.get("details") or "").strip()
    activity_type = (payload.get("activity_type") or "manual").strip()
    if not title:
        return jsonify({"error": "Il titolo dell'attivita e obbligatorio"}), 400

    if using_supabase():
        existing = supabase_select("venues", f"select=id&id=eq.{venue_id}&limit=1")
        if not existing:
            return jsonify({"error": "Contatto non trovato"}), 404
        supabase_request(
            "POST",
            "/rest/v1/venue_activities",
            "",
            payload={
                "venue_id": venue_id,
                "activity_type": activity_type,
                "title": title,
                "details": details or None,
                "created_at": utc_now(),
            },
            prefer="return=minimal",
        )
        return jsonify({"ok": True}), 201

    with closing(get_connection()) as connection:
        venue = connection.execute("SELECT id FROM venues WHERE id = ?", (venue_id,)).fetchone()
        if venue is None:
            return jsonify({"error": "Contatto non trovato"}), 404
        log_activity(connection, venue_id, activity_type, title, details or None)
        connection.commit()
    return jsonify({"ok": True}), 201


@app.get("/api/followups")
def api_followups():
    if using_supabase():
        venues = [serialize_venue_record(item) for item in supabase_select("venues", "select=id,name,city,country,status,priority,next_action,follow_up_date")]
        today = datetime.utcnow().date().isoformat()
        rows = [item for item in venues if item.get("follow_up_date")]
        rows.sort(
            key=lambda item: (
                0 if item["follow_up_date"] < today else 1 if item["follow_up_date"] == today else 2,
                item["follow_up_date"],
            )
        )
        return jsonify(rows)

    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT id, name, city, country, status, priority, next_action, follow_up_date
            FROM venues
            WHERE follow_up_date IS NOT NULL AND follow_up_date <> ''
            ORDER BY
                CASE
                    WHEN follow_up_date < date('now') THEN 0
                    WHEN follow_up_date = date('now') THEN 1
                    ELSE 2
                END,
                follow_up_date ASC
            """
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/pipeline")
def api_pipeline():
    if using_supabase():
        venues = [serialize_venue_record(item) for item in supabase_select("venues", "select=id,name,city,country,priority,status,next_action,follow_up_date,updated_at,notes")]
        negotiations = [
            item for item in venues
            if item.get("status") in {"interessato", "call da fare", "trattativa", "data opzionata"}
        ]
        negotiations.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        booking_dates = supabase_select("booking_dates", "select=id,venue_id,event_title,event_date,status,notes&order=event_date.desc")
        closed = build_closed_date_entries(venues, booking_dates)
        return jsonify({"negotiations": negotiations, "closed_dates": closed})

    with closing(get_connection()) as connection:
        negotiations = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, name, city, country, priority, status, next_action, follow_up_date, updated_at
                FROM venues
                WHERE status IN ('interessato', 'call da fare', 'trattativa', 'data opzionata')
                ORDER BY updated_at DESC
                """
            )
        ]
        closed = [
            {**dict(row), "venue_id": row["venue_id"] if "venue_id" in row.keys() else None}
            for row in connection.execute(
                """
                SELECT booking_dates.id, booking_dates.venue_id, booking_dates.event_title, booking_dates.event_date, booking_dates.status,
                       booking_dates.notes, venues.name AS venue_name, venues.city, venues.country
                FROM booking_dates
                JOIN venues ON venues.id = booking_dates.venue_id
                ORDER BY booking_dates.event_date DESC
                """
            )
        ]
        venue_rows = [
            serialize_venue(row)
            for row in connection.execute(
                """
                SELECT *
                FROM venues
                """
            ).fetchall()
        ]
    return jsonify({"negotiations": negotiations, "closed_dates": build_closed_date_entries(venue_rows, closed)})


@app.post("/api/venues/<int:venue_id>/booking-dates")
def api_add_booking_date(venue_id: int):
    payload = request.get_json(force=True)
    event_title = (payload.get("event_title") or "").strip()
    event_date = (payload.get("event_date") or "").strip()
    notes = (payload.get("notes") or "").strip()
    budget = normalize_budget_value(payload.get("budget"))
    radio_package = bool(payload.get("radio_package"))
    status = (payload.get("status") or "confirmed").strip()
    if not event_title or not event_date:
        return jsonify({"error": "Titolo evento e data sono obbligatori"}), 400
    serialized_notes = serialize_booking_date_notes(notes, budget, radio_package)

    if using_supabase():
        existing = supabase_select("venues", f"select=id&id=eq.{venue_id}&limit=1")
        if not existing:
            return jsonify({"error": "Contatto non trovato"}), 404
        now = utc_now()
        supabase_request(
            "POST",
            "/rest/v1/booking_dates",
            "",
            payload={
                "venue_id": venue_id,
                "event_title": event_title,
                "event_date": event_date,
                "status": status,
                "notes": serialized_notes,
                "created_at": now,
            },
            prefer="return=minimal",
        )
        supabase_request(
            "PATCH",
            "/rest/v1/venues",
            f"id=eq.{venue_id}",
            payload={"status": "data chiusa", "updated_at": now},
            prefer="return=minimal",
        )
        supabase_request(
            "POST",
            "/rest/v1/venue_activities",
            "",
            payload={
                "venue_id": venue_id,
                "activity_type": "booking",
                "title": "Data registrata",
                "details": f"{event_title} - {event_date}",
                "created_at": now,
            },
            prefer="return=minimal",
        )
        return jsonify({"ok": True}), 201

    with closing(get_connection()) as connection:
        venue = connection.execute("SELECT id FROM venues WHERE id = ?", (venue_id,)).fetchone()
        if venue is None:
            return jsonify({"error": "Contatto non trovato"}), 404

        now = utc_now()
        connection.execute(
            """
            INSERT INTO booking_dates (venue_id, event_title, event_date, status, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (venue_id, event_title, event_date, status, serialized_notes, now),
        )
        connection.execute(
            "UPDATE venues SET status = ?, updated_at = ? WHERE id = ?",
            ("data chiusa", now, venue_id),
        )
        log_activity(connection, venue_id, "booking", "Data registrata", f"{event_title} - {event_date}")
        connection.commit()
    return jsonify({"ok": True}), 201


if __name__ == "__main__":
    if not using_supabase():
        initialize_database()
        seed_if_empty()
    app.run(debug=True)

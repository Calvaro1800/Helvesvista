"""
MongoDB Atlas client for HelveVista.
Falls back silently if connection fails — never crashes the app.
"""
import os
from dotenv import load_dotenv

load_dotenv()

_client = None
_db = None
_cases = None


def _get_collection():
    global _client, _db, _cases
    if _cases is not None:
        return _cases
    try:
        from pymongo import MongoClient
        from pymongo.server_api import ServerApi
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            return None
        _client = MongoClient(uri, server_api=ServerApi("1"),
                              serverSelectionTimeoutMS=3000)
        _client.admin.command("ping")
        _db = _client["helvevista"]
        _cases = _db["cases"]
        print("[MongoDB] Connected to Atlas ✓")
        return _cases
    except Exception as e:
        print(f"[MongoDB] Connection failed (using JSON fallback): {e}")
        return None


def save_case(case_id: str, user_email: str, scenario: str,
              status: str, data: dict) -> bool:
    col = _get_collection()
    if col is None:
        return False
    try:
        from datetime import datetime, timezone
        col.update_one(
            {"case_id": case_id},
            {"$set": {
                "case_id": case_id,
                "user_email": user_email,
                "scenario": scenario,
                "status": status,
                "data": data,
                "updated_at": datetime.now(timezone.utc),
            },
             "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
            }},
            upsert=True
        )
        return True
    except Exception as e:
        print(f"[MongoDB] save_case failed: {e}")
        return False


def load_case(case_id: str) -> dict | None:
    col = _get_collection()
    if col is None:
        return None
    try:
        doc = col.find_one({"case_id": case_id}, {"_id": 0})
        return doc
    except Exception as e:
        print(f"[MongoDB] load_case failed: {e}")
        return None


def list_cases(user_email: str) -> list:
    col = _get_collection()
    if col is None:
        return []
    try:
        docs = col.find(
            {"user_email": user_email},
            {"_id": 0, "case_id": 1, "scenario": 1,
             "status": 1, "created_at": 1, "updated_at": 1,
             "data": 1}
        ).sort("updated_at", -1).limit(20)
        return list(docs)
    except Exception as e:
        print(f"[MongoDB] list_cases failed: {e}")
        return []


def delete_case(case_id: str) -> bool:
    col = _get_collection()
    if col is None:
        return False
    try:
        col.delete_one({"case_id": case_id})
        return True
    except Exception as e:
        print(f"[MongoDB] delete_case failed: {e}")
        return False


def list_all_active_cases(limit: int = 50) -> list:
    """Return all EN_COURS cases across all users, sorted by updated_at descending."""
    col = _get_collection()
    if col is None:
        return []
    try:
        docs = col.find(
            {"status": "EN_COURS"},
            {"_id": 0}
        ).sort("updated_at", -1).limit(limit)
        return list(docs)
    except Exception as e:
        print(f"[MongoDB] list_all_active_cases failed: {e}")
        return []


def list_known_emails() -> list[str]:
    """Return sorted list of distinct user emails from the cases collection."""
    col = _get_collection()
    if col is None:
        return []
    try:
        emails = col.distinct("user_email")
        return sorted(e for e in emails if e and "@" in e)
    except Exception as e:
        print(f"[MongoDB] list_known_emails failed: {e}")
        return []

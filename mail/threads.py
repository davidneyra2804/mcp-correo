"""Hilos básicos y cruce de no respondidos. No habla con IMAP."""

from __future__ import annotations

import re

from mail.mime import parse_header_block

_ID_RE = re.compile(r"<[^<>\s]+>")


def extract_message_ids(value: str) -> list[str]:
    return [match.group(0) for match in _ID_RE.finditer(value or "")]


def normalize_message_id(value: str) -> str:
    ids = extract_message_ids(value)
    token = ids[0] if ids else (value or "").strip()
    return token.lower()


def replied_ids_from_header_block(raw: bytes) -> set[str]:
    """Identificadores citados en In-Reply-To o References de un mensaje enviado."""
    headers = parse_header_block(raw)
    found: set[str] = set()
    for name in ("in-reply-to", "references"):
        found.update(item.lower() for item in extract_message_ids(headers.get(name, "")))
    return found


def thread_root(message_id: str, in_reply_to: str, references: str) -> str:
    referenced = extract_message_ids(references)
    if referenced:
        return referenced[0].lower()
    parents = extract_message_ids(in_reply_to)
    if parents:
        return parents[0].lower()
    own = extract_message_ids(message_id)
    if own:
        return own[0].lower()
    return normalize_message_id(message_id)


def group_threads(messages: list[dict]) -> list[dict]:
    """Agrupa por la raíz de References. El orden de cada hilo es cronológico."""
    buckets: dict[str, list[dict]] = {}
    for message in sorted(messages, key=lambda item: (item.get("date") or "", item["uid"])):
        root = thread_root(
            str(message.get("message_id") or ""),
            str(message.get("in_reply_to") or ""),
            str(message.get("references") or ""),
        )
        buckets.setdefault(root, []).append(message)
    threads = [
        {"root": root, "count": len(items), "messages": items} for root, items in buckets.items()
    ]
    threads.sort(
        key=lambda item: (
            item["messages"][-1].get("date") or "",
            item["messages"][-1]["uid"],
        ),
        reverse=True,
    )
    return threads

"""Parses EverQuest /outputfile inventory exports.

Confirmed real format (from a live Minihk_rathe-Inventory.txt export): the file
is actually several tab-delimited sections separated by blank lines - a main
"Location Name ID Count Slots" inventory table, followed by a "KeyRing Name ID"
table, and possibly others. Each section has its own header row. Empty slots
are represented as literal rows with Name="Empty" and ID=0, which are skipped.
"""
from dataclasses import dataclass
from pathlib import Path

NAME_ALIASES = {"name", "itemname", "item name"}
ID_ALIASES = {"id", "itemid", "item id"}
COUNT_ALIASES = {"count", "qty", "quantity", "stack"}
LOCATION_ALIASES = {"location", "keyring"}


@dataclass
class InventoryRow:
    name: str
    eq_item_id: int | None
    count: int
    slot: str
    area: str


def classify_area(slot: str) -> str:
    """Buckets a raw slot/location string into Equipped, Carried, Bank, Shared Bank, or Cursor.

    Bag slots are named "General 1".."General 8" (and nested "General 1-Slot1"
    for items inside a bag), bank slots "Bank1".."Bank24", shared bank slots
    "SharedBank1".."SharedBank8", and everything else (Charm, Head, Chest,
    Primary, Held, Power Source, etc.) is a worn equipment slot.
    """
    s = slot.strip().lower().replace(" ", "")
    if s.startswith("sharedbank"):
        return "Shared Bank"
    if s.startswith("bank"):
        return "Bank"
    if s.startswith("cursor"):
        return "Cursor"
    if s.startswith("general") or "bag" in s:
        return "Carried"
    return "Equipped"


def parse_character_from_filename(path: str | Path) -> tuple[str, str] | None:
    """Extracts (character_name, server) from EQ's "Name_Server-Inventory" filename.

    Returns None if the filename doesn't match that pattern - caller should
    fall back to asking the user.
    """
    stem = Path(path).stem
    if not stem.endswith("-Inventory"):
        return None
    prefix = stem[: -len("-Inventory")]
    if "_" not in prefix:
        return None
    name, server = prefix.rsplit("_", 1)
    if not name or not server:
        return None
    return name, server


def _detect_columns(header_cells: list[str]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        key = cell.strip().lower()
        if key in NAME_ALIASES:
            columns["name"] = idx
        elif key in ID_ALIASES:
            columns["id"] = idx
        elif key in COUNT_ALIASES:
            columns["count"] = idx
        elif key in LOCATION_ALIASES:
            columns["slot"] = idx
    return columns


def _split_sections(text: str) -> list[list[str]]:
    """Splits the file into blocks of non-blank lines, one block per table section."""
    sections: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                sections.append(current)
                current = []
        else:
            current.append(line)
    if current:
        sections.append(current)
    return sections


def parse_outputfile(path: str | Path) -> list[InventoryRow]:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    sections = _split_sections(text)
    if not sections:
        return []

    rows: list[InventoryRow] = []
    for section_index, block in enumerate(sections):
        header_cells = block[0].split("\t")
        columns = _detect_columns(header_cells)
        if "name" not in columns:
            if section_index == 0:
                raise ValueError(
                    f"Could not find a 'Name' column in the file header: {header_cells!r}. "
                    "The /outputfile format may have changed - check the file and update "
                    "inventory_import.py's alias sets."
                )
            continue  # unrecognized trailing section (e.g. future new table) - skip, don't fail the whole import

        # A "KeyRing" section uses its own slot-column header text instead of "Location"/"Slot".
        slot_header_text = header_cells[columns["slot"]].strip().lower() if "slot" in columns else ""
        forced_area = "Key Ring" if slot_header_text == "keyring" else None

        for line in block[1:]:
            cells = line.split("\t")
            name = cells[columns["name"]].strip() if columns["name"] < len(cells) else ""
            if not name or name.lower() == "empty":
                continue
            eq_item_id = None
            if "id" in columns and columns["id"] < len(cells):
                raw_id = cells[columns["id"]].strip()
                if raw_id.isdigit() and int(raw_id) != 0:
                    eq_item_id = int(raw_id)
            count = 1
            if "count" in columns and columns["count"] < len(cells):
                raw_count = cells[columns["count"]].strip()
                if raw_count.isdigit():
                    count = int(raw_count)
            slot = cells[columns["slot"]].strip() if "slot" in columns and columns["slot"] < len(cells) else ""
            area = forced_area or classify_area(slot)
            rows.append(InventoryRow(name=name, eq_item_id=eq_item_id, count=count, slot=slot, area=area))
    return rows


def aggregate_by_item(rows: list[InventoryRow]) -> dict[tuple[str, int | None, str], int]:
    """Sum counts for the same item name/id/area across all matching slots."""
    totals: dict[tuple[str, int | None, str], int] = {}
    for row in rows:
        key = (row.name, row.eq_item_id, row.area)
        totals[key] = totals.get(key, 0) + row.count
    return totals


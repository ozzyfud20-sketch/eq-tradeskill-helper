"""SQLite storage layer for the EQ Tradeskill Helper."""
import sqlite3
import sys
from pathlib import Path

# When frozen by PyInstaller, __file__ resolves inside a temp extraction dir
# that's wiped between runs - use the actual exe's folder instead so the DB persists.
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent
DB_PATH = _BASE_DIR / "eq_helper.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eq_item_id INTEGER UNIQUE,
    name TEXT NOT NULL,
    notes TEXT,
    tradeskill_flagged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS item_tags (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, tag_id)
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS item_locations (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (item_id, location_id)
);

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    result_item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
    tradeskill TEXT,
    trivial INTEGER
);

CREATE TABLE IF NOT EXISTS recipe_components (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (recipe_id, item_id)
);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    server TEXT NOT NULL DEFAULT '',
    last_import_at TEXT,
    UNIQUE (name, server)
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# --- Items ---------------------------------------------------------------

def add_item(name: str, eq_item_id: int | None, notes: str, tradeskill_flagged: bool) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO items (eq_item_id, name, notes, tradeskill_flagged) VALUES (?, ?, ?, ?)",
            (eq_item_id, name, notes, int(tradeskill_flagged)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_item(item_id: int, name: str, eq_item_id: int | None, notes: str, tradeskill_flagged: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE items SET name=?, eq_item_id=?, notes=?, tradeskill_flagged=?,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (name, eq_item_id, notes, int(tradeskill_flagged), item_id),
        )
        conn.commit()
    finally:
        conn.close()


def search_items(query: str = "") -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        like = f"%{query}%"
        return conn.execute(
            """SELECT * FROM items WHERE name LIKE ? OR CAST(eq_item_id AS TEXT) LIKE ?
               ORDER BY name""",
            (like, like),
        ).fetchall()
    finally:
        conn.close()


def list_workbench_items(
    query: str = "",
    tradeskill_filter: str = "all",
    server: str = "",
    character: str = "",
    tag_match: str = "any",
) -> list[sqlite3.Row]:
    """Return unique items matching text/tags, tradeskill, and inventory filters."""
    conn = get_connection()
    try:
        conditions = []
        parameters: list[str] = []
        if tag_match not in {"any", "all"}:
            raise ValueError(f"Unknown tag match mode: {tag_match}")

        search_terms = [term.strip() for term in query.split(",") if term.strip()]
        if search_terms:
            term_conditions = []
            for term in search_terms:
                like = f"%{term}%"
                term_conditions.append(
                    """(
                        items.name LIKE ?
                        OR CAST(items.eq_item_id AS TEXT) LIKE ?
                        OR EXISTS (
                            SELECT 1
                            FROM item_tags
                            JOIN tags ON tags.id = item_tags.tag_id
                            WHERE item_tags.item_id = items.id AND tags.name LIKE ?
                        )
                    )"""
                )
                parameters.extend((like, like, like))
            operator = " OR " if tag_match == "any" else " AND "
            conditions.append("(" + operator.join(term_conditions) + ")")

        if tradeskill_filter == "tradeskill":
            conditions.append("items.tradeskill_flagged = 1")
        elif tradeskill_filter == "non-tradeskill":
            conditions.append("items.tradeskill_flagged = 0")
        elif tradeskill_filter != "all":
            raise ValueError(f"Unknown tradeskill filter: {tradeskill_filter}")

        if server or character:
            location_conditions = ["item_locations.item_id = items.id"]
            if server:
                location_conditions.append("characters.server = ?")
                parameters.append(server)
            if character:
                location_conditions.append("characters.name = ?")
                parameters.append(character)
            conditions.append(
                """EXISTS (
                    SELECT 1
                    FROM item_locations
                    JOIN locations ON locations.id = item_locations.location_id
                    JOIN characters ON substr(
                        locations.name, 1,
                        length(characters.name || ' (' || characters.server || ') - ')
                    ) = characters.name || ' (' || characters.server || ') - '
                    WHERE """ + " AND ".join(location_conditions) + ")"
            )

        sql = "SELECT items.* FROM items"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY items.name COLLATE NOCASE"
        return conn.execute(sql, parameters).fetchall()
    finally:
        conn.close()


def get_item(item_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    finally:
        conn.close()


def delete_item(item_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
    finally:
        conn.close()


def find_item_by_eq_id(eq_item_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM items WHERE eq_item_id=?", (eq_item_id,)).fetchone()
    finally:
        conn.close()


def find_item_by_exact_name(name: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM items WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    finally:
        conn.close()


def upsert_item_from_import(name: str, eq_item_id: int | None) -> tuple[int, bool]:
    """Find an existing item by eq_item_id (preferred) or exact name; create it if missing.

    Returns (item_id, created) where created is True if a new row was inserted.
    """
    existing = find_item_by_eq_id(eq_item_id) if eq_item_id else None
    if existing is None:
        existing = find_item_by_exact_name(name)
    if existing is not None:
        if eq_item_id and not existing["eq_item_id"]:
            update_item(existing["id"], existing["name"], eq_item_id, existing["notes"] or "",
                        bool(existing["tradeskill_flagged"]))
        return existing["id"], False
    item_id = add_item(name, eq_item_id, "", False)
    return item_id, True


def get_or_create_location(name: str, loc_type: str = "character") -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM locations WHERE name=?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO locations (name, type, notes) VALUES (?, ?, ?)",
            (name, loc_type, ""),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --- Tags ------------------------------------------------------------------

def get_or_create_tag(name: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def set_item_tags(item_id: int, tag_names: list[str]) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))
        for name in tag_names:
            name = name.strip()
            if not name:
                continue
            row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
            tag_id = row["id"] if row else conn.execute(
                "INSERT INTO tags (name) VALUES (?)", (name,)
            ).lastrowid
            conn.execute(
                "INSERT OR IGNORE INTO item_tags (item_id, tag_id) VALUES (?, ?)",
                (item_id, tag_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_item_tags(item_id: int) -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT tags.name FROM tags
               JOIN item_tags ON item_tags.tag_id = tags.id
               WHERE item_tags.item_id=? ORDER BY tags.name""",
            (item_id,),
        ).fetchall()
        return [r["name"] for r in rows]
    finally:
        conn.close()


def list_all_tags() -> list[str]:
    conn = get_connection()
    try:
        return [r["name"] for r in conn.execute("SELECT name FROM tags ORDER BY name").fetchall()]
    finally:
        conn.close()


# --- Locations ---------------------------------------------------------------

def add_location(name: str, loc_type: str, notes: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO locations (name, type, notes) VALUES (?, ?, ?)",
            (name, loc_type, notes),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_locations() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
    finally:
        conn.close()


def delete_location(location_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM locations WHERE id=?", (location_id,))
        conn.commit()
    finally:
        conn.close()


def set_item_location(item_id: int, location_id: int, quantity: int) -> None:
    conn = get_connection()
    try:
        if quantity <= 0:
            conn.execute(
                "DELETE FROM item_locations WHERE item_id=? AND location_id=?",
                (item_id, location_id),
            )
        else:
            conn.execute(
                """INSERT INTO item_locations (item_id, location_id, quantity) VALUES (?, ?, ?)
                   ON CONFLICT(item_id, location_id) DO UPDATE SET quantity=excluded.quantity""",
                (item_id, location_id, quantity),
            )
        conn.commit()
    finally:
        conn.close()


def get_item_locations(
    item_id: int, server: str = "", character: str = ""
) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        conditions = ["item_locations.item_id = ?"]
        parameters: list[object] = [item_id]
        if server:
            conditions.append("characters.server = ?")
            parameters.append(server)
        if character:
            conditions.append("characters.name = ?")
            parameters.append(character)
        return conn.execute(
            """SELECT locations.id, locations.name, item_locations.quantity,
                      COALESCE(characters.name, '') AS character_name,
                      COALESCE(characters.server, '') AS server,
                      CASE WHEN characters.id IS NULL THEN '' ELSE
                          substr(locations.name, length(
                              characters.name || ' (' || characters.server || ') - '
                          ) + 1)
                      END AS area
               FROM item_locations
               JOIN locations ON locations.id = item_locations.location_id
               LEFT JOIN characters ON substr(
                   locations.name, 1,
                   length(characters.name || ' (' || characters.server || ') - ')
               ) = characters.name || ' (' || characters.server || ') - '
               WHERE """ + " AND ".join(conditions) +
            " ORDER BY characters.server, characters.name, area, locations.name",
            parameters,
        ).fetchall()
    finally:
        conn.close()


# --- Recipes -----------------------------------------------------------------

def add_recipe(name: str, result_item_id: int | None, tradeskill: str, trivial: int | None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO recipes (name, result_item_id, tradeskill, trivial) VALUES (?, ?, ?, ?)",
            (name, result_item_id, tradeskill, trivial),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def set_recipe_components(recipe_id: int, components: list[tuple[int, int]]) -> None:
    """components: list of (item_id, quantity)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM recipe_components WHERE recipe_id=?", (recipe_id,))
        for item_id, quantity in components:
            conn.execute(
                "INSERT INTO recipe_components (recipe_id, item_id, quantity) VALUES (?, ?, ?)",
                (recipe_id, item_id, quantity),
            )
        conn.commit()
    finally:
        conn.close()


def list_recipes() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT recipes.*, items.name AS result_name
               FROM recipes LEFT JOIN items ON items.id = recipes.result_item_id
               ORDER BY recipes.name"""
        ).fetchall()
    finally:
        conn.close()


def get_recipe_components(recipe_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT recipe_components.item_id, items.name, recipe_components.quantity
               FROM recipe_components JOIN items ON items.id = recipe_components.item_id
               WHERE recipe_components.recipe_id=? ORDER BY items.name""",
            (recipe_id,),
        ).fetchall()
    finally:
        conn.close()


def get_total_owned_quantity(item_id: int) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM item_locations WHERE item_id=?",
            (item_id,),
        ).fetchone()
        return row["total"]
    finally:
        conn.close()


def craftable_recipes() -> list[dict]:
    """Return recipes where owned quantities meet or exceed every component's need."""
    conn = get_connection()
    try:
        recipes = conn.execute("SELECT * FROM recipes").fetchall()
        results = []
        for recipe in recipes:
            components = get_recipe_components(recipe["id"])
            if not components:
                continue
            missing = []
            for comp in components:
                owned = get_total_owned_quantity(comp["item_id"])
                if owned < comp["quantity"]:
                    missing.append((comp["name"], comp["quantity"], owned))
            results.append({
                "recipe": recipe,
                "components": components,
                "missing": missing,
                "craftable": not missing,
            })
        return results
    finally:
        conn.close()


# --- Characters --------------------------------------------------------------

def get_or_create_character(name: str, server: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM characters WHERE name=? AND server=?", (name, server)
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO characters (name, server) VALUES (?, ?)", (name, server)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def touch_character_import(name: str, server: str) -> None:
    """Records that a character's inventory was just (re)imported."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO characters (name, server, last_import_at) VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(name, server) DO UPDATE SET last_import_at=CURRENT_TIMESTAMP""",
            (name, server),
        )
        conn.commit()
    finally:
        conn.close()


def list_characters() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM characters ORDER BY name").fetchall()
    finally:
        conn.close()


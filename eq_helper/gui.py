"""Tkinter UI for the EQ Tradeskill Helper."""
import os
import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk, messagebox, filedialog

from eq_helper import db
from eq_helper import inventory_import


def _sort_key(value: str):
    """Numeric sort if possible, else alphabetical by first word (then full text)."""
    try:
        return (0, float(value))
    except ValueError:
        stripped = value.strip()
        first_word = stripped.split(" ", 1)[0].lower() if stripped else ""
        return (1, first_word, stripped.lower())


def _sort_treeview_column(tree: ttk.Treeview, col: str, reverse: bool):
    if col == "#0":
        data = [(tree.item(k, "text"), k) for k in tree.get_children("")]
    else:
        data = [(tree.set(k, col), k) for k in tree.get_children("")]
    data.sort(key=lambda pair: _sort_key(pair[0]), reverse=reverse)
    for index, (_value, k) in enumerate(data):
        tree.move(k, "", index)
    tree.heading(col, command=lambda: _sort_treeview_column(tree, col, not reverse))


def _make_sortable(tree: ttk.Treeview, columns: dict[str, str]):
    """columns: {column_id: header_text}. Attaches click-to-sort to each heading."""
    for col, text in columns.items():
        tree.heading(col, text=text, command=lambda c=col: _sort_treeview_column(tree, c, False))


class ItemsTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.selected_item_id: int | None = None
        self._character_filters: dict[str, tuple[str, str]] = {}
        self._build()
        self._refresh_filter_choices()
        self._refresh_tag_suggestions()
        self.refresh()

    def _build(self):
        filters = ttk.Frame(self)
        filters.pack(fill="x", padx=8, pady=6)
        filters.columnconfigure(1, weight=1)
        filters.columnconfigure(3, weight=1)

        ttk.Label(filters, text="Search:").grid(row=0, column=0, sticky="w")
        self.search_var = tk.StringVar()
        search_controls = ttk.Frame(filters)
        search_controls.grid(row=0, column=1, sticky="ew", padx=(4, 12))
        search_controls.columnconfigure(0, weight=1)
        self.search_entry = ttk.Combobox(
            search_controls, textvariable=self.search_var, state="normal",
        )
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda _event: self.refresh())
        self.search_entry.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Label(search_controls, text="Match:").grid(row=0, column=1, padx=(8, 4))
        self.tag_match_var = tk.StringVar(value="Any term")
        self.tag_match_filter = ttk.Combobox(
            search_controls, textvariable=self.tag_match_var,
            values=("Any term", "All terms"), state="readonly", width=10,
        )
        self.tag_match_filter.grid(row=0, column=2, sticky="e")
        self.tag_match_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        ttk.Label(filters, text="Item type:").grid(row=0, column=2, sticky="w")
        self.tradeskill_var = tk.StringVar(value="All items")
        self.tradeskill_filter = ttk.Combobox(
            filters, textvariable=self.tradeskill_var,
            values=("All items", "Tradeskill only", "Non-tradeskill only"),
            state="readonly", width=20,
        )
        self.tradeskill_filter.grid(row=0, column=3, sticky="ew", padx=4)
        self.tradeskill_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        ttk.Label(filters, text="Server:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.server_var = tk.StringVar(value="All servers")
        self.server_filter = ttk.Combobox(
            filters, textvariable=self.server_var, state="readonly", width=20,
        )
        self.server_filter.grid(row=1, column=1, sticky="ew", padx=(4, 12), pady=(6, 0))
        self.server_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        ttk.Label(filters, text="Character:").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.character_var = tk.StringVar(value="All characters")
        self.character_filter = ttk.Combobox(
            filters, textvariable=self.character_var, state="readonly", width=24,
        )
        self.character_filter.grid(row=1, column=3, sticky="ew", padx=4, pady=(6, 0))
        self.character_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Button(filters, text="Clear filters", command=self._clear_filters).grid(
            row=1, column=4, padx=(8, 0), pady=(6, 0)
        )

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        body.columnconfigure(0, weight=1, uniform="workbench_panes")
        body.columnconfigure(1, weight=1, uniform="workbench_panes")
        body.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(body)
        list_frame.grid(row=0, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        columns = ("tradeskill", "name", "eq_id")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        _make_sortable(self.tree, {
            "tradeskill": "Tradeskill", "name": "Item", "eq_id": "EQ Item ID",
        })
        self.tree.column("tradeskill", width=90, anchor="center")
        self.tree.column("name", width=250, stretch=True)
        self.tree.column("eq_id", width=100, anchor="center")
        self.tree.tag_configure("tradeskill", foreground="#1a7f37")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-1>", self._on_tree_click)

        form = ttk.LabelFrame(body, text="Selected item", padding=8)
        form.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        form.columnconfigure(1, weight=1)
        form.rowconfigure(6, weight=1)

        ttk.Label(form, text="Name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(form, text="EQ Item ID").grid(row=1, column=0, sticky="w")
        self.eq_id_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.eq_id_var).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(form, text="Tags (comma separated)").grid(row=2, column=0, sticky="w")
        self.tags_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.tags_var).grid(row=2, column=1, sticky="ew", pady=2)

        ttk.Label(form, text="Description / Notes").grid(row=3, column=0, sticky="nw")
        self.notes_text = tk.Text(form, height=4, wrap="word")
        self.notes_text.grid(row=3, column=1, sticky="ew", pady=2)

        btns = ttk.Frame(form)
        btns.grid(row=4, column=0, columnspan=2, pady=6, sticky="w")
        ttk.Button(btns, text="New", command=self._clear_form).pack(side="left")
        ttk.Button(btns, text="Save", command=self._save).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete", command=self._delete).pack(side="left")

        ttk.Label(form, text="Found in inventory").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 2)
        )
        self.locations_tree = ttk.Treeview(
            form, columns=("character", "server", "area", "quantity"),
            show="headings", height=7,
        )
        for column, heading in (
            ("character", "Character"), ("server", "Server"),
            ("area", "Area"), ("quantity", "Qty"),
        ):
            self.locations_tree.heading(column, text=heading)
        self.locations_tree.column("character", width=100, stretch=True)
        self.locations_tree.column("server", width=90, stretch=True)
        self.locations_tree.column("area", width=110, stretch=True)
        self.locations_tree.column("quantity", width=55, anchor="center")
        self.locations_tree.grid(row=6, column=0, columnspan=2, sticky="nsew")

        loc_form = ttk.Frame(form)
        loc_form.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.loc_choice = ttk.Combobox(loc_form, width=24, state="readonly")
        self.loc_choice.pack(side="left")
        self.loc_qty_var = tk.StringVar(value="1")
        ttk.Entry(loc_form, textvariable=self.loc_qty_var, width=5).pack(side="left", padx=4)
        ttk.Button(loc_form, text="Set Qty", command=self._set_location_qty).pack(side="left")

    def refresh(self):
        self._refresh_filter_choices()
        server, character = self._active_inventory_filters()
        filter_mode = {
            "All items": "all",
            "Tradeskill only": "tradeskill",
            "Non-tradeskill only": "non-tradeskill",
        }.get(self.tradeskill_var.get(), "all")
        tag_match = "all" if self.tag_match_var.get() == "All terms" else "any"
        previous_item_id = self.selected_item_id
        for row in self.tree.get_children():
            self.tree.delete(row)
        visible_item_ids = set()
        for row in db.list_workbench_items(
            self.search_var.get(), filter_mode, server, character, tag_match,
        ):
            iid = str(row["id"])
            visible_item_ids.add(row["id"])
            is_tradeskill = bool(row["tradeskill_flagged"])
            checkbox = "\u2611" if is_tradeskill else "\u2610"
            self.tree.insert(
                "", "end", iid=iid,
                values=(checkbox, row["name"], row["eq_item_id"] or ""),
                tags=("tradeskill",) if is_tradeskill else (),
            )
        self.loc_choice["values"] = [loc["name"] for loc in db.list_locations()]
        if previous_item_id in visible_item_ids:
            iid = str(previous_item_id)
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self._show_item(previous_item_id)
        else:
            self._clear_form()

    def _refresh_tag_suggestions(self):
        pinned_tags = ("Pelts", "Ores", "Silk")
        pinned_keys = {tag.casefold() for tag in pinned_tags}
        other_tags = sorted(
            (tag for tag in db.list_all_tags() if tag.casefold() not in pinned_keys),
            key=str.casefold,
        )
        self.search_entry["values"] = (*pinned_tags, *other_tags)

    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or col != "#1":  # "#1" is the Tradeskill checkbox column
            return
        item_id = int(row)
        item = db.get_item(item_id)
        if not item:
            return
        new_flag = not bool(item["tradeskill_flagged"])
        db.update_item(item_id, item["name"], item["eq_item_id"], item["notes"] or "", new_flag)
        self.refresh()

    def _clear_form(self):
        self.selected_item_id = None
        self.name_var.set("")
        self.eq_id_var.set("")
        self.tags_var.set("")
        self.notes_text.delete("1.0", "end")
        for row in self.locations_tree.get_children():
            self.locations_tree.delete(row)
        self.tree.selection_remove(self.tree.selection())

    def _on_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        self._show_item(int(selection[0]))

    def _show_item(self, item_id: int):
        item = db.get_item(item_id)
        if not item:
            return
        self.selected_item_id = item_id
        self.name_var.set(item["name"])
        self.eq_id_var.set(str(item["eq_item_id"]) if item["eq_item_id"] else "")
        self.tags_var.set(", ".join(db.get_item_tags(item_id)))
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", item["notes"] or "")
        self._refresh_locations(item_id)

    def _refresh_filter_choices(self):
        characters = db.list_characters()
        servers = sorted({row["server"] for row in characters if row["server"]})
        server_values = ["All servers", *servers]
        self.server_filter["values"] = server_values
        if self.server_var.get() not in server_values:
            self.server_var.set("All servers")

        selected_server = self.server_var.get()
        self._character_filters = {}
        for row in characters:
            if selected_server != "All servers" and row["server"] != selected_server:
                continue
            label = row["name"] if selected_server != "All servers" else f"{row['name']} ({row['server']})"
            self._character_filters[label] = (row["name"], row["server"])
        character_values = ["All characters", *sorted(self._character_filters, key=str.casefold)]
        self.character_filter["values"] = character_values
        if self.character_var.get() not in character_values:
            self.character_var.set("All characters")

    def _active_inventory_filters(self) -> tuple[str, str]:
        server = self.server_var.get()
        server = "" if server == "All servers" else server
        character = self._character_filters.get(self.character_var.get())
        if character:
            character_name, character_server = character
            return server or character_server, character_name
        return server, ""

    def _clear_filters(self):
        self.search_var.set("")
        self.tag_match_var.set("Any term")
        self.tradeskill_var.set("All items")
        self.server_var.set("All servers")
        self.character_var.set("All characters")
        self.refresh()

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Item name is required.")
            return
        eq_id_raw = self.eq_id_var.get().strip()
        eq_id = int(eq_id_raw) if eq_id_raw.isdigit() else None
        notes = self.notes_text.get("1.0", "end").strip()

        if self.selected_item_id is None:
            self.selected_item_id = db.add_item(name, eq_id, notes, False)
        else:
            existing = db.get_item(self.selected_item_id)
            flagged = bool(existing["tradeskill_flagged"]) if existing else False
            db.update_item(self.selected_item_id, name, eq_id, notes, flagged)

        tag_names = [t.strip() for t in self.tags_var.get().split(",") if t.strip()]
        db.set_item_tags(self.selected_item_id, tag_names)

        self._refresh_tag_suggestions()
        self.refresh()

    def _delete(self):
        if self.selected_item_id is None:
            return
        if messagebox.askyesno("Confirm", "Delete this item?"):
            db.delete_item(self.selected_item_id)
            self._clear_form()
            self.refresh()

    def _set_location_qty(self):
        if self.selected_item_id is None:
            messagebox.showwarning("No item", "Select or save an item first.")
            return
        loc_name = self.loc_choice.get()
        if not loc_name:
            return
        locations = {loc["name"]: loc["id"] for loc in db.list_locations()}
        try:
            qty = int(self.loc_qty_var.get())
        except ValueError:
            messagebox.showwarning("Invalid quantity", "Quantity must be a number.")
            return
        db.set_item_location(self.selected_item_id, locations[loc_name], qty)
        self._on_select_refresh_locations()
        self.refresh()

    def _on_select_refresh_locations(self):
        if self.selected_item_id is not None:
            self._refresh_locations(self.selected_item_id)

    def _refresh_locations(self, item_id: int):
        for row in self.locations_tree.get_children():
            self.locations_tree.delete(row)
        server, character = self._active_inventory_filters()
        for location in db.get_item_locations(item_id, server, character):
            self.locations_tree.insert(
                "", "end", iid=str(location["id"]),
                values=(
                    location["character_name"] or "-",
                    location["server"] or "-",
                    location["area"] or location["name"],
                    location["quantity"],
                ),
            )


class LocationsTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build()
        self.refresh()

    def _build(self):
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=8)

        self.tree = ttk.Treeview(body, columns=("type", "notes"), show="tree headings")
        self.tree.heading("#0", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("notes", text="Notes")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        form = ttk.Frame(self)
        form.pack(fill="x", padx=8, pady=4)
        ttk.Label(form, text="Name").grid(row=0, column=0)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var).grid(row=0, column=1, padx=4)
        ttk.Label(form, text="Type").grid(row=0, column=2)
        self.type_var = tk.StringVar()
        ttk.Combobox(
            form, textvariable=self.type_var,
            values=["character", "bank", "guild bank", "mule"], width=12,
        ).grid(row=0, column=3, padx=4)
        ttk.Label(form, text="Notes").grid(row=0, column=4)
        self.notes_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.notes_var).grid(row=0, column=5, padx=4)
        ttk.Button(form, text="Add", command=self._add).grid(row=0, column=6, padx=4)
        ttk.Button(form, text="Delete Selected", command=self._delete).grid(row=0, column=7, padx=4)

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for loc in db.list_locations():
            self.tree.insert("", "end", iid=str(loc["id"]), text=loc["name"],
                              values=(loc["type"] or "", loc["notes"] or ""))

    def _add(self):
        name = self.name_var.get().strip()
        if not name:
            return
        db.add_location(name, self.type_var.get().strip(), self.notes_var.get().strip())
        self.name_var.set("")
        self.type_var.set("")
        self.notes_var.set("")
        self.refresh()

    def _delete(self):
        selection = self.tree.selection()
        if not selection:
            return
        db.delete_location(int(selection[0]))
        self.refresh()


class RecipesTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.selected_recipe_id: int | None = None
        self.component_rows: list[tuple[tk.StringVar, tk.StringVar]] = []
        self._build()
        self.refresh()

    def _build(self):
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=8)

        list_frame = ttk.Frame(body)
        list_frame.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(
            list_frame, columns=("result", "tradeskill", "craftable"), show="headings"
        )
        self.tree.heading("result", text="Recipe / Result")
        self.tree.heading("tradeskill", text="Tradeskill")
        self.tree.heading("craftable", text="Craftable Now?")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form = ttk.Frame(body)
        form.pack(side="left", fill="y", padx=(12, 0))

        ttk.Label(form, text="Recipe Name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var, width=28).grid(row=0, column=1)

        ttk.Label(form, text="Result Item Name").grid(row=1, column=0, sticky="w")
        self.result_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.result_var, width=28).grid(row=1, column=1)

        ttk.Label(form, text="Tradeskill").grid(row=2, column=0, sticky="w")
        self.tradeskill_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.tradeskill_var, width=28).grid(row=2, column=1)

        ttk.Label(form, text="Components (name:qty, one per line)").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        self.components_text = tk.Text(form, width=30, height=8)
        self.components_text.grid(row=4, column=0, columnspan=2)

        btns = ttk.Frame(form)
        btns.grid(row=5, column=0, columnspan=2, pady=8, sticky="w")
        ttk.Button(btns, text="New", command=self._clear_form).pack(side="left")
        ttk.Button(btns, text="Save", command=self._save).pack(side="left", padx=4)
        ttk.Button(btns, text="Refresh Craftable", command=self.refresh).pack(side="left")

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for entry in db.craftable_recipes():
            recipe = entry["recipe"]
            self.tree.insert(
                "", "end", iid=str(recipe["id"]),
                values=(
                    f"{recipe['name']} -> {recipe['result_name'] or '?'}",
                    recipe["tradeskill"] or "",
                    "Yes" if entry["craftable"] else "No",
                ),
            )

    def _clear_form(self):
        self.selected_recipe_id = None
        self.name_var.set("")
        self.result_var.set("")
        self.tradeskill_var.set("")
        self.components_text.delete("1.0", "end")

    def _on_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        recipe_id = int(selection[0])
        self.selected_recipe_id = recipe_id
        recipe = next(r for r in db.list_recipes() if r["id"] == recipe_id)
        self.name_var.set(recipe["name"])
        self.result_var.set(recipe["result_name"] or "")
        self.tradeskill_var.set(recipe["tradeskill"] or "")
        components = db.get_recipe_components(recipe_id)
        self.components_text.delete("1.0", "end")
        self.components_text.insert(
            "1.0", "\n".join(f"{c['name']}:{c['quantity']}" for c in components)
        )

    def _find_item_by_name(self, name: str):
        matches = [i for i in db.search_items(name) if i["name"].lower() == name.lower()]
        return matches[0] if matches else None

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Recipe name is required.")
            return

        result_item = self._find_item_by_name(self.result_var.get().strip())
        if self.result_var.get().strip() and not result_item:
            messagebox.showwarning(
                "Unknown item",
                f"Result item '{self.result_var.get()}' not found. Add it in the Items tab first.",
            )
            return

        trivial = None
        tradeskill = self.tradeskill_var.get().strip()

        if self.selected_recipe_id is None:
            self.selected_recipe_id = db.add_recipe(
                name, result_item["id"] if result_item else None, tradeskill, trivial
            )
        else:
            # simplest approach: delete and re-add components, keep same recipe row via direct SQL
            conn = db.get_connection()
            conn.execute(
                "UPDATE recipes SET name=?, result_item_id=?, tradeskill=?, trivial=? WHERE id=?",
                (name, result_item["id"] if result_item else None, tradeskill, trivial, self.selected_recipe_id),
            )
            conn.commit()
            conn.close()

        components = []
        missing_names = []
        for line in self.components_text.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            comp_name, qty_raw = line.rsplit(":", 1)
            comp_name = comp_name.strip()
            item = self._find_item_by_name(comp_name)
            if not item:
                missing_names.append(comp_name)
                continue
            try:
                qty = int(qty_raw.strip())
            except ValueError:
                qty = 1
            components.append((item["id"], qty))

        if missing_names:
            messagebox.showwarning(
                "Unknown components",
                "These items were not found and were skipped: " + ", ".join(missing_names),
            )

        db.set_recipe_components(self.selected_recipe_id, components)
        self.refresh()


class CharactersTab(ttk.Frame):
    """Dashboard of known characters/servers with a freshness indicator per character."""

    FRESH_DAYS = 7
    STALE_DAYS = 30

    def __init__(self, parent):
        super().__init__(parent)
        self._build()
        self.refresh()

    def _build(self):
        ttk.Label(self, text="Characters", font=("Georgia", 16, "bold")).pack(
            anchor="w", padx=8, pady=(8, 4)
        )
        self.tree = ttk.Treeview(
            self, columns=("server", "last_import", "days_since", "status"), show="tree headings"
        )
        _make_sortable(self.tree, {
            "server": "Server", "last_import": "Last Imported",
            "days_since": "Days Since Last Pull", "status": "Status",
        })
        self.tree.heading("#0", text="Character", command=lambda: _sort_treeview_column(self.tree, "#0", False))
        self.tree.column("days_since", width=140, anchor="center")
        self.tree.tag_configure("fresh", foreground="#1a7f37")
        self.tree.tag_configure("aging", foreground="#9a6700")
        self.tree.tag_configure("stale", foreground="#6e7781")
        self.tree.tag_configure("never", foreground="#6e7781")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for character in db.list_characters():
            tag, days_since, status = self._freshness(character["last_import_at"])
            self.tree.insert(
                "", "end", text=character["name"],
                values=(
                    character["server"],
                    self._format_import_time(character["last_import_at"]),
                    days_since,
                    status,
                ),
                tags=(tag,),
            )

    @staticmethod
    def _format_import_time(last_import_at: str | None) -> str:
        if not last_import_at:
            return "Never"
        try:
            stored_utc = datetime.strptime(last_import_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return last_import_at
        return stored_utc.replace(tzinfo=timezone.utc).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    def _freshness(self, last_import_at: str | None) -> tuple[str, str, str]:
        if not last_import_at:
            return "never", "-", "No data yet"
        try:
            last = datetime.strptime(last_import_at, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return "never", "-", "No data yet"
        days = max(0, (datetime.now(timezone.utc) - last).days)
        if days <= self.FRESH_DAYS:
            return "fresh", str(days), "Up to date"
        if days <= self.STALE_DAYS:
            return "aging", str(days), "Re-run soon"
        return "stale", str(days), "Stale"


class ImportTab(ttk.Frame):
    """Imports items/quantities from an EverQuest /outputfile inventory export."""

    def __init__(self, parent, on_items_changed=None):
        super().__init__(parent)
        self.on_items_changed = on_items_changed
        self._new_items: list[dict] = []
        public_folder = os.environ.get("PUBLIC")
        self.default_folder = (
            os.path.join(
                public_folder, "Daybreak Game Company", "Installed Games", "EverQuest"
            )
            if os.name == "nt" and public_folder
            else ""
        )
        self.folder_var = tk.StringVar(value=self.default_folder)
        self.path_var = tk.StringVar()
        self.character_var = tk.StringVar()
        self.server_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Enter your character and server, then find the export.")
        self._build()
        for variable in (self.folder_var, self.character_var, self.server_var):
            variable.trace_add("write", self._on_lookup_inputs_changed)

    def _build(self):
        instructions = ttk.LabelFrame(self, text="Step 1: Create your inventory file", padding=8)
        instructions.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(instructions, text="In EverQuest, type this command and press Enter:").pack(anchor="w")
        ttk.Label(
            instructions, text="/outputfile inventory", font=("TkFixedFont", 10, "bold")
        ).pack(anchor="w", pady=2)
        ttk.Label(
            instructions,
            text="Wait for the file to be created before searching for it here.",
        ).pack(anchor="w")
        ttk.Label(
            instructions, text="You can click the file name in game to see where it was saved."
        ).pack(anchor="w")

        folder_frame = ttk.Frame(self)
        folder_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(folder_frame, text="EverQuest folder:").pack(side="left")
        ttk.Entry(folder_frame, textvariable=self.folder_var).pack(
            side="left", padx=4, fill="x", expand=True
        )
        ttk.Button(
            folder_frame, text="Use default folder", command=self._use_default_folder,
            state="normal" if self.default_folder else "disabled",
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            folder_frame, text="Browse file...", command=self._browse_inventory_file
        ).pack(side="left")

        loc_frame = ttk.Frame(self)
        loc_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(loc_frame, text="Character:").pack(side="left")
        ttk.Entry(loc_frame, textvariable=self.character_var, width=20).pack(side="left", padx=4)
        ttk.Label(loc_frame, text="Server:").pack(side="left")
        ttk.Entry(loc_frame, textvariable=self.server_var, width=15).pack(side="left", padx=4)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=8, pady=4)
        ttk.Button(btn_frame, text="Find file", command=self._find_file).pack(side="left")
        self.import_button = ttk.Button(
            btn_frame, text="Import", command=self._import_now, state="disabled"
        )
        self.import_button.pack(side="left", padx=(4, 0))

        ttk.Label(self, textvariable=self.status_var, wraplength=1050, anchor="w").pack(
            fill="x", padx=8, pady=(2, 4)
        )

        ttk.Label(
            self, text="Newly discovered items - click the Tradeskill column to tag one:"
        ).pack(anchor="w", padx=8, pady=(8, 0))
        self.new_items_tree = ttk.Treeview(
            self, columns=("tradeskill", "name", "quantity", "location", "description"),
            show="headings", selectmode="none",
        )
        _make_sortable(self.new_items_tree, {
            "tradeskill": "Tradeskill", "name": "Name", "quantity": "Qty",
            "location": "Location", "description": "Description",
        })
        self.new_items_tree.column("tradeskill", width=90, anchor="center")
        self.new_items_tree.column("quantity", width=60, anchor="center")
        self.new_items_tree.column("location", width=200)
        self.new_items_tree.column("description", width=220)
        self.new_items_tree.tag_configure("tradeskill", foreground="#1a7f37")
        self.new_items_tree.bind("<Button-1>", self._on_new_items_click)
        self.new_items_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _on_lookup_inputs_changed(self, *_args):
        self.path_var.set("")
        self.import_button.configure(state="disabled")
        self.status_var.set("When the export is ready, click Find file.")

    def _use_default_folder(self):
        self.folder_var.set(self.default_folder)

    def _browse_inventory_file(self):
        initial_folder = os.path.expandvars(os.path.expanduser(self.folder_var.get().strip()))
        if not os.path.isdir(initial_folder):
            initial_folder = self.default_folder
        if not os.path.isdir(initial_folder):
            initial_folder = os.path.expanduser("~")
        path = filedialog.askopenfilename(
            title="Select /outputfile inventory export",
            initialdir=initial_folder,
            filetypes=[("EQ Inventory Export", "*-Inventory.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        parsed = inventory_import.parse_character_from_filename(path)
        if not parsed:
            self.status_var.set(
                "That filename does not include a character and server. "
                "Choose an *-Inventory.txt export."
            )
            return

        character_name, server = parsed
        self.folder_var.set(os.path.dirname(path))
        self.character_var.set(character_name)
        self.server_var.set(server)
        self.path_var.set(path)
        modified = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        self.status_var.set(
            f"Selected {os.path.basename(path)}. Last modified: {modified}. Ready to import."
        )
        self.import_button.configure(state="normal")

    def _find_file(self):
        self.path_var.set("")
        self.import_button.configure(state="disabled")
        folder = os.path.expandvars(os.path.expanduser(self.folder_var.get().strip()))
        character_name = self.character_var.get().strip()
        server = self.server_var.get().strip()
        if not character_name or not server:
            self.status_var.set("Enter both your character name and server before searching.")
            return
        if not os.path.isdir(folder):
            self.status_var.set("That folder does not exist. Check it or use Browse to choose the EverQuest folder.")
            return

        filename = f"{character_name}_{server}-Inventory.txt"
        path = os.path.join(folder, filename)
        if not os.path.isfile(path):
            self.status_var.set(
                f"Could not find {filename}. Run /outputfile inventory in game, then search again."
            )
            return

        self.path_var.set(path)
        modified = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        self.status_var.set(f"Found {filename}. Last modified: {modified}. Ready to import.")
        self.import_button.configure(state="normal")

    def _import_now(self):
        path = self.path_var.get().strip()
        character_name = self.character_var.get().strip()
        server = self.server_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("Missing file", "Find a valid inventory export before importing.")
            return
        if not character_name or not server:
            messagebox.showwarning("Missing name", "Enter both character name and server first.")
            return
        base_location = f"{character_name} ({server})"

        try:
            rows = inventory_import.parse_outputfile(path)
        except ValueError as exc:
            messagebox.showerror("Parse error", str(exc))
            return

        totals = inventory_import.aggregate_by_item(rows)
        new_items = []
        for (name, eq_item_id, area), quantity in totals.items():
            item_id, created = db.upsert_item_from_import(name, eq_item_id)
            location_name = f"{base_location} - {area}"
            location_id = db.get_or_create_location(location_name)
            db.set_item_location(item_id, location_id, quantity)
            if created:
                new_items.append({
                    "item_id": item_id, "name": name, "quantity": quantity, "location": location_name,
                })

        db.touch_character_import(character_name, server)
        self.status_var.set(
            f"Imported {len(totals)} item/location entries for '{base_location}'. "
            f"{len(new_items)} new item(s) discovered."
        )
        self._new_items = sorted(new_items, key=lambda entry: entry["name"])
        self._refresh_new_items_view()

        if self.on_items_changed:
            self.on_items_changed()

    def _refresh_new_items_view(self):
        for row in self.new_items_tree.get_children():
            self.new_items_tree.delete(row)
        for entry in self._new_items:
            item = db.get_item(entry["item_id"])
            if not item:
                continue
            is_tradeskill = bool(item["tradeskill_flagged"])
            checkbox = "\u2611" if is_tradeskill else "\u2610"
            self.new_items_tree.insert(
                "", "end", iid=str(entry["item_id"]),
                values=(checkbox, entry["name"], entry["quantity"], entry["location"], item["notes"] or ""),
                tags=("tradeskill",) if is_tradeskill else (),
            )

    def _on_new_items_click(self, event):
        region = self.new_items_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.new_items_tree.identify_column(event.x)
        row = self.new_items_tree.identify_row(event.y)
        if not row or col != "#1":  # "#1" is the Tradeskill checkbox column
            return
        item_id = int(row)
        item = db.get_item(item_id)
        if not item:
            return
        new_flag = not bool(item["tradeskill_flagged"])
        db.update_item(item_id, item["name"], item["eq_item_id"], item["notes"] or "", new_flag)
        self._refresh_new_items_view()
        if self.on_items_changed:
            self.on_items_changed()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EQ Tradeskill Helper")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(1200, screen_width - 80)
        height = min(820, screen_height - 100)
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(900, width), min(650, height))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        items_tab = ItemsTab(notebook)
        recipes_tab = RecipesTab(notebook)
        characters_tab = CharactersTab(notebook)

        def refresh_all():
            items_tab.refresh()
            recipes_tab.refresh()
            characters_tab.refresh()

        import_tab = ImportTab(notebook, on_items_changed=refresh_all)

        notebook.add(items_tab, text="Items")
        notebook.add(recipes_tab, text="Recipes")
        notebook.add(characters_tab, text="Characters")
        notebook.add(import_tab, text="Import")


def run():
    db.init_db()
    app = App()
    app.mainloop()

"""
RadioAI Studio Pro — Instant Jingles seed data.

One-shot seed — only runs if the jingle_pallets table is empty.
Mirrors the exact 5 pallets + 30 KISS MAIN pads from Figma node 44:688.

Pad positions:
    pad_index 1  → top-left   (label "N30")
    pad_index 5  → top-right  (label "N26")
    pad_index 24 → row 5 col 4 — INTENTIONALLY EMPTY ("NEW ENTRY" slot)
    pad_index 30 → bottom-right (label "N1")

KISS MAIN colors are read off the Figma reference (eyeball-matched, not exact
hex from the design file). The spec is the visual; tweak in the editor later
if needed.
"""

import logging

log = logging.getLogger("seeds_instant")


# ── Pallets ───────────────────────────────────────────────────────────────
# (name, owner, grid_cols, grid_rows, audio_output, display_order)
PALLETS = [
    ("KISS MAIN",  "DJ Kavish",  5, 6, 3, 0),
    ("DJ VAS",     "DJ Vas",     5, 4, 3, 1),
    ("LATE NIGHT", "Night Show", 4, 4, 3, 2),
    ("TOP 30",     "Chart Show", 5, 3, 3, 3),
    ("VALAS",      "Weekend",    3, 3, 3, 4),
]

# ── KISS MAIN pads — 30 pads in 5×6 grid, top-to-bottom left-to-right ────
# Tuple: (pad_index, label, color)
# pad_index=24 has label "" and is intentionally left empty (NEW ENTRY slot).
_EMPTY_PAD_INDEX = 24

KISS_MAIN_PADS = [
    # Row 1 — N30..N26
    ( 1, "N30", "#f59e0b"),  # orange  (this is the selected pad in Figma)
    ( 2, "N29", "#10b981"),  # green
    ( 3, "N28", "#3b82f6"),  # blue
    ( 4, "N27", "#be123c"),  # blood red
    ( 5, "N26", "#8b5cf6"),  # purple
    # Row 2 — N25..N21
    ( 6, "N25", "#14b8a6"),  # teal
    ( 7, "N24", "#ec4899"),  # pink
    ( 8, "N23", "#ca8a04"),  # gold
    ( 9, "N22", "#9f1239"),  # maroon
    (10, "N21", "#92400e"),  # brown
    # Row 3 — N20..N16
    (11, "N20", "#16a34a"),  # emerald
    (12, "N19", "#1e40af"),  # navy blue
    (13, "N18", "#7c3aed"),  # purple-dark
    (14, "N17", "#9f1239"),  # maroon
    (15, "N16", "#78350f"),  # dark brown
    # Row 4 — N15..N11
    (16, "N15", "#0891b2"),  # cyan-dark
    (17, "N14", "#6d28d9"),  # purple
    (18, "N13", "#0d9488"),  # teal-dark
    (19, "N12", "#7f1d1d"),  # dark maroon
    (20, "N11", "#92400e"),  # brown
    # Row 5 — N10, N9, N8, [EMPTY], N6
    (21, "N10", "#16a34a"),  # green
    (22, "N9",  "#9f1239"),  # maroon
    (23, "N8",  "#06b6d4"),  # cyan
    (24, "",    "#f59e0b"),  # ← EMPTY SLOT (NEW ENTRY in Figma)
    (25, "N6",  "#8b5cf6"),  # purple
    # Row 6 — N5..N1
    (26, "N5",  "#22c55e"),  # green
    (27, "N4",  "#65a30d"),  # olive
    (28, "N3",  "#f43f5e"),  # bright red/rose
    (29, "N2",  "#ec4899"),  # pink
    (30, "N1",  "#06b6d4"),  # cyan
]


def seed_if_empty(db) -> bool:
    """Insert the 5 pallets + KISS MAIN pads only if jingle_pallets is empty.
    Returns True if seeding happened, False if data was already present."""
    existing = db.get_pallets()
    if existing:
        log.info(f"Pallets already exist ({len(existing)} pallets) — skip seed")
        return False

    log.info("Seeding instant jingles pallets + KISS MAIN pads")

    pallet_ids = []
    for name, owner, cols, rows, audio_out, order in PALLETS:
        pid = db.add_pallet({
            "name":          name,
            "owner":         owner,
            "grid_cols":     cols,
            "grid_rows":     rows,
            "audio_output":  audio_out,
            "display_order": order,
        })
        pallet_ids.append(pid)

    # Fill KISS MAIN with the 30 designed pads
    kiss_main_id = pallet_ids[0]
    for pad_index, label, color in KISS_MAIN_PADS:
        db.add_pad({
            "pallet_id": kiss_main_id,
            "pad_index": pad_index,
            "label":     label,
            "color":     color,
            "behaviour": "play_once",
        })

    # Other pallets get empty grids matching their declared size — this lets
    # the UI render the slots so the user can assign audio later.
    for (pid, (name, _o, cols, rows, _ao, _do)) in zip(pallet_ids[1:], PALLETS[1:]):
        for idx in range(1, cols * rows + 1):
            db.add_pad({
                "pallet_id": pid,
                "pad_index": idx,
                "label":     "",
                "color":     "#f59e0b",
            })

    log.info(
        f"Seeded {len(pallet_ids)} pallets, "
        f"{len(KISS_MAIN_PADS)} KISS MAIN pads + empty grids"
    )
    return True

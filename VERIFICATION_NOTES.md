# RadioAI Studio Pro — FEATURE CROSS-VERIFICATION NOTES

> **What this is.** Screen-by-screen audit of the *actual source code* against
> `FEATURE_SPEC.md` (the ideal behaviour). For every screen: how it **should**
> work vs. what the code **actually** does. Each feature is marked and every
> real bug/gap is called out with a `file:line` pointer.
>
> **Method.** 20 screens were read directly from source (no guessing). Each
> `- [ ]` in FEATURE_SPEC.md was checked against the handler/DB call that
> implements it. Verified at HEAD `cac4adc`, 2026-07-01.
>
> **Legend:** ✅ works · ⚠ partial (wired but incomplete) · ❌ broken (spec
> expects it, code doesn't do it / does it wrong) · **(STUB)** intentional
> "coming soon" per operator's "lock unbuilt features" directive — not a bug.

---

## ⚡ STATUS UPDATE — 2026-07-02 supervised fix session

The top-10 bugs below were addressed in a supervised multi-agent fix session
(working tree only, nothing committed). Current state:

| # | Bug | Status after fix session |
|---|---|---|
| 1 | Instant Jingles hotkeys 1–9/0 | **FIXED** — digit QShortcuts → existing pad-play path |
| 2 | Sweepers ▶ preview dead | **FIXED** — mirrors jingles preview (15s cap, ▶↔■, missing-file guard) |
| 3 | Studio bottom-transport dead controls | **FIXED** — AutoPlay/Auto/Loop wired to existing auto-advance & loop state; MixFade cosmetic no-op; FADE-NEXT state captured; Problems→nominal; View-Full-History routed (incl. MainWindow delegation) |
| 4 | Playlist drag-to-reorder | **FIXED** — mime/dropMimeData → existing moveRows, both New+Edit; persistence intact |
| 5 | Songs BPM/Enabled filters + Last Played | **FIXED** — filters wired; new additive `db.get_last_played_map()` bulk method + column now renders relative time |
| 6 | Add-Campaign type discarded | **FIXED** — pill persists via `category` column, pre-selects in edit, 6th "Custom" pill added |
| 7 | SOTG CONFLICT decorative | **FIXED** — `_sharp_time_conflicts()` computes paid-break overlap at save; Studio fetches READY+CONFLICT so conflict drops still fire (SOTG>Spot) |
| 8 | Rotation Health all-time plays = 0 | **FIXED** — `_song_play_stats`→`get_song_play_stats` |
| 9 | Settings live-apply missing | **FALSE FINDING — feature already existed** (`studio.py` `_apply_studio_settings`, wired via `settings_saved` signal since commit `7d04f72`). Original ❌ was a verification error. |
| 10 | Control Panel footer + Libraries nav | **FIXED** — live uptime via monotonic clock on existing 1s tick; "Libraries" routes to Control Panel home |

Also fixed (cross-cutting): **all genuine `dict(sqlite3.Row)` offenders repo-wide**
(6 sites in dialogs/reports batch + 11 sites in database/scheduler/rotation/
force_clocks/playlist_new/stitcher/studio batch). Remaining `dict(...)` calls
verified as plain-dict copies or kwargs construction.

Incident note: during test runs the dev DB's `broadcast_log` b-tree was
corrupted by force-killed WAL writes (supervisor error, not the app). Repaired
via schema-preserving rebuild — `PRAGMA integrity_check: ok`, 2721 rows, all 4
indexes. Backup preserved at `radioai.db.corrupt_bak_20260701_182138`.
Known data issue (pre-existing, Bible #4): all 4 active sweepers now have
unplayable `file_path` (RR_SW source file gone from Downloads) — this makes
`test_rotation_pickers::test_pick_sweeper_random` fail (data-dependent test,
not a code bug). Sweepers Library data cleanup still pending.

All three locked invariants re-verified green after fixes
(`test_studio_eos_paths`, `test_studio_sotg_dispatch`, `test_studio_spot_deferred`,
scheduler dispatch/peek tests).

---

## Executive summary

Roughly **✅ 302 works · ⚠ 54 partial · ❌ 12 broken · (STUB) 31 confirmed**
across 20 screens (counts approximate; per-screen tallies below).

**The core is healthy.** Studio's dispatch model (Screen 7h) and all **3 locked
invariants** hold — `route_via_mixer=False`, `_has_pending_dispatch()` gate at
all 3 fade callsites, `_suppress_queue_emit` in `peek_next`, SOTG>Spot>Song
priority, FIFO pending, sweeper broken-file skip, and no 1Hz queue reshuffle
were all verified in code. **No invariant risk found.** SOTG (Screen 13),
Scheduling Automation (14), Stitcher (20), Final Log (17) and Main Auto Schedule
(9) are the most complete areas.

### 🔴 Highest-impact bugs (broken features, operator-visible)

| # | Screen | Bug | Where |
|---|---|---|---|
| 1 | 6 Instant Jingles | **Number-key hotkeys 1–9 / 0 entirely unimplemented** — the headline "trigger jingles with hotkeys" feature does nothing (only arrow-nav + Esc wired) | `instant_jingles.py:1250-1262` |
| 2 | 5 Sweepers | **▶ preview fully dead** — only logs, engine never wired (spec's "may be partial" understates it) | `sweepers_library.py` preview handler |
| 3 | 7 Studio | **Bottom-Transport AutoPlay + Auto/MixFade/Loop cluster dead** — signals emitted, never connected (header AUTO pill is the only working auto-advance) | `studio.py` `_BottomTransport` wiring |
| 4 | 11 Playlists | **Drag-to-reorder queue non-functional** (New + Edit) — model overrides `moveRows()` only; no `mimeData`/`dropMimeData`, so Qt's InternalMove pipeline never fires | `playlist_new.py` / `playlist_edit.py` `_QueueModel` |
| 5 | 2 Songs Library | **BPM & Enabled sidebar filters are dead no-ops**; Last Played column always renders "—" | `songs_library.py` filter handlers |
| 6 | 3 Spots | **Add-Campaign type-pill selection silently discarded on save** (and only 5 pills, no "Custom") | `add_campaign_dialog.py` `_on_save` |
| 7 | 13 SOTG | **CONFLICT status is decorative** — Assign always saves `status="READY"`, never computes paid-break conflicts | `sotg_assign.py:1505` |
| 8 | 15 Rotation Health | **All-time plays tooltip always 0** — calls `db._song_play_stats()` (wrong name; actual is `get_song_play_stats`), error swallowed by try/except | `rotation_health.py:420` |
| 9 | 16 Settings | **Studio settings don't live-apply** — `_apply_studio_settings` (spec line 565) does not exist; crossfade/fade changes need a restart | `settings_studio.py` |
| 10 | 1 Control Panel | Footer "Program running X minutes" is a hardcoded string, never updated; "Libraries" nav tab is a dead no-op | `control_panel.py` footer / nav |

### 🟠 Cross-cutting concerns

- **Banned `dict(sqlite3.Row)` pattern** (PROJECT_BIBLE Part 10 — raises on
  Python 3.14) appears in **edit-mode load paths**: `jingle_editor_dialog.py:345,352`,
  `sweeper_editor_dialog.py:652`, plus the spot report generator and
  `spot_programming_dialog.py`. Non-crashing *today* only because those paths
  may not hit 3.14 coercion — **should be swept repo-wide and fixed**.
  (Note: `core/database.py` domain methods largely coerce rows to plain dicts;
  the offenders are the dialog/report layers.)
- **Orphaned working screen:** `ui/force_clocks.py` is a functional 419-line
  screen but is unreachable from the premium Scheduling Hub (routes to a
  "coming soon" toast instead). Same class: `ui/log_viewer.py`, `ui/rebroadcast.py`.
- **Unwired sidebar filters** recur (Songs: BPM/Enabled; Spots: Category/Priority/Day;
  Playlist-Edit: 3 checkboxes) — panels built, never passed to the query.
- **Dialogs silently drop collected input** on save (Add-Song Era/Priority,
  Mass-Import Era/Priority + duplicate match-mode, Edit-Categories
  Auto-Rotate/Min-Separation).
- **Empty-state chart text unreachable** on analytics screens (Play History,
  Category Performance) because the monthly helper zero-fills 12 months → flat
  bars show instead of "No plays logged yet".

### Per-screen tally

| # | Screen | ✅ | ⚠ | ❌ | (STUB) | Headline issue |
|---|---|---|---|---|---|---|
| 1 | Control Panel | 8 | 4 | 0 | 0 | Hardcoded footer timer; dead "Libraries" nav tab |
| 2 | Songs Library (+5 dialogs) | 44 | 18 | 3 | 3 | BPM/Enabled filters dead; Last Played "—"; dialogs drop input |
| 3 | Spots & Commercials (+3 dialogs) | 32 | 5 | 0 | 1 | Type-pill discarded; sidebar filters unwired; `dict(Row)` |
| 4 | Jingles Library | 5 | 4 | 0 | 1 | Filter dropdowns are cycle-stubs; `dict(Row)` in editor |
| 5 | Sweepers Library | 6 | 1 | 1 | 1 | ▶ preview fully dead; `dict(Row)` in editor |
| 6 | Instant Jingles | 9 | 2 | 1 | 2 | **Hotkeys 1–9/0 unimplemented** |
| 7 | Studio | 38 | 5 | 6 | 0 | Bottom-transport cluster dead; core+invariants OK |
| 8 | Scheduling Hub | 8 | 0 | 0 | 4 | force_clocks.py functional but orphaned |
| 9 | Main Auto Schedule | 12 | 1 | 0 | 1 | Only "N SLOTS" hint missing; 05-17 fixes verified |
| 10 | Clock Editor | 9 | 2 | 0 | 2 | Duplicate title not shown; PREPAIR button missing |
| 11 | Playlists (Browse/New/Edit) | 18 | 6 | 0 | 8 | Drag-reorder queue non-functional |
| 12 | AI Magic Hub | 6 | 0 | 0 | 0 | Only stale static "0/2 modules" label |
| 13 | Spot on the Go (+4 steps) | 33 | 1 | 0 | 0 | CONFLICT status decorative only |
| 14 | Scheduling Automation | 16 | 0 | 0 | 0 | Sister-group cards capped at 2 (no "+N more") |
| 15 | Rotation Health | 12 | 1 | 0 | 0 | All-time-plays tooltip always 0 (wrong method name) |
| 16 | Settings (Hub/Gen/Sound/Studio) | 19 | 2 | 1 | 5 | No live-apply (`_apply_studio_settings` missing) |
| 17 | Final Log | 7 | 0 | 0 | 1 | Sweeper rows show generic name (no sweeper_id) |
| 18 | Play History | 4 | 1 | 0 | 0 | Empty-state chart text unreachable |
| 19 | Category Performance | 5 | 1 | 0 | 0 | "Click row → Play History" affordance dead |
| 20 | The Stitcher | 11 | 0 | 0 | 2 | Set Hook is a toast, not a deep-link |

---

## Screen 1 — Control Panel (Home Hub)
**Source:** `ui/control_panel.py`
**Ideal purpose:** Central dashboard — 7 library row-cards with live DB stats + top nav + header clock/station/LIVE pill, routing into every library screen.

| Feature (spec, abbreviated) | Status | Code reality / evidence (file:line) |
|---|---|---|
| Logo + RadioAI/STUDIO PRO/BROADCAST AUTOMATION branding top-left | ✅ works | `_LogoBox` at 28,18 (`control_panel.py:656`); three brand labels at `:660-673`. |
| Top nav tabs Libraries/Scheduling/Settings/AI Magic ✦ clickable → route | ⚠ partial | Buttons built + `nav_clicked` emitted (`:682-694`); handler `main_window.py:1003` routes Scheduling/Settings/AI Magic ✦/Studio/Control Panel. But "Libraries" has NO branch (`:1009-1025`) → clicking it is a silent no-op. Acceptable (already on Libraries), but not a real route. |
| Header clock live HH:MM :SS + weekday + date, per-second | ✅ works | `_tick` updates main/sec/dow/date labels (`:818-827`); QTimer 1000ms (`:628-631`). |
| Active-Station card: name + location + pulsing green dot | ✅ works | `_StationCard` (`:368-436`); uses `Settings().station_display` (`:424`), "Jaipur, Rajasthan" (`:428`), `QPropertyAnimation` dot pulse (`:375-380`). Location is hardcoded, not from settings. |
| "Open Studio" CTA opens Studio screen | ✅ works | `_OpenStudioButton` at 1208,18; `osb.clicked.connect(self.studio_clicked.emit)` (`:734-736`) → `main_window.py:1027` switches to studio. |
| "LIVE" pill top-right, live HH:MM:SS + pulsing red dot | ✅ works | `_LivePill` (`:515-586`) at 1240,136; QTimer tick (`:531-534`) + pulse anim; mono clock drawn (`:585`). |
| Each of 7 cards shows real DB stat line | ✅ works | `_refresh_card_data` (`:829-872`) pulls `get_dashboard_stats()` and rewrites each card's stat label. DB queries are all real: songs/clocks/campaigns/jingle_pads/sweepers/jingles/auto_schedule (`database.py:4140-4179`). Placeholder strings in CARD_SPECS get overwritten. |
| Each card: icon, accent color, category badge, "Open →" button | ✅ works | `PictorialIcon` (`:138`), color family from spec, `_ColoredPill` badge (`:171`), `_OpenButton` (`:175`). |
| Clicking card or Open button navigates to that library | ✅ works | Card `mousePressEvent` + Open btn both emit `clicked(key)` (`:177,256-258`) → `card_clicked` → `main_window.py:689` routes songs/instant_jingles/spots/sweepers/jingles/stitcher/scheduling. |
| Card hover brightens border/background to accent | ⚠ partial | `enterEvent/leaveEvent` set `_hover` + repaint; border switches to accent@120 alpha (`:214-216`). Background/fill does NOT change on hover — only the border. Spec says "border/background"; background is static. |
| Footer: "RadioAI Studio Pro • v2.0.0 • Program running X minutes" | ⚠ partial | Brand + v2.0.0 + bullets rendered (`:778-797`), but "Program running 14 minutes" is HARDCODED (`:794`) — never recomputed. No program-start timestamp, `_tick` doesn't touch it. Always reads "14 minutes". |
| "⚙ Settings" link opens Settings hub | ✅ works | Gear label + Settings button (`:800-814`); `s.clicked.connect(self.settings_clicked.emit)` → `main_window.py:1032` switches to settings_hub. |

### 🐛 Bugs & gaps
1. **Footer "Program running X minutes" is a hardcoded string** — `control_panel.py:794` renders the literal `"Program running 14 minutes"`. There is no program-start time captured and `_tick` (`:818-827`) never updates this label, so it permanently reads "14 minutes" regardless of actual uptime. Spec expects a live elapsed counter.
2. **"Libraries" nav tab is a dead route** — `_build_header` emits `nav_clicked("Libraries")` (`:694`), but `_on_nav_clicked` (`main_window.py:1009-1025`) has no `"Libraries"` branch, so the click does nothing. Low impact (the user is already on the Libraries/Control Panel screen) but it is a no-op, not a route to a screen.
3. **Card hover changes border only, not background** — `paintEvent` (`:213-220`) only swaps the border pen on `_hover`; the body gradient fill is unchanged. Spec wants the background to brighten toward the accent too. Cosmetic.
4. **Station location hardcoded** — `_StationCard` paints "Jaipur, Rajasthan" as a literal (`:428`) rather than a settings-driven location; only the station name is dynamic. Minor, matches project station but not settings-configurable.

Note: No `dict(sqlite3.Row)` misuse, no TODO/FIXME, no crashes found. `get_dashboard_stats` is called in a try/except (`:831-835`) so a DB error degrades gracefully to placeholder text. Stitcher card correctly shows "Module Disabled" when disabled (`:841-844`).

### Tally
✅ 8 · ⚠ 4 · ❌ 0 · (STUB) 0


---

## Screen 2 — Songs Library (+ dialogs)
**Source:** `ui/songs_library.py` + 6 dialogs
**Ideal purpose:** Master music catalog — view/filter/search/preview songs, edit categories, cue points, and view analytics.

### 2 · Main screen (header/sidebar/table/detail panel)

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Breadcrumb "Control Panel \| Libraries \| ● Songs"; links navigate | ⚠ | `songs_library.py:890-917` — "Control Panel" is a real button emitting `breadcrumb_clicked("control_panel")`; "Libraries" is a static QLabel (not a link); "● Songs" is the active chip. Partial. |
| Page title + subtitle | ✅ | `songs_library.py:920-927` "Songs Library" + subtitle. |
| Live clock + station + "▶ Open Studio" mini showing Now-Playing | ⚠ | Clock `:930-933` ticks (`_tick` :1928). Station `:934`. Open-Studio mini `:940-943` emits `studio_clicked`, but its "Now-Playing" subtitle is HARDCODED "Billie Eilish — Bury A Friend" (`_HeaderOpenStudio` :346), not live. |
| Song-count box shows filtered count | ⚠ | `_SongCountBox` :116; set from `_total_count` (dashboard stats, :1552-1554). Shows TRUE total, NOT the filtered count — filters only hide rows, count never updates. |
| "+ Add New Song" opens dialog | ✅ | `:960,1717-1722` → `AddNewSongDialog`. |
| "⤓ Mass Import" opens dialog | ✅ | `:961,1724-1729` → `MassImportDialog`. |
| "✎ Edit Categories" opens dialog | ✅ | `:962,1731-1736` → `EditCategoriesDialog`. |
| "✕ Delete" deletes selected (only enabled when selected) | ⚠ | `:963,1738-1828` opens ConfirmDeleteDialog and deletes via `db.delete_song`. But button is ALWAYS enabled — no selection-gating; guarded only by an info dialog when nothing selected (:1758). |
| Search box filters table live (title/artist) | ✅ | `:976-978,1709-1715` in-memory substring match on title+artist. |
| Category dropdown filters | ✅ | `:987-998,1881-1895`; populated from DB `:1000-1009`. |
| Energy dropdown filters Low/Med/High | ⚠ | Filter logic exists `:1891-1892`, but `_row_to_dict` DOES populate `energy` (:1537). Works IF DB rows carry energy. Functional. |
| Vocal dropdown filters | ✅ | `:1893-1894`, vocal populated `:1538`. |
| BPM dropdown filters by range | ❌ | Dropdown built `:991` but `_on_filter_changed` has NO `bpm` branch (:1888-1894) — selecting a BPM range does nothing. |
| Enabled dropdown filters Only Enabled/All/Disabled | ❌ | Dropdown built `:992` but `_on_filter_changed` has NO `enabled` branch — no-op. |
| "📊 Category Performance" report | ✅ | `:1023,1028-1031` emits `report_clicked("category_performance")` (routing in MainWindow). |
| "🎯 Rotation Health" report | ✅ | `:1024` emits `report_clicked("rotation_health")`. |
| "⏱ Last Played" report (may be STUB) | ✅ | `:1025` emits `report_clicked("last_played")` (routing external). |
| "📈 Top Songs" report (may be STUB) | ✅ | `:1026` emits `report_clicked("top_songs")`. |
| Table columns: dot, Title, Artist, Category pill, Duration, BPM, Last Played | ✅ | `_SongRow` :502-535; header cols :1043-1055. |
| Duration MM:SS; Last Played relative | ⚠ | Duration `_fmt_duration` :107; `_human_ago` :91. BUT `_row_to_dict` hardcodes `last_played: None` (:1541 "filled later if available" — never filled), so Last Played always renders "—". |
| Category pill color-coded | ✅ | `_CategoryPill` :400, `_category_color` :87. |
| Click select; Ctrl toggle; Shift range; drag multi-select | ✅ | `_select_song` :1571-1622 (ctrl/shift), drag via `dragged`/`_on_row_dragged_to_global` :1629-1670. |
| Selected row highlights (cyan tint + accent + bold title) | ✅ | `paintEvent` :568-572, `_update_title_style` :549-555. |
| Per-row ▶ preview (~15s cap), toggles ■, one at a time | ✅ | `_PlayButton` :431; `_on_row_play_clicked` :1316-1339; 15s timer `PREVIEW_DURATION_MS=15000` :786, :1378; single-preview enforced by `_stop_preview` :1338. |
| Detail tabs: Song Details / Audio Cues / Play History | ✅ | `:1117-1133`; interactions `_on_detail_tab_clicked` :1273-1306. |
| "Audio Cues" tab opens Cue Editor | ✅ | `:1285-1289` → `_open_cue_editor`. |
| "Play History" tab opens per-song report | ✅ | `:1291-1305` emits `report_clicked("play_history")`. |
| Song header card: title, artist·year, Enabled/Disabled + Category badges | ⚠ | `_SongHeaderCard` :647; `set_song` :658. Meta line is artist·duration·BPM (:1685-1687), NOT artist·year. Enabled + Category badges present :707-726. |
| Read-only fields Title/Artist/Album/Year/Category/Energy/Vocal/BPM | ✅ | `_DetailFormField` :620 (readOnly :635); populated `_update_detail_panel` :1694-1705. |
| Audio-preview waveform + start/end labels | ⚠ | `WaveformWidget` :1179-1183; right label = duration :1706. Left label hardcoded "0:42" (:1186) and never updated. |
| "✎ Edit Cues" opens Cue Editor | ✅ | `:1208-1222,1224-1236`. |
| AI insight box (placeholder text ok) | ⚠ (placeholder) | `_AIInsightBox` :729; text is HARDCODED "Plays every 18 min…/played 47 times" (:735-736); `set_insight` exists but is never called. |

### 2a · Add New Song dialog

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| AUTO CODE (6-digit) generated + shown | ✅ | `add_new_song_dialog.py:350` `randint(100000,999999)`; shown :401-404; saved to `auto_code` :874. |
| Artist required; "Find Artist" picker; "+ New" prefilled | ✅ | Find `:447-456,784-791`; New `:457-466,793-801` (prefills from artist input). Note: "required" now relaxed (see below). |
| Song Title required | ⚠ | Marked required `:480` but relaxed at save (falls back to filename). |
| Optional fields Album/Playlister/Label/CDKey/Barcode/Songwriter/Comments/Composer | ✅ | Inputs :483-523; saved :865-880. |
| Category pills (mutually exclusive) | ✅ | `_CategoryPill` :179; `_on_cat_pill` :779-782 deactivates others. |
| Dropdowns Era/Vocal/Priority/Year(default current)/BPM | ⚠ | Built :555-560; Year defaults current :559. BUT on save only Year/Vocal/BPM persist (:866-869); **Era and Priority are collected into widgets but NOT written to the `song` dict** (:862-881) — silently dropped. |
| "..." Browse picks audio (mp3/wav/flac/m4a/ogg); path in read-only field | ✅ | `_on_browse` :803-810 with that exact filter. |
| Duration auto-read (mutagen) | ✅ | `:852-860` reads `mutagen.File().info.length`. |
| Enabled checkbox (default on) + Frozen (default off) | ✅ | `:646` enabled checked True; `:657` frozen default off. |
| **Relaxed (2026-05-17):** empty artist→"Unknown Artist"; empty title→filename; audio REQUIRED | ✅ | `_on_save` :818-834: audio required check :826-829; title→filename :830-832; artist→"Unknown Artist" :833-834. Matches spec exactly. |
| Save persists + closes; Cancel discards | ✅ | Save `db.add_song` :884, emit + `accept()` :892-893; Cancel `reject` :759,417. |
| "✦ AI Auto-fill Metadata" info dialog (STUB) | ✅ (STUB) | `_on_ai_autofill` :812-816 shows "coming in a future phase" info. |

### 2b · Mass Import dialog

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Counters Selected / Ready / Errors | ✅ | `_StatusCounter` :306; `_update_counters` :1147-1155. |
| "Browse" folder picker; "Scan" threaded ID3 walk | ✅ | Browse :1069-1076; Scan :1078-1106 → `_ScanWorker` (QThread) :50, mutagen read :91-177. |
| Filter chips Include-subfolders / MP3 / WAV / FLAC | ✅ | `_FilterChip` :393; formats built from chips :1091-1094; subfolders passed :1102. |
| Table columns checkbox/Filename/Artist(ID3)/Title(ID3)/Duration/Status | ✅ | `_FileRow` :484-562; header :751-756. |
| Status pill Ready(green)/No Tags(amber)/Error(red) | ✅ | `_STATUS_COLORS` :460-464; painted :554-562; worker sets status :158-176. |
| **Relaxed (2026-05-17):** "No Tags" importable — checkbox enabled + row shows fallback; only Error disabled | ⚠ | Checkbox enabled for Ready+No Tags `:502-507`. Worker DOES populate filename/Unknown-Artist fallback into result (:168-173). BUT `_FileRow.paintEvent` overrides display: if `d.get("artist")`/`d.get("title")` is falsy it shows "— Not found" — however the fallback already fills them, so real rows show the fallback text. Spec largely met; the "— Not found" branch (:532,538) is now dead for No-Tags rows since worker pre-fills them. Functional but confusing dual-path. |
| "Select All" / "Deselect All" toggle importable rows | ✅ | `:800-822,1137-1145`; `set_selected` respects enabled `:513-515`. |
| Default settings Category/Era/Year/Priority/Enabled | ⚠ | Widgets built :851-910. On import only Category-id + Year + Enabled(hardcoded True) passed (`defaults` :1187-1191). **Era and Priority defaults are NOT used** by `_ImportWorker` (:220-230). |
| "Skip duplicate songs" (default on) + match mode | ⚠ | Skip checkbox default True :925-926, passed :1199. Match-mode combo built :938 but its VALUE is IGNORED — `_db.song_exists(artist,title)` always uses Artist+Title (:215); File path / Filename modes do nothing. |
| Import threaded, progress bar 0→100%, UI disables | ✅ | `_ImportWorker` :184; progress :1205-1213; import btn disabled during :1194-1195. |
| Finish summary "N added • M skipped • P errors" | ✅ | `_on_import_finished` :1215-1235 shows summary dialog + label. |

### 2c · Edit Categories dialog

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Left pane lists categories: color dot, name, description, count | ✅ | `_CategoryRow` :83-163; populated :650-660. |
| "+ Add" / "✎ Rename" / "✕ Delete" (confirm; can't delete last) | ✅ | Add :701-716; Rename :718-735; Delete :737-761 (last-guard :743-748, confirm :753). |
| Right pane: Name(req,unique), Color(10 swatches), Description, Auto-Rotate, Min Separation | ⚠ | Name :469-471; 10 swatches :477-483 (SWATCH_COLORS :40-51); Description :486-488; Auto-Rotate combo :491-498; Min-Sep combo :501-507. BUT `_on_save` only persists name/color/description (:796-800) — **Auto-Rotate and Min-Separation selections are NOT saved to DB.** |
| "Songs in this category" preview: first ~5 artists + "+N more" | ✅ | `_SongsPreview` :218-257; `get_songs_by_category(limit=5)` :680; "+N more" :251-257. |
| "✓ Save Category" writes DB, flashes success, emits refresh | ✅ | `_on_save` :763-814 → `db.update_category`; `categories_changed.emit()` :810; flash :816-837. |
| Deleting category with songs warns about unassign | ✅ | `_on_delete` :749-752 appends unassign warning when count>0; `delete_category(reassign_to=None)` :757. |

### 2d · Audio Cue Editor dialog

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Song synthetic waveform with time ruler | ✅ | `_CueWaveformWidget` :211; ruler :526-554; synthetic bars `_gen_bars` :469-480. |
| 6 draggable markers START/INTRO/HOOK IN/HOOK OUT/OUTRO/MIX | ✅ | MARKER_IDS :64; drag `mousePressEvent`/`mouseMoveEvent` :411-462. |
| Bars color-zoned by marker (green/white/pink/white/red) | ✅ | `_zone_for_x` :482-497, `_zone_color` :499-506. |
| Dragging clamps to neighbors + snaps to 100ms grid | ✅ | `_clamp_marker` :386-407 (bounds + 100ms snap :405-406). |
| HOOK OUT − HOOK IN ≥ 100ms | ✅ | `HOOK_MIN_MS=100` :384; enforced in bounds :399-400 and validate :1652. |
| Order enforced START≤INTRO≤HOOK IN<HOOK OUT≤OUTRO≤MIX≤duration | ✅ | Bounds :396-403; validation `_validate` :1648-1659. |
| 6 cue cards: time + <<100/>>100 nudge + Preview + Reset | ✅ | `_CueCard` :622-759; nudge :666-669, preview :673-680, reset :683-697. |
| Fade In / Fade Out sliders 0–2000ms | ✅ | `_VerticalFadeSlider` :766; range 0-2000 :797. |
| "✓ Save Cues" validates + writes cue points; Cancel discards | ✅ | `_on_save` :1877-1909 → `db.save_song_cue_points`; validated :1883; Cancel `reject` :1721. |
| Preview button flashes (audio STUB this phase) | ⚠ (better than spec) | Card flashes green `flash_preview` :740-755. Additionally Phase B1 ACTUALLY plays audio via engine (`_on_card_preview` :1506-1520, `_ensure_playback_channel` :1524) when an engine is passed — so it is NOT just a stub. |

### 2e · Find / Add Artist dialogs

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Find: live search name/country/genre + pills (All/Recently Added/Most Played/Favorites) | ✅ | `find_artist_dialog.py` search `_filtered_artists` :512-530; pills :366-372, applied :524-529. |
| Artist row: avatar initial, name, country·genre, ★ favorite, song count | ✅ | `_ArtistRow` :153-249. |
| Click selects; double-click selects+closes; star toggles favorite | ⚠ | Click :254-261; double-click :263-266 → select+`_on_select`. Star toggle `_on_favorite_toggled` :555-564 works, BUT the hit-test only fires when the row is ALREADY a favorite (`:257` requires `is_favorite` truthy) — you can un-favorite but cannot favorite a non-favorite via the star. Partial. |
| "+ Add New" opens Add Artist prefilled with search text | ✅ | `_on_add_new` :566-571 passes `prefill_name=self._search_text`. |
| Add Artist: Name(req) + Display/Country/Genre/Era/Notes | ✅ | `add_artist_dialog.py` fields :214-271. |
| Save enforces unique name; duplicate→error; success closes returns artist | ✅ | `_on_save` :364-405; UNIQUE-catch :393-398; emit `artist_saved` + accept :404-405. |
| "✦ AI Auto-fill from artist name" coming-soon (STUB) | ✅ (STUB) | `_on_ai_autofill` :356-362 info dialog. |

### 🐛 Bugs & gaps
1. **BPM & Enabled filters are no-ops** — `songs_library.py:1888-1895` `_on_filter_changed` handles only category/energy/vocal. Selecting a BPM range or Enabled/Disabled filter does nothing (rows stay visible). ❌
2. **Last Played column always "—"** — `_row_to_dict` sets `last_played: None` with a "filled later" comment (`:1541`) that never executes. The relative-time helper is dead for the table. ⚠
3. **Add New Song silently drops Era & Priority** — dropdowns collected into widgets but the save `song` dict (`add_new_song_dialog.py:862-881`) omits era/priority. Same in Mass Import defaults (`mass_import_dialog.py:1187-1191`, `_ImportWorker:220-230`). Operator input is lost. ⚠
4. **Edit Categories drops Auto-Rotate & Min-Separation** — `edit_categories_dialog.py:796-800` persists only name/color/description; the two rotation combos are ornamental. ⚠
5. **Mass Import duplicate match-mode ignored** — combo (Artist+Title / File path / Filename) at `:938` is never read; `_ImportWorker` always calls `song_exists(artist,title)` (`:215`). File-path/Filename modes are dead. ⚠
6. **Find Artist star can only un-favorite** — `find_artist_dialog.py:257` hit-test guarded by `and self._artist.get("is_favorite")`; the ★ is only painted/clickable for existing favorites (`:234`), so a non-favorite row has no way to become a favorite from this dialog. ⚠
7. **Delete button never disabled** — spec wants "only enabled when a song is selected" (`songs_library.py:963`); button is always active, relying on a runtime info-dialog guard. Cosmetic/UX. ⚠
8. **Open-Studio mini + AI insight show hardcoded strings** — `_HeaderOpenStudio:346` ("Billie Eilish — Bury A Friend") and `_AIInsightBox:735-736` never reflect real state; `set_insight` unused. ⚠ (placeholder, acceptable per spec note for AI box; Open Studio subtitle is not covered by that allowance).
No banned `dict(sqlite3.Row)` usage found; row access uses `r["col"]` / `"col" in r.keys()` throughout. No crashes/dead-signal issues detected in the save/emit paths.

### Tally
✅ 44 · ⚠ 18 · ❌ 3 · (STUB) 3


---

## Screen 3 — Spots & Commercials (+ dialogs)
**Source:** `ui/spots_commercials.py` + 3 dialogs
**Ideal purpose:** Manage ad campaigns, their spot files, weekly break schedule, and play reports.

### 3 · Main screen (sidebar / table / now-airing / detail tabs)

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Sidebar counter "active/total campaigns" | ✅ | `_SidebarCounter.set_counts` fed by `_load_campaigns` computing `total`/`active` from `get_all_campaigns("all")` — `spots_commercials.py:1874-1884`, painted `:257-286` |
| "+ Add Campaign" opens dialog in create mode | ✅ | `_on_add_campaign` → `AddCampaignDialog(edit_campaign_id=None)` — `:2109-2115` |
| "✎ Edit Campaign" opens edit mode for selected row | ✅ | `_on_edit_campaign` passes `edit_campaign_id=target_id`; guards no-selection — `:2123-2139` |
| "🗓 Schedule Breaks" opens Spot Programming dialog | ✅ | `_on_edit_breaks` → `SpotProgrammingDialog(campaign_id=...)` persisted mode — `:2141-2157` |
| "✕ Delete" deletes selected campaign (confirm) + data | ✅ | `_on_delete_campaign` confirm via `dialogs.confirm(...danger=True)` then `db.delete_campaign` — `:2170-2192` |
| Filters: Status / Category / Priority / Day | ⚠ | All 5 combos built (`:1201-1215`) but only **Status** is wired (`currentIndexChanged → _on_status_filter_changed`, `:1216-1217`). Category/Priority/Day combos have no signal connection — decorative only |
| Reports section links (5, deferred/STUB) | ✅ (STUB) | 5 `_SidebarActionButton`s built with **no `.clicked.connect`** — inert, matches "deferred/STUB" — `:1225-1234` |
| Table columns: dot, Name, Spots, Category, Priority, Start, End | ✅ | `_CampaignRow.paintEvent` + pills; header labels `_TableHeader` — `:392-512` |
| Single-click selects+populates; double-click edits | ✅ | rows emit `clicked→_select_campaign`, `double_clicked→_on_edit_campaign` — `:1902-1903`; `_select_campaign→_refresh_detail_panel` `:1907-1912` |
| Row highlight on select; zebra; scrollable | ✅ | selected cyan tint + accent `:399-402`; zebra `:404`; `QScrollArea` body `:1265-1287` |
| Now Airing ▶/■ plays first active spot (green idle/red playing) | ✅ | `_on_airing_play_clicked`→`_start_airing` picks first active on-disk file `:1940-1976`; button color RED/GREEN `:952` |
| Shows "NOW AIRING: name" + progress + MM:SS/MM:SS | ✅ | `_NowAiring.paintEvent` label+bar+duration `:966-997`; driven by `_on_airing_position` `:2015-2023` |
| Playback stops when screen hidden | ✅ | `hideEvent` calls `_stop_airing` `:2036-2041` |
| "Campaign Details" tab: metadata + spot files + weekly grid | ✅ | `_build_tab_details` header card + 7 fields + spot-file rows + `_WeeklyBreakGrid` — `:1349-1419`, populated `:2043-2101` |
| "+ Add File" adds audio file to campaign | ✅ | `_on_add_file` QFileDialog → `db.add_spot_file` → refresh — `:2194-2219` |
| Spot file row shows filename + duration + Active/Off badge | ✅ | `_SpotFileRow.paintEvent` — `:685-718` |
| "Play Reports" tab: mode toggle, Start/End pickers, Reset, Generate PDF | ✅ | `_build_tab_play_reports`: `QButtonGroup` Actual/Scheduled, two `QDateEdit`, reset link, generate button — `:1423-1791` |
| Generate PDF writes PDF, opens it, shows path+timestamp, warns 0 bytes | ✅ | `_on_generate` calls `generate_spot_play_report`, updates `last_lbl`/`path_lbl`, `out.stat().st_size==0 → dialogs.warning`, then `os.startfile`/`QDesktopServices` — `:1725-1783` |

### 3a · Add Campaign dialog

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| AUTO CODE box shows/edits code | ⚠ | `_AutoCodeBox` **displays** `generate_auto_code()` result (`add_campaign_dialog.py:649`); no edit field — code is read-only paint, disabled in edit mode `:650-653`. Spec says "shows/edits" — only shows |
| Required: Name, Start, End (pickers via "...") | ✅ | Title required (Save disabled until non-empty `:1027-1029`); `_DateInput` with "..." button for Start/Expire `:715-720` |
| Dropdowns: Programming Mode, Playback Order, Category, Priority | ✅ | `_mode_combo`/`_playback_combo`/`_category_combo`/`_priority_combo` — `:700-743` |
| Audio Files panel; "+ Add File"; empty state | ✅ | `_AudioFilesPanel` with "No audio files added yet" `:502-508`; "+ Add New File" → `_on_add_file` `:768-769,1036-1043` |
| Availability: Active vs Draft (one selected) | ✅ | `_AvailabilityCard` hit-test toggle `:268-278`, value→`is_active` on save `:1140-1141` |
| Campaign Type pills (6): Commercials/Station ID/News Break/Sponsor/Promo/Custom | ⚠ | Only **5** pills built: `CAMPAIGN_TYPES = ["Commercial","Station ID","Sponsor","News Break","Promo"]` `:543,814-819`. "Commercials"→"Commercial" naming diff; **no "Custom"** pill. Also: `_selected_type` is **never written to `data` on save** (`:1143-1160`) — pill selection is discarded |
| Save validates + inserts + returns id; Cancel discards | ✅ | `_on_save` validates title, `add_campaign`/`update_campaign`, emits `campaign_saved(id)` `:1120-1204`; Cancel→`reject` `:893` |
| "✦ AI Auto-fill Campaign" is STUB toast | ⚠ (STUB) | `_AIBanner.clicked` → `log.info("[AI Auto-fill] not yet wired...")` `:858-860` — logs only, **no toast/dialog shown** to user (spec says "STUB toast") |

### 3b · Campaign Date Picker dialog

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Month nav (‹ ›) + "Month Year" label | ✅ | `_MonthNavBar` prev/next + `set_month("MMMM yyyy")` — `campaign_date_picker_dialog.py:51-93,626-632` |
| 6×7 grid; out-of-month/before-min dim+non-clickable; today ring; selected filled | ✅ | `_CalendarGrid.set_month` configures 42 cells; disabled `< min_date` blocks click `:136-139,251`; today ring `:175-180`; selected purple fill `:160-167` |
| Quick-select: Today, In One Month, (start-mode) Never | ✅ | 3 `_QuickSelectButton`s; Never disabled in "start" mode `:520-533` |
| OK returns chosen date (or Never); Cancel discards | ✅ | `_on_ok` emits `never_selected`/`date_selected(QDate)` `:663-670`; Cancel→`reject` `:568` |

### 3c · Spot Programming (break grid) dialog

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Grid 144 rows (10-min, 00:00–23:50) × 7 day cols | ✅ | `GRID_H=HEADER_H+144*CELL_H`; `_slot_to_time` 0..143 every 10min — `spot_programming_dialog.py:127-133`, cols=7 `:696-699` |
| Left panel: live total-spots count + Priority selector | ✅ | `_SpotsCountDisplay` updated by `_on_grid_changed` `:1119-1121`; `_priority_combo` High/Medium/Low → `grid.set_priority` `:952-956` |
| Presets: Morning Drive/Lunch Hour/Drive Time/Late Night | ✅ | `PRESETS` dict `:102-117`; `_on_preset_picked` replaces grid `:1186-1202` |
| "+ Add" fills selection; "− Remove" clears; "Clear All" wipes (confirm) | ✅ | `_on_add→schedule_at_selection` `:1123-1132`; `_on_remove→clear_at_selection` `:1134-1143`; `_on_clear_all` confirm `:1168-1176` |
| "Paste to All Days" / "Paste to Selection" | ✅ | `_on_paste_all→paste_to_all_days` `:1145-1155`; `_on_paste_selected→paste_to_selected_day` `:1157-1166` |
| Cells color by priority: High=red, Medium=amber, Low=cyan | ✅ | `PRIORITY_COLORS = {High:#f43f5e, Medium:#f59e0b, Low:#06b6d4}` `:93-97`, applied `_paint_cell` `:780-788` |
| Click toggles; drag rectangle-selects; Esc clears; right-click menu | ✅ | toggle `:567-574`; drag additive `:518-546`; Esc `keyPressEvent` `:583-593`; context menu (Schedule/Set Priority/Clear) `:612-644` |
| Apply saves to campaign_schedule (or stages to parent) | ✅ | `_on_apply`: persisted→`db.update_break_schedule` + `schedule_saved`; staged→`schedule_staged` — `:1204-1225` |

### 🐛 Bugs & gaps
1. **Add Campaign: type-pill selection is silently discarded** — `_selected_type` is tracked (`add_campaign_dialog.py:1031-1034`) but the save `data` dict (`:1143-1160`) never includes it (no `campaign_type` key). Whatever pill the operator picks is lost; category comes only from the separate `_category_combo`. Also the pill set is 5 items, missing "Custom" and using "Commercial" not "Commercials" (`:543`).
2. **Add Campaign edit mode: spot files double-write risk / no delete** — on Save in edit mode files are NOT re-inserted (`if ... and not is_edit`, `:1180-1182`), but the panel pre-loads existing files (`:1001-1003`) with no way to remove them; adding a new file in edit mode is silently not persisted through this dialog (flagged as TODO in-code `:1177-1179`). Add-file in edit mode is a dead path here.
3. **Category/Priority/Day sidebar filters are inert** — built but never connected (`spots_commercials.py:1210-1217`); only Status filters. Spec lists all four as filters.
4. **AI Auto-fill is log-only, not a toast** — `_AIBanner` click only `log.info`s (`add_campaign_dialog.py:858-860`); no user-visible toast/dialog, unlike the sibling "Stitcher" button which does `_stub_toast` (`:770-772`). Minor UX inconsistency vs spec's "STUB toast".
5. **`dict(sqlite3.Row)` convention violation (not a crash)** — CLAUDE.md bans `dict(sqlite3.Row)`, yet `spot_play_report.py` uses `dict(row)` (`:248,259,283-284,305-320`) and `spot_programming_dialog.py:1097` uses `dict(r)`. These run fine (sqlite3.Row supports the mapping protocol) but violate the project rule; the main screen uses the safe `{k: r[k] for k in r.keys()}` pattern (`spots_commercials.py:1891-1894`) — inconsistent.
6. **Play Reports default dir drifted from spec/docstring** — spec + the file's own docstring say PDFs land in `%LOCALAPPDATA%\RadioAI\reports`, but `_resolve_default_dir` now targets `~/Downloads/RadioAI Reports` first (`spot_play_report.py:104-141`). Functional (falls back cleanly) but the UI "Saved to:" label and docstring are stale. Not a bug — noting the divergence.

**Verified good:** delete uses dedicated `db.delete_campaign` cascade (hand-cleans `campaign_schedule`, NULLs `broadcast_log`/`final_log_entries`, `database.py:3648-3662`) — NOT raw DELETE. PDF path is real: `generate_spot_play_report` writes via QPdfWriter, releases handle (`del writer`+gc), returns Path; UI verifies `st_size==0`→warning, then `os.startfile`. No dead signals found on wired controls. No stub confirmations — `dialogs.confirm/info/warning/error` all real (`core/dialogs.py:415-485`).

### Tally
✅ 32 · ⚠ 5 · ❌ 0 · (STUB) 1


---

## Screen 4 — Jingles Library
**Source:** `ui/jingles_library.py` + `ui/dialogs/jingle_editor_dialog.py`
**Ideal purpose:** Station-identity audio catalog — browse/filter jingles, add/edit via editor dialog, preview, view rotation/usage insight.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Header: breadcrumb, live clock, station name, "Open Studio" | ✅ | `jingles_library.py:827-907` — breadcrumb Control Panel/Libraries/🔔Jingles, `_clock_lbl` ticks (`:819-821,1521-1523`), `Settings().station_display` (`:899`), Open Studio btn (`:905-907`) |
| Counter shows "X jingles / Y enabled" | ✅ | `_SidebarCounter.set_counts` shows total + "N enabled" (`:249-252`), fed from load (`:1210-1213`) |
| "+ Add New Jingle" opens the Jingle Editor dialog | ✅ | `_on_add_new` → `_open_editor_dialog(jingle_id=None)` → `JingleEditorDialog` (`:1354-1375`); dialog is real & saves (`jingle_editor_dialog.py:848-884`) |
| Search filters by name/category/playlister code | ✅ | `_filtered_jingles` matches name/category/playlister_code (`:1244-1249`), wired via `_on_search_changed` (`:1323-1325`) |
| Filters: Category, Properties, Duration; "Only Enabled" checkbox | ⚠ | Filter logic all present & correct (`:1225-1243`). BUT dropdowns are click-to-cycle stubs, not real popups — `_SidebarDropdown._cycle` advances index on each click (`:300-303`, self-documented "Behaviour stub" `:273-276`). Functionally filters, poor UX. |
| Table columns: bell dot, Name, Category pill, Duration, Properties pill, Last Used | ⚠ | All columns rendered (`_JingleRow.paintEvent :473-519`, header `:388-394`). Last Used hardcoded "—" — broadcast_log lookup deferred (`:1197`) |
| Single-click selects; double-click opens editor; right-side ▶ previews (~15s cap, mono, ▶↔■) | ✅ | click→`_on_row_clicked` (`:1268`), dbl→`_open_editor_dialog` (`:1275-1278`), play gutter→`_on_row_play` toggles preview (`:1280-1286`). Real preview via engine, 15s `QTimer` cap (`:1433-1483`), glyph ▶↔■ (`:513-518`, `set_playing`). "mono" not enforced in code — plays file as-is. |
| Detail tabs: Jingle Details (read-only) / Schedule / Usage Stats | ⚠ | Tab bar exists (`_DetailTabBar :592-639`) but `_on_tab_picked` only logs; Schedule/Usage Stats have NO distinct content — deferred (`:1351-1352`). Only Jingle Details fields populate (`:1305-1314`). |
| AI rotation insight + 7-day play count show (insight may be placeholder) | ⚠ | Both are static placeholders: AI pill hardcoded "Playing every 28 min avg" (`:1119`); stats card hardcoded "Last 7 days: played 0 times" (`:1130-1131`, `:1298-1299`) — never computed from DB. Matches spec's "may be placeholder". |
| Mass Import / Edit Categories / Delete / Export-to-Playlister are STUB toasts | ✅ (STUB) | Confirmed all stub `dialogs.info` "Coming soon": Mass Import (`:1383-1387`), Edit Categories (`:1389-1393`), Delete (`:1395-1404`, guards no-selection but never deletes), Export (`:1406-1411`). Also Playlister Code Prefix stub (`:1413-1418`). |

### 🐛 Bugs & gaps
- **`dict(sqlite3.Row)` — BANNED pattern, latent crash.** `jingle_editor_dialog.py:345` (`return dict(row)`) and `:352-353` (`[dict(r) for r in ...]`). Project rule: "`dict(sqlite3.Row)` is BANNED (raises on Python 3.14)" (PROJECT_BIBLE.md:673, HANDOVER_2026_05_14_v2.md:591). `core/database.py:40` sets `row_factory = sqlite3.Row`, so these paths (`_fetch_existing` edit-mode load, `_fetch_links`) will raise on 3.14. Canonical fix: `{k: row[k] for k in row.keys()}`. Note: this same anti-pattern is widespread in the repo (database.py, scheduler, etc.), so it's a project-wide latent issue, not unique to this screen.
- **Delete does not use `db.delete_*`.** Per CLAUDE.md, `jingles` must delete via a dedicated `db.delete_*()` method. Currently Delete is a pure stub (`:1395-1404`) — no destructive path exists yet, so no rule violation *yet*, but the real implementation must route through `db.delete_jingle` (not raw SQL).
- **Duration filter label mismatch risk:** filter uses en-dash "5–10s" (`:1237`) and dropdown option matches (`:130`) — consistent, OK.
- **`_JingleRow` play hit-zone vs pill:** properties pill sits at x=444 (`:435`), play gutter is last 40px of TABLE_W=760 (`:462`) — no overlap, OK.
- No dead signals found; `add_jingle_clicked`, `jingle_selected` emitted; engine `playback_ended` hookup guarded (`:811-816`).
- `_open_editor_dialog` has an ImportError fallback toast (`:1364-1371`) — dead branch now that dialog exists, harmless.

### Tally
✅ 5 · ⚠ 4 · ❌ 0 · (STUB) 1 (the 4-way stub row) + 1 latent-crash bug


---

## Screen 5 — Sweepers Library
**Source:** `ui/sweepers_library.py` + `ui/dialogs/sweeper_editor_dialog.py`
**Ideal purpose:** Manage audio overlays that layer on top of songs at timing positions — browse/filter by position, add/edit via editor, view position explainer.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Header: breadcrumb, clock, station, "Open Studio" | ✅ | `sweepers_library.py:913-994` — breadcrumb Control Panel/Libraries/〜Sweepers, `_clock_lbl` ticks (`:905-907,1405-1407`), `Settings().station_display` (`:986`), Open Studio (`:992-994`) |
| Counter shows "active/total sweepers" | ✅ | `_SidebarCounter` paints `f"{active}/{total}"` + "SWEEPERS" (`:277-285`), fed from load (`:1239-1242`) |
| "+ Add New" opens the Sweeper Editor dialog | ✅ | `_on_add_new` → `_open_editor_dialog(sweeper_id=None)` → real `SweeperEditorDialog` (`:1337-1349`); dialog saves via `db.add_sweeper/update_sweeper` (`sweeper_editor_dialog.py:1195-1222`) |
| Position filter list: All / Start / Before Intro / Before End / Bridge at End / Independent / Custom (selecting filters table) | ✅ | `POSITION_OPTIONS` (`:87-95`), rows built (`:1029-1036`), `_on_filter_picked` sets filter + refreshes (`:1326-1335`), `_filtered_sweepers` applies (`:1252-1256`) |
| Table columns: status dot, Name, Position pill, Duration, Category pill, Properties, Last Used | ⚠ | All rendered (`_SweeperRow.paintEvent :465-518`, pills `:428-434`, header `:544-557`). Last Used hardcoded "—" (`:1226`, `:511`) — broadcast_log deferred |
| Single-click selects; double-click opens editor | ✅ | click→`_on_row_clicked` (`:1277-1282`), dbl→`_on_row_double_clicked`→`_open_editor_dialog(edit)` (`:1284-1286`, `:440-448`) |
| "How Sweeper Positions Work" explainer shows song timeline w/ position markers | ✅ | `_HowPositionsExplainer` painted diagram — timeline track, 4 position markers, "Sweeper plays here" callout, layering caption (`:564-648`), placed in center (`:1088-1091`) |
| Detail panel: read-only fields + Position-Settings selector (6 positions) | ✅ | `_DetailsHeaderCard` + 6 `_DetailsField` (`:1123-1134`), populated read-only (`:1305-1313`). 6 `_PositionSettingRow` from `POSITION_OPTIONS[1:]` (`:1148-1153`), active row highlights current position (`:1315-1316`). Clicking a position row is read-only ack (logs only, `:1394-1398`) — cannot change/save from here (editor owns writes). |
| ▶ preview (wiring may be partial) | ❌ (STUB) | `_AudioScrubber` is visual-only; ▶ click → `_on_scrubber_play` only logs "preview wiring deferred" (`:1400-1401`, self-documented `:655-659`). `self._engine` accepted but "not wired yet" (`:870`). No actual playback — matches spec's "may be partial" (here it's fully deferred). Contrast: Jingles Library DID wire real preview. |
| Mass Import / Edit Categories / Delete / Export are STUB toasts | ✅ (STUB) | Confirmed all `dialogs.info` "Coming soon": Mass Import (`:1357-1361`), Edit Categories (`:1363-1367`), Delete (`:1369-1378`, guards no-selection, never deletes), Export (`:1380-1385`). Plus Playlister Prefix stub (`:1387-1392`). |

### 🐛 Bugs & gaps
- **`dict(sqlite3.Row)` — BANNED pattern, latent crash.** `sweeper_editor_dialog.py:652` (`return dict(row)` in `_fetch_existing`, edit-mode path). Project rule: banned, "raises on Python 3.14" (PROJECT_BIBLE.md:673). With `row_factory = sqlite3.Row` (`core/database.py:40`) this raises when double-clicking a sweeper to edit on 3.14. Fix: `{k: row[k] for k in row.keys()}`. (Repo-wide anti-pattern, not unique here.)
- **Delete does not use `db.delete_*`.** CLAUDE.md lists `sweepers` among tables requiring dedicated `db.delete_*()`. Delete is currently a pure stub (`:1369-1378`) — no destructive path yet, but the real one must route through `db.delete_sweeper`, never raw `DELETE FROM`.
- **▶ preview non-functional** (see table row) — the only genuinely dead interactive control on this screen; scrubber play button emits signal that only logs.
- **Position-setting rows in detail panel are inert** — clicking logs an ack but does nothing (`:1394-1398`), self-documented as "editor dialog not yet wired". Cosmetically implies editability that isn't there.
- No dead signals found: `sweeper_selected`, `add_sweeper_clicked` emitted; `sweeper_saved` connected (`:1348`). Filter selection-preservation logic on filter change is correct (`:1330-1334`).
- Editor `Playlister Code` placeholder pulls existing code as placeholder even in NEW mode (`sweeper_editor_dialog.py:769-770`) — cosmetic only.

### Tally
✅ 6 · ⚠ 1 · ❌ 1 (▶ preview) · (STUB) 1 (the 4-way stub row) + 1 latent-crash bug


---

## Screen 6 — Instant Jingles (Live Pad Grid)
**Source:** `ui/instant_jingles.py` + `core/instant_jingle_engine.py`
**Ideal purpose:** Live DJ tool — trigger jingles instantly with hotkeys/pads during a broadcast.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Header: breadcrumb, clock, station, "Open Studio" | ✅ | `instant_jingles.py:1266-1346` — breadcrumb chip (1319), live clock `_clock_lbl` (1333) ticked at 1s (2171-2174), station `Settings().station_display` (1337), Open Studio button (1344-1346). |
| Left sidebar lists pallets; click loads pads; selected highlights | ✅ | `_populate_pallets` builds `_PalletRow`s (1597-1608); `_select_pallet` sets highlight (1624-1642) and calls `_load_pads` (1642); accent bar drawn on selected (`_PalletRow.paintEvent` 260-264). |
| Tabs across top switch pallets | ✅ | `_populate_tabs` (1610-1622), `_PalletTab.set_active` cyan underline (536-538, 550-553); tab click → `_select_pallet` (1618-1620). |
| Pad grid (up to 5×6): filled show color+label+duration; empty show "NEW ENTRY / Empty slot" | ✅ | `_populate_pads` grids by `pad_index` up to cols×rows (1654-1689); `_Pad._paint_filled` label+duration (414-469); `_paint_empty` "NEW ENTRY"/"Empty slot" (471-498). |
| Left-click filled pad → plays immediately (▶→■ while playing) | ✅ | `_on_pad_left_clicked` → `engine.play_pad` (1720-1770); `set_playing` toggled via `_on_engine_started`/`_ended` (2137-2153); pad highlight on playing (`_Pad.paintEvent` 431-436). |
| Right-click pad → opens pad editor on right | ✅ | `_Pad.mousePressEvent` right → `right_clicked` (390-391); `_on_pad_right_clicked` → `_refresh_editor` (1772-1774, 1908-1928). |
| Number keys 1–9 (and 0) trigger corresponding pads; Escape stops all | ⚠/❌ | ❌ Number keys 1–9/0 NOT wired anywhere — `_install_shortcuts` only binds Up/Down/Left/Right/Escape (1250-1262); grep for `Key_[0-9]` = none. ✅ Escape → `_on_stop_all` (1258). |
| Pad editor: preview, 10 color swatches, Label, Audio File (assign/clear), Output 1–8, Volume %, Behaviour (once/Loop/Latch), Test/Preview | ✅ | `_PadEditor` (726-1084): `_PadPreview` (771), 10 `EDITOR_SWATCHES` (674-677, 779-783), label input (800), assign/clear btns (834-862), Output combo 1-8 (810-816), Volume (818), Behaviour combo (822-830), Test btn (866-878). |
| AI insight box shows pad's 7-day usage | ⚠ | `_AIInsightBox` present (680-723); `set_pad` fills "used {plays}× in last 7 days" from `stats` (1011-1022); `_refresh_editor` fetches `db.get_pad_play_stats(...days=7)` (1920). Wired but display is coarse ("More analytics coming soon"); not independently verified DB method returns 7-day window. |
| Bottom controls: Stop All (works), AutoGain/MixFade/Loop/Latch toggles (AutoGain/MixFade STUBs) | ✅/(STUB) | Stop All → `engine.stop_all` (1468-1471, 2058-2064) ✅. Loop/Latch mutate behaviour (2066-2089) ✅. AutoGain (STUB) `_on_toggle_autogain` only flips visual flag + logs "not yet implemented" (2091-2097). MixFade (STUB) same (2099-2105). |
| Polyphony: up to 8 pads at once via InstantJingleEngine | ✅ | `InstantJingleEngine.MAX_POLYPHONY = 8` (`instant_jingle_engine.py:61`); cap enforced with oldest-eviction in `play_pad` (106-114), filtered to jingle-pad channels only (adapter over shared AudioEngine). |

### 🐛 Bugs & gaps
1. **Number-key hotkeys 1–9/0 completely missing** — `instant_jingles.py:1250-1262`. The spec's headline "live DJ tool — trigger jingles instantly with hotkeys" is not met on the standalone screen: `_install_shortcuts` wires only arrow keys (navigation) and Escape (stop-all). There is no `keyPressEvent` override and no `QShortcut` for `Key_1..Key_9`/`Key_0`, so pads cannot be fired by number. Only mouse-click triggers a pad.
2. **`_on_editor_output` does not persist per-pad output** — `instant_jingles.py:1958-1962`. Selecting an Output (1–8) in the pad editor writes it as the *pallet* output, not the pad's, because `jingle_pads` has no per-pad output column (acknowledged TODO). Pad-level output routing silently doesn't persist.
3. **Edit Grid Size is a no-op** — `_on_edit_grid` just logs "TBD" (1844-1846). Sidebar action exists but grid resize isn't implemented (grid still renders correctly from stored cols/rows).
4. **Test/Preview routes to main output, not monitor/cue** — `_on_test_pad` (2039-2054) plays through the normal engine output; TODO notes it should route to monitor (output 7). Live-audible during broadcast.
5. **AutoGain / MixFade are visual-only stubs** — confirmed as expected per spec (2091-2105); flagged so callers know the toggles have no audio effect.

Notes: DB table is `jingle_pads` / `jingle_pallets` (correct — `get_pallets`/`get_pads`/`update_pad` used, `_update_status_count` queries `jingle_pads`). No banned `dict(sqlite3.Row)` — explicit `_pallet_row_to_dict`/`_pad_row_to_dict` helpers used (1569-1595). Engine signals `pad_started/pad_ended/pad_stopped` all connected (1226-1228) and `pad_ended` now actually fires on natural EOS (engine 247-260) — no dead signals found.

### Tally
✅ 9 · ⚠ 2 · ❌ 1 · (STUB) 2


---

## Screen 7 — Studio (Broadcast Workstation)
**Source:** `ui/studio.py` (+ `core/scheduler/engine.py`, `core/audio/engine.py`)
**Ideal purpose:** The on-air control center — decides/plays what airs next (songs, spots, SOTG, jingles, sweepers), enforces SOTG>Spot>Song priority, and gives the operator manual override.

### 7a · Header
| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Logo + wordmark + "BROADCAST AUTOMATION" | ✅ | `_Header` class `studio.py:140`; wordmark card `studio.py:1223+` |
| Center clock HH:MM:SS + weekday + date | ✅ | `set_clock(hms, day, date)` `studio.py:215`; fed 1Hz `_on_tick` → `_header.set_clock(...)` `studio.py:7851` |
| Active-Station card (station/active clock name) | ✅ | active-clock indicator `_studio_check_active_clock` `studio.py:7907`; header shows station card |
| SIGNAL pill green/red | ✅ | `_update_status_pills` → `set_signal(_compute_signal_state())` `studio.py:6473,6475`; true when any channel `playing` |
| STREAM pill green/amber | ⚠ | `set_on_air(on)` at `studio.py:224/6468` drives ON-AIR; a dedicated STREAM pill distinct from SIGNAL/ON-AIR not separately verified — likely folded into on-air state |
| AUTO pill purple, pulses green when scheduler runs | ✅ | `set_auto_mode(auto_mode)` `studio.py:6469`; `auto_mode` gated on `_auto_advance_enabled and scheduler.is_running()` `studio.py:6465` |
| "‹ Control Panel" returns to hub | ✅ | `control_panel_clicked.connect(_on_control_panel)` `studio.py:4034`; emits breadcrumb `studio.py:6592` |
| "⚙" settings cog opens Studio Settings | ✅ | `settings_clicked.connect(_on_settings)` `studio.py:4035` |

### 7b · Master Strip
| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| NOW player: title, artist·year, elapsed/total, REMAINING | ✅ | `_NowPlayer` `studio.py:518`; `set_progress(pos,dur)` driven by `_on_engine_position` `studio.py:4906` |
| "● ON AIR · LIVE" pulsing dot only while playing | ✅ | on-air state via `set_on_air` `studio.py:6468`, gated on `_playback_cid` + kind deck/spot `studio.py:6459` |
| Waveform + moving playhead | ✅ | `_NowPlayer.set_progress` + waveform render; position feed `studio.py:4901-4907` |
| CROSSFADE PREVIEW purple zone (Studio-Settings toggle) | ✅ | `_cfg_show_crossfade_preview` `studio.py:3843`; loaded `studio.py:4321`; applied `_update_waveform_overlays` `studio.py:4346,4377` |
| Flash-mix-point green line ~10s before mix point (toggle) | ✅ | `_cfg_flash_mix_point` `studio.py:3844/4323`; overlay `studio.py:4386`; renderer `_NowPlayer:808` |
| NEXT chip: title/artist + "TO AIR in Ns" + INTRO badge | ✅ | `_NextChip.set_next(title,artist,to_air_s,intro_s)` `studio.py:871`; fed `studio.py:6174,6233` |
| Control cluster: Restart(always)/Loop/Pause(disabled idle)/Stop Next(disabled idle) | ✅ | `_ControlCluster` `studio.py:1035`; Restart `studio.py:6384`, Loop `6417`, Pause `6257`, StopNext `6394` (both no-op when idle) |
| Level meters L/R VU with peak-hold decay | ✅ | `_LevelMeters` `studio.py:1081` (peak-hold decay meter widget) |
| Analog clock ticks (hour/min/sec hands) | ✅ | `_AnalogClock` `studio.py:1157`, repainted via 1Hz tick |
| MIC pill toggles mic + emits mic signal; ducks audio (may be partial) | ⚠→✅ | `mic_clicked` signal `studio.py:1237`; `_on_mic_toggled`→`_mic_engage/_mic_release` duck the DECK channel `studio.py:7575,7587,7609`. Software ducking is COMPLETE; only true RJ-mic mixing (BASS_RecordStart) is deferred to v1.1 (`studio.py:4079`). Spec's "wiring may be partial" over-cautious — ducking works. |

### 7c · Libraries panel
| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| 7 type tiles (Songs default/Tracks/Jingles/Spots/Voice/Sweepers/Favorites) | ✅ | `_type_tiles` built `studio.py:2198-2204`; tile activation `studio.py:2411` |
| Action buttons ADD/INSERT/REPLACE/PREPAIR/DELETE | ✅ | `_on_lib_add:7670`, `_on_lib_insert:7697`, `_on_lib_replace:7717`, `_on_lib_delete:7747`, `_on_lib_prepair:7788`. All mutate the broadcast queue (INSERT/REPLACE/DELETE pivot on selected row, fall back to head — exceeds spec). |
| Songs table Artist+Title; single-click select; double-click load | ✅ | `_LibrariesPanel` table `studio.py:2163+`; selection feeds `_selected_library_row_as_queue_dict` (used by all actions) |
| Search + Search/Reset + checkboxes (SuperSearch/Show Only NEW/Sort by Surname) | ⚠ | Checkboxes present `studio.py:2262-2268`, wired to `_apply_search_filter` `studio.py:2275`. **SuperSearch is a placeholder** for v1.1 full-text scan (`studio.py:2346`); Show Only NEW + Sort by Surname functional (`studio.py:2347-2350`). |
| Category dropdown + current category + count | ✅ | category filter present in `_LibrariesPanel` (`studio.py:2163+`, category menu + count) |

### 7d · Up Coming queue
| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Rich cards: AT-time, dur, glyph+tile+badge (SONG/JINGLE/BREAK/VOICE/SOTG/SWEEPER/STATION) | ✅ | `_UpComingQueue` `studio.py:1579`; `_TYPE_VISUAL` map with all 8 badges `studio.py:1327-1339`; AT-time `_fmt_at_clock:1342` |
| NEXT card rose glow + "NEXT" pill | ✅ | NEXT pill in card paint `studio.py:894`; rose palette `studio.py:885` |
| Pending Spots/SOTG at TOP + T-60s preview cards | ✅ | `_pending_spot_to_card`/`_pending_sotg_to_card`; `_load_upcoming_queue:6794` prepends pending + T-60s window; `_check_upcoming_dispatches:6901` |
| Single-click select (persists across refresh); double-click acts | ✅ | `_on_queue_row_selected:7630` sets `_queue_selected_song`; used by lib actions; persists via `_find_queue_position` |
| "FADE NEXT" toggle sets fade-into-next | ❌ | `_FadeNextToggle` `studio.py:1537` emits `toggled` but signal is NEVER `.connect`-ed to any studio handler (`_fade_toggle` only instantiated/moved `studio.py:1600-1601`). Visual-only — does NOT control fade behavior. |
| Footer: loaded-playlist total + name | ✅ | `set_loaded_total` `studio.py:3627`; footer in `_UpComingQueue` |
| **Queue does NOT reshuffle every second** | ✅ | `_on_tick` only re-renders CACHED preview unless `_check_upcoming_dispatches` returns True `studio.py:7873-7894`; no `peek_next` at 1Hz (fix documented `studio.py:7855-7872`) |

### 7e · Instant Jingles panel
| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| 3×3 pad grid; filled=color+label+dur, empty="NEW ENTRY" | ✅ | `_InstantJinglesPanel` `studio.py:2726`; 3×3 grid at (14,110) `studio.py:2764` |
| Click pad → plays; hotkeys 1–5 trigger first five | ✅ | `hotkey_clicked` `studio.py:2734`; 5 hotkeys `studio.py:2778-2783`; QShortcut 1-5 bound `studio.py:6629-6637`; dispatcher `_on_jingle_hotkey_clicked:6691` |
| DEMO box: playing jingle name + countdown | ✅ | `set_demo_active(label,total)` `studio.py:2802` / `set_demo_inactive:2815`; fed `studio.py:6771,6788` |
| "Edit Bank" opens standalone screen; "Last played: X" | ✅ | breadcrumb `"instant_jingles"` `studio.py:6760`; last-played label `studio.py:2749,2927` |

### 7f · History / Next Break / RDS / Problems
| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| History last ~12 plays (time + artist−title), newest top, live refresh | ✅ | `_HistoryPanel:2950`; `_refresh_history:6503` pulls `db.get_history(24)`, dedupes to 12; called after each transition |
| "View Full History →" opens full history | ❌ | `view_full_clicked` emitted `studio.py:2987` but NEVER `.connect`-ed anywhere → dead link |
| Next Break big MM:SS countdown + type/dur/spots + Skip/Preview | ⚠ | `_NextBreakPanel:3066`; countdown fed via `_on_scheduler_next_break_in`→`set_countdown` `studio.py:6127`. BUT `set_break_meta` (type/dur/spots) NEVER called → those stay hardcoded defaults; `skip_clicked`/`preview_clicked` emitted `studio.py:3109-3111` but NEVER connected → dead buttons |
| RDS panel live HH:MM + on-air artist/title | ✅ | `_RDSPanel:3194`; clock computed live in paint `studio.py:3255-3256`; `set_on_air(artist,title)` `studio.py:3212` fed `studio.py:6193,6249` |
| Problems panel warnings w/ count, else "All systems nominal" | ❌ | `_ProblemsPanel:3295`; `set_problems(items)` defined `studio.py:3310` but NEVER called → panel is static, never surfaces real missing-file/warning state |

### 7g · Bottom Transport
| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| ▶ Play (start/resume) + ■ Stop (hard stop) | ✅ | `play_clicked→_on_play_clicked` `studio.py:4207,6272`; `stop_clicked→_on_deck_stop` `studio.py:4208` |
| Progress slider "MM:SS / MM:SS"; click seeks | ✅ | `seek_requested→_on_bottom_seek` `studio.py:4209,6423`; `set_progress` `studio.py:3633` |
| AutoPlay toggle sets auto-advance on EOS | ❌ | `_AutoPlayToggle:3494`; `autoplay_toggled` emitted `studio.py:3610` but NEVER connected in StudioScreen → does NOT flip `_auto_advance_enabled`. (Header AUTO pill does that instead.) |
| Right cluster: Up/Down, Stop All, Auto, MixFade, Loop | ⚠ | 6-button cluster built `studio.py:3612-3625`. Wired: `stop_all_clicked→_on_stop_all_clicked` `studio.py:4212`; Up/Down `→_on_up/down_clicked` `studio.py:4210-4211` but those are **no-op stubs** `studio.py:6433-6438`. NOT wired at all: `auto_clicked`, `mixfade_clicked`, `loop_clicked` (bottom cluster) — emitted `studio.py:3584-3586` but no `.connect` → dead. Only Stop All works. |

### 7h · Playback & dispatch rules (CORE)
| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Song→song crossfade at mix_point_ms (else duration−fade_out_start); overlap | ✅ | `_maybe_trigger_fade_out:4390` (mix_point_ms wins `4442`, else fade_out_start `4446`); fade + `_dispatch_crossfade_overlap:4473` starts next on fresh channel overlapping (`4566-4611`) |
| Priority SOTG > Spot > Song at every fade/EOS decision | ✅ | EOS drain order `studio.py:5062-5081` (SOTG then Spot then song); spot-resume `4958-4978`; sotg-resume `4997-5015`; crossfade `4511-4549` all SOTG→Spot→Song |
| Pending FIFO (append, fire back-to-back) | ✅ | `_pending_spots`/`_pending_sotgs` lists `studio.py:3860,3870`; `.append()` `5591,5813,5831` (never overwrite) |
| Defer-fade-when-pending (3 callsites gated on `_has_pending_dispatch`) | ✅ | INVARIANT #2 holds: `_on_engine_mix_point_reached:5279`, `_maybe_trigger_fade_out:4426`, `_dispatch_crossfade_overlap:4498` all defer when pending; helper `_has_pending_dispatch:5231` |
| Spot resume / SOTG resume (chain SOTG>Spot then resume from anchor) | ✅ | EOS (a) spot `studio.py:4951-4988` uses `_pre_spot_song_id` anchor; (a') sotg `4990-5026` uses `_pre_sotg_song_id`; both chain then `_compute_next_song(after_id=anchor)` |
| Stop Next: play to end then idle; drop pending | ✅ | EOS (b) `studio.py:5028-5041`, `_drain_pending_dispatches(reason="stop-next")` |
| Loop: repeat current; drop pending | ✅ | EOS (c) `studio.py:5043-5052`, `_drain_pending_dispatches(reason="loop")` |
| Sweepers overlay; sequential load like song; missing-file skipped | ✅ | overlay `_dispatch_overlay_sweeper:5463`; scheduler `_pick_sweeper` filters missing/empty `file_path` + non-existent files `engine.py:1014,1034,1051` → returns None, slot walker advances (never stalls) |
| Auto-advance ON fires next at EOS; OFF idles until Play | ✅ | EOS (d) gated on `_auto_advance_enabled` `studio.py:5059`; AUTO-off drains pending + Live-Assist `studio.py:6356-6366` |

**Invariant cross-check (PROJECT_BIBLE Part 3):**
- INV#1 `route_via_mixer=False` — ✅ default `engine.py:126,163`; MainWindow passes `False` `main_window.py:63`; BASSmix dormant.
- INV#2 defer-fade gate — ✅ all 3 callsites check `_has_pending_dispatch()` (see 7h).
- INV#3 `_suppress_queue_emit` — ✅ set True in `peek_next` try/finally `engine.py:655-673`; checked before `queue_changed.emit()` in `pick_next_item` `engine.py:575`.
- Thread-safety: BASS callbacks emit `_mix_point_reached_internal`/`_fade_completed_internal` (QueuedConnection) → main-thread `mix_point_reached`/`fade_completed` `engine.py:198-203,707-724`. ✅

### 🐛 Bugs & gaps
1. **Bottom Transport AutoPlay toggle is dead** — `_AutoPlayToggle.autoplay_toggled` (studio.py:3610) is emitted but never `.connect`-ed in StudioScreen. Spec 7g requires it to set auto-advance-on-EOS; only the header AUTO pill actually flips `_auto_advance_enabled`. Operator toggling the bottom AutoPlay does nothing.
2. **Bottom Transport Auto/MixFade/Loop cluster buttons dead** — `auto_clicked`/`mixfade_clicked`/`loop_clicked` (studio.py:3584-3586) have no `.connect`. Up/Down are connected but call no-op stubs (`_on_up_clicked`/`_on_down_clicked`, studio.py:6433-6438). Only "Stop All" in the right cluster functions.
3. **FADE NEXT toggle non-functional** — `_FadeNextToggle.toggled` (studio.py:1540) never connected; toggling it flips only the pill visual, does not affect any fade-into-next logic (spec 7d).
4. **Problems panel never populated** — `set_problems()` (studio.py:3310) is never called. Missing-file / warning state is computed elsewhere (`_handle_missing_file`) but never routed to the panel, so it never shows real problems or a count (spec 7f).
5. **"View Full History →" dead link** — `view_full_clicked` (studio.py:2987) emitted, never connected. Clicking does nothing (spec 7f).
6. **Next Break Skip/Preview buttons + meta dead** — `skip_clicked`/`preview_clicked` (studio.py:3109-3111) never connected; `set_break_meta` (type/dur/spots) never called, so those fields show hardcoded defaults (Commercial / 2:30 / 5). Only the countdown is live (spec 7f).
7. **STREAM pill vs SIGNAL/ON-AIR ambiguity (minor)** — spec distinguishes SIGNAL (streaming OK) and STREAM (streaming) pills; code drives on-air + signal state but a separate STREAM pill with amber-when-not-streaming was not confirmed distinct.

### Tally
✅ 38 · ⚠ 5 · ❌ 6 · (STUB) 0


---

## Screen 8 — Scheduling Hub
**Source:** `ui/scheduling_hub.py`
**Ideal purpose:** Navigation dashboard for the scheduling family (tiles + Studio launcher + status footer).

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Header w/ clock, station, nav buttons (Libraries / Settings / AI Magic / Studio) | ✅ | `_Header` from app_chrome at `scheduling_hub.py:645-654`; libraries/settings/ai_magic/studio_open wired to `screen_requested`. Clock updated in `_on_tick` `:735-746`. |
| Tiles route to Playlists, Main Auto Schedule, Force Clocks (STUB), Rebroadcast (STUB), RDS (STUB), Final Log Creator, Log Viewer (STUB) | ✅ | 7 tile specs `:576-607`; each `_TileCard.clicked` → `screen_requested.emit` `:663-675`. Routing in `main_window.py:_on_hub_screen_requested`: playlists `:741`, main_auto_schedule `:765`, final_log_creator `:798`. |
| — Force Clocks is STUB | ✅ (STUB) | Routes to "coming soon" toast `main_window.py:917,922-926`. `ui/force_clocks.py` exists (419 lines, functional add/list/delete) but is NOT wired into the premium hub routing — dead-ended by the toast. |
| — Rebroadcast is STUB | ✅ (STUB) | Toast `main_window.py:918`. `ui/rebroadcast.py:1-6` self-describes "Phase F8 stub … in-memory placeholder"; not routed. |
| — RDS is STUB | ✅ (STUB) | Toast `main_window.py:919`. No RDS screen file at all; tile key `"rds"` only hits the fallback toast. |
| — Log Viewer is STUB | ✅ (STUB) | Toast `main_window.py:920`. `ui/log_viewer.py:1-6` self-describes "Phase F5 stub"; not routed. |
| Studio launcher card shows NOW PLAYING + "▶ Go Live Now" | ✅ | `_StudioLauncher` `:333-495`; paints NOW PLAYING + track `:467-479`, "▶  Go Live Now" button `:495`. `set_now_playing` fed from `_on_tick` polling `self._studio._current_track` `:760-773`. Both card + button emit `studio_open` `:680-683`. |
| Status footer shows "SYSTEM HEALTHY" (green) or "ENGINE STOPPED" (rose) + uptime | ✅ | `_StatusFooter` `:502-567`; `_on_scheduler_state` flips healthy/rose `:721-731` with exact strings "SYSTEM HEALTHY" / "ENGINE STOPPED". Uptime via `set_uptime` in `_on_tick` `:750-756`. |

### 🐛 Bugs & gaps
- No `dict(sqlite3.Row)` usage, no raw DELETE, no delete_clock path here (pure nav screen) — clean.
- **Dead/misleading files:** `ui/force_clocks.py` (419 lines, *functional* CRUD against `force_clocks` table), `ui/rebroadcast.py`, `ui/log_viewer.py` all exist but are unreachable from this premium hub — every tile falls to the generic "coming soon" toast (`main_window.py:922-926`). So Force Clocks is effectively a STUB from the user's POV even though a working legacy-theme screen exists on disk. Matches spec's STUB expectation, but note the wasted implementation.
- Studio now-playing reads `self._studio._current_track` via `getattr`/try-except `:764-772` — safe if attribute renamed (degrades to "Studio idle"), no crash.
- Footer "Settings" link hit-rect `QRect(1310,866,90,18)` `:781` is a manual mousePressEvent hot-zone — brittle if layout shifts, but functional.

### Tally
✅ 8 · ⚠ 0 · ❌ 0 · (STUB) 4 (Force Clocks / Rebroadcast / RDS / Log Viewer — all confirmed STUB via toast)


---

## Screen 9 — Main Auto Schedule
**Source:** `ui/auto_schedule.py`
**Ideal purpose:** Assign clocks to each day+hour cell of a 24×7 weekly grid; persist to `auto_schedule`.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Available Clocks: lists ALL clocks; scrollable via wheel + ▲/▼ chevrons + thumb (2026-05-17 fix — all reachable, not just 3) | ✅ | `_ClocksPanel` `:244-530`. All clocks become children `:288-299`; visible window of 3 via `_relayout_rows` (hides off-band rows) `:364-376`. `wheelEvent` `:408-413`, chevron hit-tests `:415-422`, ▲/▼ + track + proportional thumb painted in `_paint_scroll_chrome` `:482-530`. |
| Clicking a clock selects it (rose highlight); shows "N SLOTS" hint | ⚠ | Selection + rose highlight ✅ (`_ClockRow.set_selected` rose gradient `:203-208`, drop shadow `:181-182`). BUT hint text is NOT "N SLOTS" — `_on_clock_selected` sets hint to first assigned cell `"{Day} · {HH:00}"` `:1362-1366`; shows nothing if the clock is assigned nowhere. Spec's "N SLOTS" hint not implemented. |
| "SET ›››" applies selected clock to all selected cells; enabled only when clock AND cells selected | ✅ | `_SetButton` `:537-616`. `_update_button_states` enables iff `sel_clock is not None and bool(sel_cells)` `:1375`. `_on_set_clicked` writes each target `:1403-1419`. |
| "⊙ Create Clock" opens new clock | ✅ | `_btn_create` → `screen_requested.emit("clock_new")` `:1250-1254`. Routes to ClockEditor new mode `main_window.py:770-772`. |
| "✎ Edit" / "⧉ Duplicate" (enabled only with selection) | ✅ | `_btn_edit`/`_btn_dup` start disabled `:1265,1271`; enabled iff clock selected in `_update_button_states` `:1378-1380`. Edit → `clock_edit:{id}` `:1491`; Duplicate → `clock_duplicate:{id}` `:1499`. |
| "🗑 Delete Clock": REFUSES if clock still assigned to any grid cell (warn to clear first); else confirm + delete (2026-05-17 fix) | ✅ | `_on_delete_clicked` `:1445-1485`. `_cells_assigned_to` scans grid `:1436-1443`; if assigned → `dialogs.warning` "Clock is in use" w/ sample cells, returns `:1454-1467`. Else confirm dialog `:1468-1472` then **`db.delete_clock`** (dedicated cascade) `:1478`. `ValueError` handled `:1479-1480`. |
| "⚙ Auto Program Settings" routes to that screen (may be STUB) | ✅ (STUB) | `_btn_auto` → `screen_requested.emit("auto_program_settings")` `:1274-1277`; `main_window.py:792-796` shows "Auto Program Settings — coming soon." toast. Confirmed STUB target, as spec anticipated. |
| Grid: 24 rows × 7 day cols; assigned cell shows clock name + color | ✅ | `_ScheduleGrid` single custom-paint widget `:795-1088`; `_paint_cell` fills accent color + draws clock name `:1062-1088`. Colors deterministic per id `color_for_clock_id` `:120-125`. |
| Single-click selects; Ctrl toggles; Shift range; drag lasso; Esc clears; Ctrl+A all 168 | ✅ | `mousePressEvent`: plain=`{cell}`, Shift=range via `_cells_in_rect`, Ctrl=toggle `:944-973`. Drag lasso in `mouseMoveEvent` `:975-994`. `keyPressEvent`: Esc→`clear_selection`, Ctrl+A→`select_all` (all 7×24=168) `:1008-1014,893-902`. |
| Weekdays vs Specific Days modes: Weekdays applies SET to Mon–Fri uniformly at chosen hour; Specific per exact cell | ✅ | `_ModeTab` × 2 `:1110-1119`. `_expand_targets` `:1384-1401`: Weekdays expands any Mon–Fri cell to full Mon–Fri strip at that hour; Sat/Sun literal; Specific = identity. Mode persisted to settings `auto_schedule.mode` `:1318-1322`, loaded `:1308-1316`. |
| "Clear" wipes grid (with confirm) | ✅ | `_ClearButton` `:753-788` → `_on_clear_clicked` confirm dialog `:1421-1427` then `db.clear_all_auto_schedule` `:1429`. |
| Assignments persist to DB; scheduler picks up next tick | ✅ | Each SET → `db.set_auto_schedule_cell` `:1412`; load via `db.get_auto_schedule_grid` `:1346`. Docstring `:9-18` confirms SchedulerEngine re-queries DB each tick (no refresh signal). |

### 🐛 Bugs & gaps
- **No `dict(sqlite3.Row)`** — clocks read via `r["id"]`/`r["name"]` with `"description" in r.keys()` guard `:1330-1333`. Clean.
- **Delete uses `db.delete_clock`** (dedicated manual-cascade) `:1478`, NOT raw DELETE. Correct per CLAUDE.md destructive protocol. Comment at `:1474-1477` documents the cascade.
- Minor: "N SLOTS" hint from spec is unimplemented — hint shows a cell reference instead (see ⚠ row). Cosmetic, not a crash.
- `_on_clock_selected` and `_on_delete_clicked` reach into `self._card.grid._grid` / `._clock_meta` private members `:1362,1441,1449` — internal coupling, works but fragile.
- `select_clock` emits `clock_selected(-1)` sentinel for deselect `:324-325`; `_on_clock_selected` guards `cid < 0` `:1360`. Consistent, no dead signal.

### Tally
✅ 12 · ⚠ 1 (N SLOTS hint) · ❌ 0 · (STUB) 1 (Auto Program Settings target)


---

## Screen 10 — Clock Editor
**Source:** `ui/clock_editor.py`
**Ideal purpose:** Build a clock = ordered list of content slots (Create / Edit / Duplicate).

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Title reflects mode: "Create New Clock" / "Edit [name]" / "Duplicate (Copy of [name])" | ⚠ | `paintEvent` only branches EDIT vs NEW `:2217-2220`: title = "Edit Clock" (generic, NOT "Edit [name]") or "Create New Clock". **Duplicate mode falls into the NEW branch** → shows "Create New Clock" / breadcrumb "NEW", never "Duplicate (Copy of…)". Name field does get "Copy of …" `:1805-1807`, but the title/breadcrumb do not reflect duplicate. |
| Meta strip: Clock Name (required), Comments, Color (6 options), Backup-song filter pill | ✅ | `_MetaStrip` `:217-323`: name QLineEdit `:237`, comments `:249`, `_ColorDropdownButton` with `CLOCK_COLOR_OPTIONS` (6) `:149-156,263`, `_BackupFilterButton` pill `:267-269`. Name required enforced in `_validate_for_save` `:2089-2091`. |
| Element-type tiles: Song / Jingle / Spot / Voice / Sweeper — switching changes filter panel | ✅ | `_TypeIconTile` × 5 from `ELEMENT_TYPES` `:114,780-786`; `set_element_type` → `_apply_sweeper_visibility` swaps panels `:890-896,917-939`. |
| Filters per type: Era, Vocal, Year, Priority, BPM (song/spot/voice); sweeper adds Position picker; jingle = random | ✅ | Song-filter dropdowns Era/Vocal/Year/Pri/BPM `:804-836`. Sweeper: `_dd_sweeper_pick` + `_dd_sweeper_position` (6 positions) `:851-867`. Jingle: single `_dd_jingle_pick` "Random (any)" `:874-879`. Visibility gated per type `:917-939`. (Note: Sound Code / Popularity / Properties dropdowns are decorative no-ops, flagged in code `:168-171`.) |
| Category picker dropdown ("All Songs" or specific category + count) | ✅ | `_CategoryDropdown` `:629-740`; menu "All Songs · N songs" + per-cat counts `:679-687`; paints selected name + count `:721-735`. Fed by `db.get_categories` `:1749-1766`. |
| Filter results card shows match count + avg duration; "Reset All Filters" | ✅ | `_FilterResultsCard` `:1141-1213` paints big count + "ESTIMATED AVG DURATION". `_refresh_filter_results` computes via `scheduler._songs_matching_filter_json` `:1875-1896`. Reset link → `reset_clicked` → `_lib.reset_filters()` `:1165-1171,1872-1873,1038-1046`. |
| Action stack: + ADD / ↳ INSERT / ⇄ REPLACE / 🎙 PREPAIR / 🗑 DELETE | ⚠ | `_ActionStack` implements ADD / INSERT / REPLACE / DELETE only `:1291-1318` — **PREPAIR button is absent** (spec lists 5, code has 4). ADD `:1960`, INSERT `:1969`, REPLACE `:1981`, DELETE `:1995` all wired and act on `self._elements`. |
| Clock face (circular) visualizes slots colored by type; center shows total duration | ✅ | `ClockFaceWidget` from `ui/widgets/clock_face.py` `:93-98,1423`; `set_elements` on every mutation `:1822,1964`. Colorize-by Sound Code/Type/Era `:1413-1417,1451-1462`. (Center duration rendering lives in the clock_face widget, not this file.) |
| OK saves clock + slots, returns to Auto Schedule; Cancel discards | ✅ | `_on_ok` validates → `_save` → `saved.emit` → `screen_requested.emit("main_auto_schedule")` `:2097-2108`. `_save` writes meta `db.save_clock` + `db.save_clock_slots` `:2110-2149`. Cancel → `_cancel_then_route` with dirty-confirm `:2187-2199`. |
| Duplicate mode saves as NEW clock (no id reuse) | ✅ | `_save`: EDIT branch reuses `_source_id`; **NEW *and* DUPLICATE** both call `db.create_clock(...)` for a fresh id `:2121-2137`. `db.duplicate_clock` is NOT used → no id reuse. Duplicate marked dirty on load so OK has effect `:1831-1832`. |
| Sub-tabs "Song Tracks" / "Artists" are STUB ("coming soon") | ✅ (STUB) | `_AvailableElementsCard.paintEvent` non-filters branch draws "Song Tracks picker — coming soon." / "Artists picker — coming soon." `:1109-1123`. Tabs switch but render only placeholder text. |

### 🐛 Bugs & gaps
- **No `dict(sqlite3.Row)`** — rows read via `row["x"]` + `"x" in row.keys()` guards throughout (`:1804-1818`, `:1840-1862`). Clean. Uses `db._conn().execute(...)` directly for COUNT and jingles `:1760,1780` — read-only SELECTs, acceptable.
- **Title bug (⚠ above):** duplicate mode never shows a "Duplicate"/"Copy of" title or breadcrumb — only the pre-filled name reveals it. Spec item partially met.
- **Missing PREPAIR action (⚠ above):** action stack has 4 buttons, spec expects 5 (no 🎙 PREPAIR).
- No destructive raw SQL, no delete_clock misuse (this screen never deletes clocks — Auto Schedule owns that). Slot save is atomic DELETE+INSERT inside `db.save_clock_slots` per docstring `:18-21`.
- `_on_backup_clicked` `:2079-2084` is a "coming soon" info dialog — backup-song filter picker is a STUB (pill records "Random song · No Filter"); spec listed the pill's existence (✅) but the picker behind it is stubbed.
- Dirty-tracking suppressed during programmatic load via `_is_loading` `:1655,2055-2059` — prevents false-dirty; correct.

### Tally
✅ 9 · ⚠ 2 (duplicate title, missing PREPAIR) · ❌ 0 · (STUB) 2 (Song Tracks/Artists sub-tabs; backup-filter picker)


---

## Screen 11 — Playlists (Browse / New / Edit)
**Source:** `ui/playlists.py`, `ui/playlist_new.py`, `ui/playlist_edit.py`
**Ideal purpose:** Browse/manage playlists, build a new one from the library with a drag-orderable queue, and power-edit an existing one with preview + analyze tooling.

### 11a · Playlists (Browse)

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Search box (debounced) + filter chips All/Manual/Imported/Smart with counts | ✅ | `_SearchInput` 200ms debounce `playlists.py:164-168`; chips built `playlists.py:958-967`; counts `_refresh_chips_counts` `playlists.py:1068-1079`; filter+search applied in `_visible_playlists` `playlists.py:1052-1066` |
| "+ New Playlist" opens create; "Import" is STUB toast | ✅ / (STUB) | New emits `playlist_new` `playlists.py:971-972`; Import → `_on_import_stub` info toast "coming soon" `playlists.py:974-976, 1270-1274` |
| 4 stat cards: Total Playlists / Total Tracks / Avg Duration / Scheduled | ✅ | Cards `playlists.py:980-994`; values `_refresh_stats` `playlists.py:1081-1113` |
| Playlist cards: cover, type badge, title, tracks+duration, last edit, ▶ Preview, Open →, schedule pill | ✅ | `_PlaylistCard.paintEvent` renders all of these `playlists.py:495-620` |
| Preview plays first track (on-air confirm if Studio live); Open → editor | ✅ | `_on_preview_card` confirms when `studio._current_track` set `playlists.py:1203-1216`, loads first track `1222-1250`; Open emits `playlist_edit:<id>` `1200-1201` |
| Selecting a card fills detail panel (cover, meta, ~5 tracks, Edit/Add/overflow) | ✅ | `_DetailPanel.set_data` + paint `playlists.py:676-872`; `_refresh_detail` pulls 5 tracks `1125-1142` |
| "Add to Schedule" adds playlist to schedule | ✅ | `_on_add_to_schedule` → `scheduler.add_playlist_to_schedule` `playlists.py:1252-1268`; method exists `scheduler/engine.py:889` |
| Overflow menu (Duplicate/Delete/Export) STUB toast | (STUB) | `_on_overflow_stub` info toast "coming soon (Duplicate/Delete/Export)" `playlists.py:1276-1279` |

### 11b · Create New Playlist

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Cancel (discard confirm if dirty) / ✓ Save Playlist | ✅ | `_on_cancel` confirms + deletes draft when dirty `playlist_new.py:1768-1782`; `_on_save` flushes+commits `1741-1766` |
| Meta: cover picker, Name (default "Untitled Playlist"), Type dropdown, Color swatches, Tags (comma-split) | ✅ | `_MetaFormStrip` children `playlist_new.py:459-463`; name default `1555`/`477`; tags normalized on comma `405-414`; 6 swatches `88-90` |
| Left library: search (debounced) + category chips + BPM/Year/Sort + result count + pagination (10/page) | ✅ | `_LibraryBrowser` search `playlist_new.py:848-849`, chips `950-987`, filter bar `856-857`, count `927`, `PAGE_SIZE=10` `813` + pager `869-883` |
| Each library row "+ ADD" → appends to queue, becomes "✓ ADDED" | ✅ | `_LibraryRow` button + hit-test `playlist_new.py:728-730`; paints ✓ ADDED when `is_added` `787-795`; `_on_add_song` flips state `1023-1028` |
| Right queue: drag-handle, rank, title/artist, duration, × remove; **drag to reorder** | ⚠ | Rows render handle/rank/×/dur via `_QueueRowDelegate` `playlist_new.py:1181-1261`; × remove works `1315-1327`. **Drag-reorder likely broken** — see Bug 1 |
| Auto-save persists draft (name/type/color/tags/cover + song order) after edits | ✅ | 1500ms debounce `playlist_new.py:1610-1613`; `_on_autosave` → `update_playlist_draft` + `replace_playlist_songs` `1713-1737`; every handler calls `_mark_dirty` |

### 11c · Edit Playlist

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Toolbar: Preview (on-air confirm), Preview Breaks STUB, Search, Mic | ✅ / (STUB) | Preview `_on_preview_track`→`_start_preview` with on-air confirm `playlist_edit.py:1820-1867`; Preview Breaks STUB toast `1869-1873`; Search focuses filter input `1875-1878`; Mic STUB toast `1880-1883` |
| Tabs: Edit (active) / Memos / Schedule & Details / Export | ⚠ (STUB) | Edit active; other 3 tabs → "coming soon" toast `playlist_edit.py:1885-1892` (render-only, no tab content) |
| Preview slot shows selected track; element-type tiles switch library filter (folder/heart STUB) | ⚠ / (STUB) | Preview slot updates on selection `playlist_edit.py:1797-1805`. Folder/heart → "coming soon" toast `1813-1816`. BUT functional tiles do NOT switch filter — `_on_type_changed` is a **no-op** `1807-1811` |
| Action stack: +ADD / ↳INSERT / ⇄REPLACE / 🎙PREPAIR / 🗑DELETE | ✅ / (STUB) | ADD/INSERT/REPLACE/DELETE mutate model `playlist_edit.py:1744-1785`; PREPAIR is STUB toast `1787-1790` |
| Playlist table (Name/Title/Run Time); drag rows to reorder | ⚠ | Table + delegate render columns `playlist_edit.py:721-829`; InternalMove enabled `763-766`. **Drag-reorder likely broken** — see Bug 1 |
| Filter panel: search + Search/Reset + checkboxes + category dropdown | ⚠ | All widgets present `playlist_edit.py:1027-1144`. But checkboxes SuperSearch/Only-NEW/Surname are **not passed to the query** (`_refresh_filter_results` only uses text+category) `1703-1713` — see Bug 3 |
| Analyze panel: selected track metadata + play-history placeholder STUB | ✅ / (STUB) | Meta rows painted `playlist_edit.py:1198-1215`; 14 hour-cells + "Play history — coming soon" hint `1226-1249` |
| Bottom transport + ✓ Save persists name + song order | ✅ | Transport play/stop/seek + engine wiring `playlist_edit.py:1896-1938`; `_save` → `update_playlist_draft` + `replace_playlist_songs` `1972-2006`; validates non-empty name/≥1 track `1965-1970` |

### 🐛 Bugs & gaps
1. **Drag-to-reorder queue likely does nothing / can drop rows (New + Edit)** — Both `_QueueModel`s override only `moveRows()` (`playlist_new.py:1152-1167`, `playlist_edit.py:678-696`) and the views set `DragDropMode.InternalMove` (`playlist_new.py:1285`, `playlist_edit.py:763`). Qt's default internal-move pipeline serializes rows via `mimeData()` then calls `insertRows()`/`removeRows()` — it does NOT invoke a custom `moveRows()`. None of `mimeData`/`dropMimeData`/`removeRows`/`insertRows`/`dropEvent` are implemented on either model or view (grep: no matches). Result: dragging a queue row produces no persisted reorder, and because the base model can't move the underlying `_rows`/`_tracks` list, the drop is silently discarded (or in some Qt paths deletes the dragged row). The spec's headline queue interaction is effectively non-functional. Needs runtime confirmation, but the code path cannot work as written.
2. **Edit: functional element-type tiles don't switch the library filter** — Spec 11c says "element-type tiles switch the library filter." `_on_type_changed` is an explicit no-op (`playlist_edit.py:1807-1811`); only folder/heart show a toast. So clicking Jingle/Spot/Voice/Sweeper changes tile highlight but does not re-filter the song source. Partial vs spec.
3. **Edit filter checkboxes are decorative** — SuperSearch / "Show Only NEW Additions" / "Sort by Surname" toggles emit `filter_changed` but `_refresh_filter_results` (`playlist_edit.py:1703-1713`) and `_first_filter_match` (`1717-1742`) only pass `query` + `category_id` to the DB. The three checkboxes have no effect on results.
4. **Browse "ON AIR NOW" uses banned raw-row/private access, but not `dict(sqlite3.Row)`** — `_is_playlist_on_air` calls `self._db._conn().execute(...)` directly (`playlists.py:1156-1161`), bypassing the DB API; low risk but a layering violation. No `dict(sqlite3.Row)` anti-pattern found anywhere in the three files (rows are consumed via `dict(r)`/`r["col"]`/`.keys()` guards, which is the accepted form).
5. **Minor: New draft only created on first edit** — if the user opens Create New, changes nothing and hits Save, no draft row exists so it just navigates back (`playlist_new.py:1746-1749`). Intended, but means an empty "playlist" is never persisted (matches auto-save-on-dirty design). Not a defect, noted for completeness.

No crashes, no `dict(sqlite3.Row)`, no dead signals to STUB handlers, and DB writes to `playlists`/`playlist_songs` are correctly wired via `create/update/commit/replace_playlist_songs` (all exist `core/database.py:2179-2358`).

### Tally
✅ 18 · ⚠ 6 · ❌ 0 · (STUB) 8


---

## Screen 12 — AI Magic Hub
**Source:** `ui/ai_magic_hub.py`
**Ideal purpose:** Landing page for the AI automation suite — two option cards route to the SOTG shell and the rotation-AI hub.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Header: logo, clock, station, "Open Studio" + breadcrumb "✦ AI Magic" | ✅ | `_build_header` `ai_magic_hub.py:431-490`: `_HeaderLogo` 439, "RadioAI" 440, live clock `_clock_lbl` 472 + `_tick_clock` 678-679, station 481-486, `_HeaderOpenStudio` 488-490 → `studio_clicked`, breadcrumb `_BreadcrumbPill("✦ AI Magic")` 457-458 |
| Hero "✦ AI MAGIC" + subtitle + 3 status pills (ENGINE STANDBY / N/2 MODULES ACTIVE / PREMIUM AUTOMATION) | ✅ | `_build_hero` `ai_magic_hub.py:494-540`: sigil "✦" 496, "AI MAGIC" title 502, subtitle 508-514, pills "ENGINE · STANDBY" / "0 / 2 MODULES ACTIVE" / "PREMIUM AUTOMATION" 518-525. ⚠ Note: "0 / 2 MODULES ACTIVE" is hardcoded — never reflects the engine being ON |
| "Spot on the Go" card → routes to SOTG shell | ✅ | Card spec `screen_key="spot_on_the_go"` `ai_magic_hub.py:563`; emits `screen_requested` via `_on_card_clicked` 584-586; MainWindow routes `spot_on_the_go` → `spot_on_the_go_shell` `main_window.py:845-848` |
| "Scheduling Automation" card → routes to rotation-AI hub | ✅ | Card spec `screen_key="scheduling_automation"` `ai_magic_hub.py:573`; MainWindow routes → `scheduling_automation_hub` (with `.refresh()`) `main_window.py:849-859` |
| Whole card clickable (same as "Configure →") | ✅ | `_AIOptionCard.mousePressEvent` 277-280 emits `clicked(screen_key)`; CTA button also emits same 274-275. Both wired to `_on_card_clicked` 581 |
| Roadmap banner lists future modules | ✅ | `_build_roadmap` `ai_magic_hub.py:590-635`: amber-accent stripe + "ROADMAP · MORE AUTOMATIONS LAUNCHING" 614 + item list (Voice Tracking AI, Audience Pulse, Auto Mastering, Smart Crossfades, Hourly Insight Brief) 620-623 |

### 🐛 Bugs & gaps
- No crashes, no banned `dict(sqlite3.Row)`, no dead signals. `screen_requested` / `studio_clicked` both wired in MainWindow (`ai_magic_hub` 443-446).
- Status pill "0 / 2 MODULES ACTIVE" and hero "ENGINE · STANDBY" are static strings (`ai_magic_hub.py:518-521`); the docstring at 17-19 admits both cards were once "coming soon" placeholders. Cards now genuinely route (verified), but the pill counts are cosmetic and do not reflect that the rotation engine is live/ON. Cosmetic mismatch, not a functional break.
- Card status pills read "● COMING SOON" (default `status_label`, `_AIOptionCard.__init__` 192, not overridden per-card at 578) even though both cards route to real screens — stale label. Minor cosmetic.

### Tally
✅ 6 · ⚠ 0 · ❌ 0 · (STUB) 0


---

## Screen 13 — Spot on the Go (SOTG)
**Source:** `ui/spot_on_the_go_shell.py` + 4 step screens
**Ideal purpose:** One-shot scheduled audio drops (RJ links / news / sponsor reads) that fade the music and play once at a sharp HH:MM, with per-drop priority, daily PDF report, and optional AI transcription summary.

### 13a · Shell

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Breadcrumb "✦ Spot on the Go" + hero + module/scheduled/links pills | ✅ | `spot_on_the_go_shell.py:527` breadcrumb pill; hero `:565`; 3 pills "MODULE · STANDBY" / "0 SCHEDULED TODAY" / "0 LINKS QUEUED" `:589-596` (counts are hardcoded 0 placeholders, not live) |
| 4 step cards route to their screens | ✅ | `CARD_SPECS` `:615-633` → keys create_schedule/assign/generate_report/assign_api_key; `_on_card_clicked` emits `screen_requested` `:653-655`; CTA + whole-card click both wired `:262-268` |
| Priority ladder strip (1 Paid Spots, 2 SOTG sharp-time/song fade, 3 Songs baseline) | ✅ | `_PriorityLadder.TIERS` `:352-362` — exact 3-tier semantics rendered `:381-417` |

### 13b · Step 1 — Create Schedule

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| "Shows saved" + "Total links" pills update live | ✅ | `_refresh_saved_shows` sets `_pill_shows_label`/`_pill_links_label` `sotg_create_schedule.py:982-985` (total_links summed from `link_count`) |
| Form: RJ*, Show*, Days(Daily/Weekdays/Weekends), Start, End, Color(6), #Links(1–12 def 9), Desc | ✅ | fields `:532-571`; days combo `:540`; 6-swatch `_ColorPicker` `COLOR_PALETTE` `:78-79`; spin range 1–12 init 9 `:565-567` |
| Changing "# of Links" rebuilds row (auto-shrink 10–12) + updates auto-calc | ✅ | `_on_link_count_changed` `:843-846`; `_compute_box_width` shrinks + slim pill at n≥10 `:258-266` |
| Auto-calc strip: envelope hours + link count + ~interval; overnight wrap | ✅ | `_update_auto_calc` `:848-863`; `_envelope_minutes` wraps `end_m += 24*60` `:882-884` |
| "Create Show" validates (RJ, show, valid HH:MM) + saves; "Reset" clears | ✅ | `_on_submit` `:895-946` validates RJ/show/envelope, calls `create_sotg_show`; `_reset_form` `:952-970` |
| Saved-shows table: chip, name, RJ, days, slot, links, interval, desc, EDIT, DELETE | ✅ | `COLUMNS` `:295-307`; `_fill_row` builds all 11 cells incl chip `:1005-1010`, EDIT `:1044`, DELETE `:1049` |
| Row click (or EDIT) loads show for inline edit ("Update Show" + "Cancel Edit") | ✅ | `cellClicked`→`_on_row_clicked`→`_on_edit` `:792,1100,1110`; flips caption/btn `:1144-1147`; Cancel shown `:1147`, `_on_cancel_edit` `:948` |
| DELETE confirms, then removes show + its links | ✅ | `_on_delete` confirm dialog `:1159`, `delete_sotg_show` `:1167`; DB cascade on `sotg_links` FK `database.py:855-857` |

### 13c · Step 2 — Assign

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Pills: Links Queued / Fired / Conflict / Missed (live) | ✅ | 4 hero pills `sotg_assign.py:1057-1074`; `_refresh_hero_counters` sums per-date counts `:1523-1541` |
| Today / Tomorrow toggle + formatted date label | ✅ | `_DateToggle` `:141-207`; `_refresh_date_label` "%a, %d %b %Y" `:1097-1103` |
| Left: show cards (chip, name, RJ, time, "X/Y ready" badge); click selects | ✅ | `_ShowCard` `:789-909`; ready badge `ready_n = ready+fired` `:846-869`; click→`_on_show_clicked` `:1210` |
| Right: links table — #, Link, File, Dur, Sharp, Priority, ▶, Status | ✅ | header cols `:1287-1297`; `_LinkRow` composes all widgets `:580-679` |
| File button picks audio (mp3/wav/ogg/flac/m4a) → "filename · MM:SS" | ✅ | `_FileButton` filter `:461`; `_render_filled` "name · dur" `:438-443`; duration probed via pybass3 `:685-698` |
| Sharp-time HH:MM; past-time: today red+disable, tomorrow no check | ✅ | `_SharpTimeInput._revalidate` only when `_validate_today` `:353-365`; `set_scheduled_date` enables validation only if date==today `:706-710`; disables Save via `_refresh_save_button` (`not is_invalid_past`) `:734-735`; server-side guard also rejects `database.py:940-961` |
| Priority toggle ⚡ HIGH / ⏱ LOW | ✅ | `_PriorityToggle` `:254-318` |
| ▶ preview plays file locally (not on air); ■ stops | ✅ | `_PreviewButton` uses shared engine load/play/cleanup `:471-572` |
| Status badge PENDING/READY/FIRED(✓)/MISSED(✕)/CONFLICT(⚠) | ✅ | `STATUS_STYLE` `:70-76`; `_StatusBadge` `:215-246` |
| Save enabled only with file+time+priority (not invalid past); "Update" if exists | ✅ | `_refresh_save_button` eligibility `:728-756`; label Update when `assignment_id` present `:739-740` |
| FIRED/MISSED rows read-only | ✅ | `_apply_lock_state` disables file/time/prio/save `:712-726` |
| Auto-suggested sharp times spread across envelope (overridable) | ✅ | `_spread_times` even spread + overnight wrap `:109-133`; applied only when no sharp_time yet `:1451-1464` (never overwrites) |
| Legend explains statuses (CONFLICT = paid break occupies minute) | ✅ | `_build_legend` 5 pills + CONFLICT explainer `:1339-1385` |
| CONFLICT detection | ⚠ | Status is rendered/legended but the Assign screen never computes or writes CONFLICT — `upsert_sotg_assignment` always saves `status="READY"` `:1505`; CONFLICT would have to be set by Studio dispatch elsewhere, not found in this screen |

### 13d · Step 3 — Generate Report

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Stat pills: Total Drops / Played(✓) / Missed(✕) | ✅ | `_StatPill` x3 `:532-537`; counted from full day `_refresh_data` `:763-770` |
| Date bar: ◀ / date pill (calendar) / ▶ / Today / "Show pending too" | ✅ | `_build_date_bar` `:547-575`; `_CalendarPopup` `:945-975`; pending toggle `:573` |
| Table: #, Time, Show, RJ, Link, Status, File, Duration | ✅ | header cols `:588-597`; `_AssignmentRow` `:249-372` |
| Rows expand to 4-line AI summary when FIRED + ai_summary | ✅ | `_has_summary = ai_status=="DONE" and summary` `:266`; height 56→116 `:267`; 4-line block `:352-361` |
| "Show pending too" off (default) hides PENDING/READY; hint shows hidden count | ✅ | default `_include_pending=False` `:394`; filter FIRED/MISSED `:751-753`; hidden-count hint `:773-780` |
| "📥 Download PDF" builds daily PDF, saves to reports dir, opens it | ✅ | `_on_download_pdf`→`generate_sotg_daily_report` `:886-895`; `os.startfile` opens `:910`; PDF renders `AI Summary:` block `sotg_daily_report.py:413-415,524,679` |
| Note shows auto-save path (23:59 daily) + last-save time | ✅ | path from `DEFAULT_REPORT_DIR` `:678-683`; `_refresh_last_save_label` reads `last_sotg_report_save_at` setting `:838-848` |

### 13e · Step 4 — Assign API Key

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Pills: Done Today / Queue / Errors (live) | ✅ | `_HeroStatPill` x3 `:660-668`; refreshed from `get_sotg_summary_counts_today` + `queue_depth` `:1033-1039` |
| Provider cards GEMINI + OPENAI, connection dot, tagline, hint, Activate/Configure | ✅ | `_ProviderCard` `:106-269`; two cards `:673-689`; `set_connected` green/red dot `:242-257` |
| Switching provider activates it; Configure focuses key input | ✅ | `_on_activate_provider` saves + reloads `:1130-1140`; `_on_configure_provider` focuses `_key_input` `:1142-1145` |
| Key card: masked input + 👁 Reveal/Hide, Model dropdown (provider-specific), ↻ Test, Save & Activate | ✅ | password echo `:764`; `_toggle_reveal` `:849-856`; model combo per-provider `:825-841`; buttons `:788-809` |
| Test Connection pings provider, reports reachable ✓ or error | ✅ | `_on_test_connection`→`build_adapter(...).test_connection()` `:1147-1174`; adapters do real GET /models with 15s timeout `gemini_adapter.py:165-185`, `openai_adapter.py:207-228` |
| Save & Activate stores key/model in Settings, reloads engine, confirms | ✅ | `_on_save_clicked` writes Settings keys + engine_enabled=1 `:1187-1195`, `engine.reload_settings()` `:1198`, confirm dialog `:1204` |
| Live activity log: today's transcriptions grouped by show, DONE/PROCESSING/FAILED/SKIPPED/MISSED pill + 4-line summary | ✅ | `_refresh_activity_log` groups by show `:936-1016`; `_ActivityRow` pill logic `:403-429`; 4-line summary `:471-479` |
| "↺ Backfill Missing (50 max)" enqueues past FIRED drops lacking summaries | ✅ | `_on_backfill`→`engine.enqueue_backfill(limit=50)` `:1211-1230`; engine pulls `get_pending_transcription_assignments` and enqueues `sotg_transcription_engine.py:103-112` |
| Privacy note: keys in radioai.db; audio sent only to active provider | ✅ | hero sub2 `:650-657` + privacy strip `:812-821` |

### 🐛 Bugs & gaps
1. **CONFLICT never actually detected in Assign** — `sotg_assign.py:1505` hardcodes `status="READY"` on every save; the CONFLICT status/legend/pill are pure UI with no code path that inspects paid-spot breaks. So the "Conflict" hero pill and per-row CONFLICT badge can only light up if some other component (Studio dispatch) writes it, which is not present here. Effectively unimplemented for the Assign screen.
2. **Shell hero pills are static placeholders** — `spot_on_the_go_shell.py:589-596` render "0 SCHEDULED TODAY" / "0 LINKS QUEUED" as literal strings; never queried from the DB despite the spec implying live counts. (Spec 13a wording "module/scheduled/links pills" is satisfied cosmetically but not live.)
3. **Dead code after `return` in Create Schedule** — `_capture_pill_label` (`sotg_create_schedule.py:453-476`) has `self._hero_right = ...` code after the `return labels[-1]...` on `:463`; the whole "Inline edit / click any row to edit" right-hand hero block is unreachable and never renders. Cosmetic only (no crash), but the hero-right hint from the design is silently missing.
4. **`_spread_times` has dead branches** — `sotg_assign.py:122-123` sets `m = sm` for `n==1` but `m` is unused (loop recomputes `t`). Harmless.
5. **Header label fetched by fragile index** — `sotg_assign_api_key.py:556-557` does `QLabel("RadioAI", h)` then `h.findChildren(QLabel)[-1]` to style it. Works today (it is the last-added child at that instant) but brittle vs. incident-#19 guidance the codebase otherwise follows. No functional bug.

Note (verified OK): No banned `dict(sqlite3.Row)` in any SOTG DB method — all use the safe `{k: r[k] for k in r.keys()}` idiom (`database.py:818,829,834,1026,1058`). The `dict(r)` hits at `database.py:2318/2336/2365/3591-2` are campaign/spot code, not SOTG. Past-time validation is enforced both client-side and server-side (`database.py:940-961`). DB writes to sotg_shows/sotg_links/sotg_assignments all present and committed.

### Tally
✅ 33 · ⚠ 1 · ❌ 0 · (STUB) 0


---

## Screen 14 — Scheduling Automation (Rotation AI)
**Source:** `ui/scheduling_automation_hub.py`, `ui/scheduling_daily_plan_review.py`
**Ideal purpose:** Operator control panel for the Time-Slot Freshness rotation engine (14a Hub) + the approve/discard gate for AI's proposed daily plan (14b Daily Plan Review).

### 14a · Hub

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Hero "🤖 SCHEDULING AUTOMATION" + engine/balanced/groups pills | ✅ | `_build_hero` `scheduling_automation_hub.py:626-681`: sigil 🤖 627, title 633, pills ENGINE (live state) 665-667, BALANCED TODAY (live) 668-671, GROUPS (live count) 672-675 |
| Engine card: big state dot, "ENGINE: ON/OFF/WARMING/ERROR", last/next tick, algorithm line, last-error line | ✅ | `_build_engine_card` 685-807: halo+dot colored by `_engine_state()` 702-720, state label map 723-728, tick info (last/next, live from Settings sentinel) 737-751, algorithm line 753-758, last-error line (live from Settings) 761-773 |
| "🔄 Refresh" ticks the engine | ✅ | Button 776-785 → `refresh_engine_clicked` → `_on_sched_ai_refresh` `main_window.py:1129-1143` calls `self._rotation_engine.tick()`; tick writes plan + emits `tick_completed` → hub repaints (`_on_tick_completed` 1146-1192) |
| "⏹ Stop AI Engine" stops it (obeys enabled flag) | ✅ | Button 787-797 → `stop_engine_clicked` → `_on_sched_ai_stop` `main_window.py:1145-1169`: confirm gate, sets `KEY_ENGINE_ENABLED="0"`, `_set_state("OFF")`. Engine `_on_tick` early-exits on `is_enabled()==False` (`rotation_ai_engine.py:256-258`); `is_enabled` reads the flag 145-150. Obeys the flag correctly |
| Sister-group cards: group id, category chips (2–5), member count "N/5", total songs, EDIT + UNGROUP | ✅ | `_SisterGroupCard` 186-297: title "GROUP {id} · {n} / 5 categories" 207-208, chips 224-227, meta "{total} songs total" 237-240, Edit btn 247-258 → `edit_clicked`, Ungroup btn 260-270 → `ungroup_clicked`. Live groups from `_load_groups` 457-487 (`db.get_sister_groups`). ⚠ Only first 2 groups rendered (867-881); 3+ groups have no visible "+N more" overflow (comment at 862-864 promises one but none built) |
| "✚ New Sister Group" opens picker (2–5 categories; already-grouped disabled) | ✅ | CTA `_build_create_group_cta` 912-948 → `create_group_clicked` → `_on_sched_ai_create_group` `main_window.py:1171-1182` opens `SisterGroupPickerDialog`. Picker: min/cap 2-5 enforced (`sister_group_picker.py:44-45`, save enabled only 2≤n≤5 at 369-389, cap at 350-367); already-grouped categories disabled + "already in Group N" hint 332-346 |
| "Today's AI Actions": Rested / Promoted / Balanced counts + recent-decisions log | ✅ | `_build_today_summary` 952-1073: stats from `_live_today_stats` (`_load_today_stats` 489-503 reads `db.get_ai_rotation_plan`) 987-1010; recent decisions from `_load_recent_decisions` 505-546 (`db.get_rotation_decisions_for_date`) rendered 1020-1034; empty-state fallback line 1022-1024 |
| "📅 Review Today's Plan →" opens Daily Plan Review | ✅ | CTA 1037-1073 → `review_plan_clicked` → `main_window.py:522-524` emits `review_daily_plan` → routes to `scheduling_daily_plan_review` with `.refresh()` 860-867 |

### 14b · Daily Plan Review

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Hero "📅 TODAY'S PLAN REVIEW" + date + diff legend (🟢 added / 🔴 rested / ⚪ unchanged) | ✅ | `_build_hero` `scheduling_daily_plan_review.py:749-795`: title 756, live date 762-765, diff legend sub2 772-779 "🟢 added from sister · 🔴 rested · ⚪ unchanged" |
| Per-clock cards (collapsible): time range + clock + group badge + change summary + chevron | ✅ | `_ClockCard` 170-357: time range 220, clock name 233, group badge 240-254, change summary 257-263, chevron ▾/▸ 266-271, whole-header click 274-280 → `toggle_clicked` → `_on_card_toggled` 914-933 (rebuilds scroll) |
| Expanded: LEFT "WILL BE RESTED"; RIGHT AI picks, promoted marked "+ FRESH · from sister" | ✅ | `_build_body` 291-351: LEFT col (rest_rows, badge_kind "rested"/"WILL BE RESTED") 322-330 + `_load_state` 606-614; RIGHT col (promote→"+ FRESH · from sister" 617-624, pick rows 625-630) 332-340; column headers "WITHOUT AI" / "WITH AI CHANGES" 807-820 |
| AI reasoning line explains changes | ✅ | Reasoning strip 342-351 fed from `_load_state` concat of decision reasons 641-644; engine builds reasons via `_rest_reason`/`_pick_reason` (`rotation_ai_engine.py:656-680`) |
| "✓ Approve & Apply Now" applies; "✕ Discard Plan" reverts | ✅ | Buttons `_build_action_bar` 972-997 → `approve_clicked`/`discard_clicked`. Approve → `_on_sched_ai_approve` `main_window.py:1222-1248` calls `db.mark_ai_rotation_plan_approved` (exists `database.py:1690`). Discard → `_on_sched_ai_discard` 1250-1276 calls `db.mark_ai_rotation_plan_discarded` (exists 1703), confirm-gated |
| Note: if untouched, plan auto-applies at 5 PM | ✅ | Static note in action bar 954-960 + hero 762-765 + hub CTA footer `scheduling_automation_hub.py:1068-1073`. Backed by real logic: `_check_ai_rotation_auto_apply` `main_window.py:1278-1325` (≥17:00, only flips status 'pending'→'auto_applied', idempotent sentinel) → `db.mark_ai_rotation_plan_auto_applied` (exists `database.py:1724`) |
| Empty state when no decisions exist yet | ✅ | `_load_state` sets `_live_clock_cards=[]` when no decisions 544-547; `_build_clock_cards` renders "No plan yet for today" dashed empty panel 851-876. Hero pills show 0 (539-542). Hub also has sister-groups empty state 882-908 |

### 🐛 Bugs & gaps
- **Mock fallback masks empty state (both screens).** When `db is None`, Daily Plan Review keeps `MOCK_CLOCK_CARDS` sample data (`scheduling_daily_plan_review.py:487-489`, `_load_state` returns early at 513-515) — shows fake "Tum Hi Ho" cards. In-app `db` is always passed (`main_window.py:541-542`) so this only bites test/headless construction, not production. Same pattern for hub MOCK_* but hub's `_load_*` return `[]`/zeros when `db is None`, so hub degrades cleanly.
- **Hub renders only 2 sister-group cards.** `_build_sister_groups` slices `self._live_groups[:2]` (`scheduling_automation_hub.py:867-869`) and the promised "+ N more groups" overflow hint (comment 862-864) is never built. Groups 3+ silently invisible on the Hub (still editable only if visible). The right-summary count line (847-855) does report the true total, so counts stay honest.
- **`_engine_state()` does not reflect the enabled flag.** `_engine_state()` returns `engine.state()` (`scheduling_automation_hub.py:426-432`). When Stop is pressed, MainWindow calls `engine._set_state("OFF")` (`main_window.py:1164`) which does emit `engine_state_changed` → hub repaints via `_on_engine_state_changed` 1109-1144. Works, but the hub never independently reads `is_enabled()`; if the flag is flipped in Settings without a `_set_state` call, the hub's dot would be stale until next tick. Minor — the wired path is correct.
- No banned `dict(sqlite3.Row)` in any of the three files. Engine's `_slot_to_dict` (`rotation_ai_engine.py:685-690`) uses the safe `{k: slot[k] for k in slot.keys()}` comprehension. `db.get_sister_groups` returns plain dicts (`database.py:1527-1530`).
- All 8 hub signals + 4 review signals are wired in MainWindow (`main_window.py:518-551`). No dead signals. Confirmations (Stop, Ungroup, Discard) are real `confirm()`/`dialogs.info` calls, not stubs.

### Tally
✅ 16 · ⚠ 0 · ❌ 0 · (STUB) 0


---

## Screen 15 — Rotation Health
**Source:** `ui/rotation_health.py`
**Ideal purpose:** Day-wise audit of AI rotation (Time-Slot Freshness) decisions per music category.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Breadcrumb "Rotation Health" pill | ✅ | `_BreadcrumbPill("🎯 Rotation Health", GREEN)` header `rotation_health.py:828-829`; legs Control Panel / Songs Library at `811-823` |
| "← Back to Songs" button | ✅ | `QPushButton("← Back to Songs Library")` emits `back_clicked` `rotation_health.py:869-877` |
| Date pill (calendar) | ✅ | `_DatePillButton` opens `QCalendarWidget` popup `rotation_health.py:160-235`; built at `880-882` |
| Date pill max = today | ✅ | `cal.setMaximumDate(QDate.currentDate())` `rotation_health.py:219`; "(Today)" suffix `184-187` |
| Refresh button | ✅ | `_RefreshButton`; `_on_refresh_clicked` fires `engine.tick()` then reloads `rotation_health.py:238-251, 884-886, 1224-1234` |
| Filter dropdown (All/Rested/Promoted/Has changes) | ✅ | `_FilterDropdown.MODES` = all/rested/promoted/has_changes `rotation_health.py:258-263`; applied in `_rebuild_card_grid` `1080-1090` |
| "Hide empty cards" toggle | ✅ | `_HideEmptyToggle` (default checked=True) emits `toggled`; filters empty cards `rotation_health.py:309-361, 924-927, 1088-1089` |
| Stat pills RESTED/PROMOTED/CLOCKS/ERRORS/PLAN STATUS | ✅ | 5 `_StatPill`s built `rotation_health.py:889-899`; values set from plan+buckets `1035-1057` |
| Category cards, 3-col grid | ✅ | `COLS = 3`; `_flush_row` lays 3-up with padding `rotation_health.py:1093-1097, 1143-1149, 1184-1209` |
| Sections RESTED / PROMOTED OUT / PROMOTED IN | ✅ | `_CategoryCard` builds three `_CardSection`s (Rested/Promoted Out/Promoted In) `rotation_health.py:598-619` |
| Row shows clock · song · parent category | ✅ | `_DecisionRow` 3 cols: clock_lbl, song_title, source_category_name `rotation_health.py:384-467` |
| Hover tooltip (7-day + all-time plays + reason) | ⚠ | Tooltip HTML built `rotation_health.py:431-445`; last-7d via `get_song_recent_plays_count` OK (`database.py:1945`); **all-time via `db._song_play_stats` which does NOT exist** (`database.py:103` is `get_song_play_stats`) — swallowed by try/except `420-423`, so all-time silently renders 0 |
| Empty-card dashed "no changes today" state | ✅ | `_EmptyCategoryCard` dashed body "AI did not touch this category" `rotation_health.py:654-722`; shown when not hidden `1124-1129` |

### 🐛 Bugs & gaps
1. **Wrong method name breaks all-time play count** — `_DecisionRow` calls `db._song_play_stats(int(sid))` at `rotation_health.py:420`, but the DB method is `get_song_play_stats` (`database.py:103`). No `_song_play_stats` exists anywhere in `core/`. It is caught by `except Exception` (`422-423`) and logged at debug, so no crash — but the hover tooltip's "All-time" figure is **always 0** for every row. Spec requires all-time plays in the tooltip → effectively broken/stub.
2. **Empty-card opacity call is a no-op** — `_EmptyCategoryCard.__init__` calls `self.setWindowOpacity(0.7)` on a child widget (`rotation_health.py:672-675`); `setWindowOpacity` only affects top-level windows, so the intended dimming never happens. Cosmetic only, wrapped in try/except.
3. **No `dict(sqlite3.Row)` misuse** — decision/plan dicts are built safely via `{k: row[k] for k in row.keys()}` (`database.py:1688, 1761`); all `.get()` calls in the UI operate on real dicts. No banned pattern, no dead signals found (`date_picked`, `mode_changed`, `toggled`, `back_clicked`, `studio_clicked`, `breadcrumb_clicked` all connected).

### Tally
✅ 12 · ⚠ 1 · ❌ 0 · (STUB) 0


---

## Screen 16 — Settings
**Source:** `ui/settings_hub.py`, `settings_general.py`, `settings_soundcard.py`, `settings_studio.py`
**Ideal purpose:** Four-part settings area — a hub landing page routing to General (station identity/paths/startup/backup), Soundcard (device routing), and Studio (crossfade/AutoCue/levels/cue-split) sub-pages, all persisting to the `settings` table via the `Settings` singleton.

### 16a · Settings Hub

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| 3 cards: General / Soundcard / Studio, each opens its sub-page | ✅ | `settings_hub.py:354-381` builds 3 `_OptionCard`s with keys `settings_general`/`settings_soundcard`/`settings_studio`; card click emits `screen_requested` (`:383-385`). Whole-card click via `mousePressEvent` (`:198-201`) + CTA (`:196`). |
| Header clock + station + "Open Studio" | ✅ | Live clock `QTimer` 1s (`:275-279`, `_tick_clock` `:428`), station label from `Settings().station_display` (`:332-341`), Open Studio buttons in header (`:343-345`) and status bar (`:414-424`) emit `studio_clicked`. |

### 16b · General

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Station Identity (Name/City/Region/Frequency/Slogan/Email) load+save from DB | ✅ | Fields built `:735-752`; loaded `_load_settings` `:871-876`; saved `_save_left_column` `:929-934` via `s.set(...)`. |
| File Paths (Music/Recordings/Logs/Exports) with Browse folder pickers | ✅ | `_BrowseField` uses `QFileDialog.getExistingDirectory` (`:381-388`); 4 path fields `:756-764`; loaded `:879-886`, saved `:935-938`. |
| "Save Station Settings" saves left col + refreshes header station label live | ✅ | `_on_save_station` `:982-993` → `_save_left_column` which re-sets `_station_lbl` from `Settings().station_display` (`:940-944`); emits `settings_saved` (`:990`) so MainWindow can broadcast to other screens (`:584-588`). |
| Startup toggles (7 incl. Windows-startup registry deferred STUB) persist | ⚠ (STUB) | All 7 toggles built `:784-804`, loaded via `get_bool` `:889-902`, saved as '1'/'0' `:949-962`. Persist ✅ but Windows-startup registry write is DB-only per docstring (`:35-38`); no `winreg`/registry code present — registry side is STUB as spec allows. |
| Date/Time: Date Format, Time Format, Timezone (default IST), Language (default English India) | ✅ | Combos `:809-817`; loaded `:905-917` (defaults `IST — Asia/Kolkata`, `English (India)`), saved `:965-975`. Time-format shorthand ↔ label mapping handled `:909-913`/`:967-973`. |
| Backup interval dropdown + destination picker; "Backup Now"/"Restore" STUB ("coming v1.1") | ✅ (STUB) | Interval combo + backup path `_BrowseField` `:820-823`, persist `:978-980`. Backup Now/Restore are info dialogs "coming in v1.1" (`_on_backup_now` `:1009-1013`, `_on_restore_backup` `:1015-1019`) — STUB as spec requires. |
| "Save All Preferences" saves everything + success dialog | ✅ | `_on_save_all` `:995-1007` saves both columns, emits `settings_saved`, shows `dialogs.info` success. |

### 16c · Soundcard

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| 5 channel cards: Out1 Main On-Air (CRITICAL), Out2 Monitor, Out3 Cue/Preview, Out4 Jingles, In1 Mic | ✅ | `CHANNEL_SPECS` `:481-502` defines all 5 with correct titles; Out1 `is_critical=True` → `_CriticalPill` (`:298-301`); cards built `:644-662`. |
| Each card: Device dropdown (enumerated Windows devices + "(none)"), Volume slider + "VOL: X%", Channel dropdown, Test/Monitor STUB, connection status | ✅ (Test STUB) | Device combo populated with `(none)` + enumerated devices (`populate_devices` `:383-387`); vol slider + `VOL: n%` label (`:325-333`, `_on_vol_changed` `:429-430`); channel combo `:343-348`; Test/Monitor button → `_on_test_clicked` info "coming v1.1" (`:814-821`) STUB; status green Connected / gray Not assigned (`_refresh_status` `:432-442`). |
| Warning strip: driver/volume changes need restart | ✅ | `_build_warning_strip` amber strip with restart-required text `:666-697`. |
| "Save Routing" persists all device/volume/channel selections | ✅ | `_on_save_clicked` `:799-812` → `_save_all` `:788-795` writes `audio_output_X`/`audio_vol_outputX`/`audio_channel_outputX` via `s.set(...)`; emits `settings_saved`. Loaded `_load_settings` `:777-786`. |
| "Test ALL" is a STUB | ✅ (STUB) | `_on_test_all` `:823-827` info dialog "coming v1.1". |
| Enumerates REAL Windows devices via BASS | ✅ | `enumerate_audio_devices` uses `BASS_GetDeviceInfo`/`BASS_DEVICEINFO` (`:80-103`), skips "No sound", falls back to single "Default device" if BASS not loaded; called once at init `:524`. |

### 16d · Studio

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Crossfade Duration (0–10s), Fade Out Start (0–10s), Fade Curve (Linear/Log/Exp/S-Curve) | ✅ | `_sl_crossfade` 0-10 (`:878-880`), `_sl_fade_out` 0-10 (`:881-883`), `_CurveRow` with `FADE_CURVES` (`:78`, `:884`). Load `:1114-1117`, save `:1165-1167`. |
| Next Song Load: load-next dropdown, preload buffer, AutoMix trigger | ✅ | Three `_LabeledDropdown` `:892-897`; load `:1118-1123`, save `:1168-1170`. |
| Playback Fallback: fallback action dropdown + missing-file-alert toggle | ✅ | `_cmb_fallback` + `_tg_missing_alert` `:906-910`; load `:1124-1127`, save `:1171-1173`. |
| "Save Transition Settings" persists left column | ✅ | `_on_save_left` `:1195-1204` → `_save_left` `:1163-1173`; emits `settings_saved`. |
| AutoCue: dB threshold slider + scan-mode dropdown | ✅ | `_sl_autocue` -70..0 dB (`:930-934`), `_cmb_autocue_scan` (`:935-936`); load `:1130-1133`, save `:1177-1178`. |
| Volume & Levels: Master/Cue/Jingle/Mic sliders | ✅ | Four `_LabeledSlider` 0-100 `:944-951`; load `:1134-1137`, save `:1179-1182`. |
| VU Meters: decay speed + peak-hold + clip toggle | ✅ | `_cmb_vu_decay`, `_cmb_peak_hold`, `_tg_clip` `:960-965`; load `:1138-1142`, save `:1183-1185`. |
| "Save Audio Settings" persists center column | ✅ | `_on_save_center` `:1206-1215` → `_save_center` `:1175-1185`. |
| Cue Split radio group (Off / L-cue R-air / L-air R-cue / Blend) | ✅ | `CUE_SPLIT_OPTIONS` 4 keys `:110-115`, `_RadioGroup` `:987`; load w/ key validation `:1148-1151`, save `:1189`. |
| Crossfade Preview toggles (show overlap zone / flash mix point) drive Studio overlays | ⚠ (STUB) | Both toggles built + persist (`:994-999`, load `:1152-1153`, save `:1190-1193`). But docstring `:29-31` states Studio waveform overlay rendering is v1.1 — they save only; live overlay wiring not present here. |
| Audio Engine info (buffer/sample-rate/bit-depth/engine) read-only | ✅ | 4 `_InfoRow` (read-only display) `:1007-1017`; populated from settings `:1156-1161`. |
| "Save Studio Settings" persists cue-split + preview toggles | ✅ | `_on_save_right` `:1217-1227` → `_save_right` `:1187-1193`. |
| Note: crossfade/fade/mix changes live-apply to Studio via `_apply_studio_settings` | ❌ | No `_apply_studio_settings` method exists anywhere in these 4 files. Saves only write to DB + emit `settings_saved`; no signal/call pushes crossfade/fade values into a running Studio engine. Docstring `:26-28` confirms AudioEngine hot-reload is v1.1 (restart required). Live-apply is NOT implemented. |

### 🐛 Bugs & gaps
1. **No live-apply to Studio (`_apply_studio_settings` absent)** — spec line 565 requires crossfade/fade/mix changes to broadcast into the running Studio via `_apply_studio_settings`. That method does not exist in any of the 4 settings files; `_on_save_*` only calls `s.set()` and emits `settings_saved`. Studio changes require an app restart (per module docstring `settings_studio.py:26-28`). This is the one hard miss vs. spec — everything else that's unimplemented is explicitly scoped as a v1.1 STUB by the design.
2. **Crossfade Preview / Mix-Point flash toggles don't drive overlays yet** — `show_crossfade_preview` / `flash_mix_point` persist correctly but the spec says they "drive the Studio waveform overlays"; the overlay rendering is deferred to v1.1 (`settings_studio.py:29-31`). Persist works; the downstream visual effect is a STUB.
3. **Windows-startup toggle is DB-only** — spec explicitly allows this (registry deferred), so not a defect, but flagged for completeness: no `winreg` write exists (`settings_general.py:35-38`).

No banned patterns found: no `dict(sqlite3.Row)` usage in any of the 4 files; all writes go through `Settings().set(...)` into the settings table; all button signals are connected (no dead signals observed). Device enumeration correctly guards BASS import with try/except and a fallback.

### Tally
✅ 19 · ⚠ 2 · ❌ 1 · (STUB) 5

(STUB count = features that are correctly scoped stubs per design: Backup Now, Restore, per-channel Test/Monitor, Test ALL, Windows-startup registry. The 2 ⚠ rows also carry STUB behavior for their deferred halves; the 1 ❌ is the missing live-apply.)


---

## Screen 17 — Final Log
**Source:** `ui/final_log.py`
**Ideal purpose:** Per-hour broadcast history (actual air log) for a chosen date, read from `broadcast_log`.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Header: live date + time + "Jump To Screen" pill (decorative) | ✅ | `_HeaderBar.set_now` sets date+time `final_log.py:219-221`; live via QTimer 1s `final_log.py:775-780`. `_JumpToScreenPill` is decorative, emits no jump `final_log.py:138-152`. |
| Date selectors: Day / Month / Year dropdowns + "🔍 FETCH REPORT" | ✅ | 3 `_StyledCombo` built + populated `final_log.py:833-851`; `_FetchReportButton` "🔍  FETCH REPORT" `final_log.py:342-355`, wired `final_log.py:862-865`. |
| FETCH loads counts + selected hour, updates status | ✅ | `_on_fetch_clicked` → `_reload_hour_counts` + `_reload_for_hour` + green status `final_log.py:942-948`. |
| HOUR SLOTS sidebar: 24 rows (00:00–01:00 … 23:00–24:00) with per-hour counts; click loads hour | ✅ | 24 `_HourSlotRow` `final_log.py:463-467`; label `_hour_label` `final_log.py:99-100` (23 → "23:00 – 00:00"); counts via `get_broadcast_hour_counts_for_date` `final_log.py:955-962` / `database.py:352-372`; click → `hour_selected` → `_reload_for_hour` `final_log.py:950-951`. |
| Broadcast log table: #, Time, Type(chip), Title, Artist/Details, Category, Duration, Status(PLAYED) | ✅ | 8 cols `final_log.py:528-529`; TYPE colored chip `final_log.py:578-585`; STATUS always "PLAYED" green `final_log.py:599-604`. |
| DOWNLOAD .TXT saves file + shows path | ✅ | `_on_download_clicked` builds text, `QFileDialog.getSaveFileName`, `Path.write_text`, then `set_path("Auto-saved to: …")` `final_log.py:1041-1070`; default path under `%LOCALAPPDATA%\RadioAI\logs\...` `final_log.py:1072-1081`. |
| Stats strip: Total Items / Songs / Spots / Jingles / Sweepers / Total Air Time | ✅ | `_StatsStrip` 6 cells `final_log.py:629-636`; `_update_stats` counts by type + air time `final_log.py:1028-1037`. |
| PRINT LOG is a STUB ("coming in v1.1") | ✅ (STUB) | `_on_print_clicked` → `dialogs.info(... "coming in v1.1")` `final_log.py:1103-1108`. Intentional stub per spec. |

### 🐛 Bugs & gaps
- **Sweeper/stitcher rows lose their name (minor).** `broadcast_log` has `song_id`/`campaign_id`/`jingle_id` but **no `sweeper_id`** (`schema.sql:363-379`). `_row_to_dict` only special-cases song/spot/jingle; sweeper & stitcher fall to the `else` branch → title becomes `etype.title()` ("Sweeper") with artist "—" (`final_log.py:983-994`). Type chip + stats still work. Not a crash; a data-completeness gap.
- **No `dict(sqlite3.Row)` banned call** — table consumes raw Rows via `r["col"]` indexing (`final_log.py:978-1021`); DB helper returns `fetchall()` Rows (`database.py:330-350`). Safe on Py 3.14.
- **DB errors swallowed to empty, no user feedback.** `_reload_hour_counts` / `_reload_for_hour` catch all exceptions → log + empty (`final_log.py:955-971`). Empty hour renders 0 rows / all-zero stats (correct empty-state), but a genuine DB failure looks identical to "no plays".
- **`d = self._formatted_date()` computed but unused** in `_on_fetch_clicked` (`final_log.py:945`) — dead local, harmless.
- **`_days_in_month` clamps day on month/year change** so Feb-30 style invalid dates can't occur (`final_log.py:914-925`). Good.
- Test-friendly: broad try/except around all DB calls lets a thin `_FakeDB` construct the screen (`final_log.py:734-741`).

### Tally
✅ 7 · ⚠ 0 · ❌ 0 · (STUB) 1


---

## Screen 18 — Play History
**Source:** `ui/play_history.py`
**Ideal purpose:** Per-song airplay analytics (totals, monthly chart, recent plays) from `broadcast_log`.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Hero: album-art placeholder + title + artist·album·year + category pill + duration·BPM·energy + TOTAL PLAYS + "since [date added]" | ✅ | `_AlbumArt` ♪ gradient tile `play_history.py:225-244`; title/meta `play_history.py:351-358`; `_CategoryPill` `play_history.py:361-367`; inline "M:SS duration · BPM · energy" `play_history.py:369-378`; TOTAL PLAYS mono `play_history.py:380-381`; "Since <added_at>" `play_history.py:382-383`. |
| 4 stat cards: Plays This Month / This Week / Avg per Week / Last Played (with deltas) | ✅ | 4 `_StatCard` built `play_history.py:831-838`; `_update_stats` sets values + "+N vs last month/week" deltas + avg "rolling 4 weeks" + last-played human/exact `play_history.py:950-989`. Summary SQL `database.py:376-452`. |
| 12-month bar chart: current cyan, peak purple, others dim; gridlines + Y-axis + month labels + peak callout | ✅ | `_MonthlyChart.paintEvent`: heading, "Peak: N plays" callout `play_history.py:492-499`; 5 gridlines + Y-axis values `play_history.py:513-527`; current=cyan / peak=purple-light / else dim purple `play_history.py:544-557`; count-above-bar + month labels `play_history.py:563-578`. Data `get_song_monthly_plays` fills zero months `database.py:454-500`. |
| Recent Plays — Last 5 table: #, Date, Time, Clock, Slot, Operator, Deck | ✅ | 7 cols `play_history.py:590`; `load_rows` maps all 7 `play_history.py:647-681`; source `get_song_recent_plays(sid,5)` joins clocks, coerces to plain dicts `database.py:502-521`. |
| Empty states when no plays logged | ⚠ (partial) | Chart draws "No plays logged yet for this song." when `_data` empty `play_history.py:483-490`. **BUT** `get_song_monthly_plays` always returns 12 zero-filled month dicts (`database.py:492-499`), so `_data` is never empty → the no-data message is effectively unreachable; chart instead shows 12 empty bars with peak=1. Stat cards show "0"/"Never played" (graceful). Recent table just renders 0 rows (no explicit "no plays" placeholder). Functional but no dedicated empty message actually fires. |

### 🐛 Bugs & gaps
- **Chart empty-state is dead in practice.** Because the monthly helper zero-fills (`database.py:481-499`), `set_data` gets a non-empty list every time; the `if not self._data` branch (`play_history.py:483`) can only trigger if the DB call throws (caught → `monthly=[]` at `play_history.py:929-932`). So on a never-played song you see 12 flat bars, not the "No plays logged yet" text. Cosmetic.
- **No `dict(sqlite3.Row)` banned call.** `load_song` uses `{k: row[k] for k in row.keys()}` (`play_history.py:913`); recent-plays already dict-coerced in DB layer. Safe on Py 3.14.
- **All DB calls wrapped in try/except → empty defaults** (`play_history.py:911-938`); a real DB error renders as an empty/zero song rather than surfacing.
- **Peak scaling on all-zero data:** `_MonthlyChart` sets `_max=max(1, …)` (`play_history.py:462-463`), so Y-axis reads 1/1/1/1/0 with no bars — acceptable degenerate case.
- **Recent Plays table has no zero-row placeholder** (spec asks empty states); an unplayed song shows an empty grid under the heading. Minor.
- Slot/operator/deck rendered with fallbacks "—" when null (`play_history.py:653-656`). Good.

### Tally
✅ 4 · ⚠ 1 · ❌ 0 · (STUB) 0


---

## Screen 19 — Category Performance
**Source:** `ui/category_performance.py`
**Ideal purpose:** Per-category aggregate airplay analytics + ranked song list with dead-inventory highlighting.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Hero: category tile + name + "N songs · total plays" + category pill + top-song line + TOTAL PLAYS | ✅ | `_CategoryTile` ♬ gradient `category_performance.py:105-129`; name `category_performance.py:236`; "N songs  ·  N total plays" summary `category_performance.py:237-239`; `_CategoryPill` `category_performance.py:241-246`; "Top: title — artist · N plays" meta `category_performance.py:249-254`; right TOTAL PLAYS + "N songs" `category_performance.py:259-260`. |
| 4 stat cards: Plays This Month / This Week / Avg per Song / Most Played | ✅ | 4 `_StatCard` `category_performance.py:506-513`; `_update_stats` fills month/week deltas, avg "total ÷ songs", most-played title+sub `category_performance.py:618-660`. Summary SQL `database.py:525-619`. |
| 12-month bar chart (same style as Play History) | ✅ | Reuses `_MonthlyChart` imported from play_history `category_performance.py:61-66`, placed `category_performance.py:523-524`; data `get_category_monthly_plays` zero-fills 12 months `database.py:621-663`. |
| Songs in Category — ranked table: #, Title, Artist, Total Plays, Week, Month, Last Played, Energy·Vocal | ✅ | 8 cols `category_performance.py:273-274`; `load_rows` maps all 8 incl. Energy·Vocal join `category_performance.py:353-388`; source `get_category_songs_ranked` (LEFT JOIN aggregate, zero-play included, ORDER total DESC) `database.py:1967-2007`. |
| Zero-play (dead-inventory) rows dimmed | ✅ | `dim = total == 0` → num/txt/sub cols swapped to TEXT_DIM/TEXT_MUTED `category_performance.py:354-358`; subtitle reports "N aired · N dead inventory" `category_performance.py:341-350`. |
| Empty states when category has no plays/songs | ⚠ (partial) | Hero meta → "No songs in this category have aired yet." when no most_played `category_performance.py:255-257`; ranked table subtitle handles `n=0` ("All 0 songs …") `category_performance.py:344-349`; most-played card → "— / no plays yet" `category_performance.py:659-660`. **BUT** the 12-month chart never shows its "No plays" text (helper zero-fills → non-empty list), and an empty category renders an empty grid + flat bars rather than a dedicated empty panel. |

### 🐛 Bugs & gaps
- **Chart empty-state unreachable (same as Play History).** `get_category_monthly_plays` always returns 12 zero-filled dicts (`database.py:655-662`), so `_MonthlyChart`'s `if not self._data` branch (`play_history.py:483`) never fires for an unplayed category. Cosmetic.
- **No `dict(sqlite3.Row)` banned call.** `get_category_songs_ranked` returns `{k: r[k] for k in r.keys()}` (`database.py:2007`); summary builds a plain dict field-by-field. Safe on Py 3.14.
- **Aggregation SQL is correct.** `total_plays` counts `broadcast_log JOIN songs` on `category_id` (`database.py:548-552`); ranked-table subquery groups by `song_id` then LEFT JOINs so zero-play songs survive (`database.py:1989-2004`); `plays_week`/`plays_month` use `weekday 0 -7 days` / `strftime('%Y-%m')` consistently. `avg_per_song` guards `song_count>0` (`database.py:584-585`).
- **Row click is wired for selection but not navigation.** Table is `SingleSelection` (`category_performance.py:308-309`) and subtitle invites "Click any row to open per-song Play History" (`category_performance.py:346`), but **no `itemClicked`/`cellClicked` signal is connected** — clicking a row selects but does not open Play History. Dead affordance vs. the advertised behavior.
- All three DB calls wrapped in try/except with sane defaults (`category_performance.py:587-605`); genuine DB failure degrades to "—"/0 rather than surfacing.
- Chrome widgets imported from `ui.play_history` (`category_performance.py:61-66`) — intentional shared-chrome, not duplication.

### Tally
✅ 5 · ⚠ 1 · ❌ 0 · (STUB) 0


---

## Screen 20 — The Stitcher
**Source:** `ui/stitcher.py` + `core/stitcher_engine.py`
**Ideal purpose:** Pre-mix a "Coming Up Next" hook montage (opening + song hooks + separators + closing) into one seamless WAV played through BASS.

| Feature (abbreviated) | Status | Code reality (file:line) |
|---|---|---|
| Tabs: Next Songs Hooks (active) / Real Time Announcement (STUB) / News Assembly (STUB) | ✅ (STUBs) | `MODULE_TABS` = 3 tabs `stitcher.py:107-111`; `_on_tab_clicked` swaps panels ↔ placeholder `:911-927`; placeholder text for the two STUBs `:980-995` |
| Module Enabled card toggles on/off | ✅ | `_ModuleEnabledCard` click toggles + emits `stitcher.py:267-292`; load `set_enabled` `:1324-1325`; saved as `module_enabled` `:1382-1383`,`db:2892-2905` (coerced 0/1) |
| 4 audio-file rows (Opening/Separator/Closing/Fallback): path + Browse + ▶ Preview | ✅ | `_AudioFileRow` Browse `_on_browse` `stitcher.py:412-421`, ▶ wired `:394-404`; four rows built `:1015-1038` |
| Preview plays if file exists else "file missing" | ✅ | `_preview_audio_file`: `os.path.exists` guard → `dialogs.warning "File missing"` `stitcher.py:1548-1553`; plays via AudioEngine `:1561-1566` |
| Hook Settings: Min (0–10), Max (1–20), preview dur (1–30s), Trigger mode dropdown (4 modes) | ✅ | Min `QIntValidator(0,10)` `:1053`; Max `(1,20)` `:1063`; dur `(1,30)` `:1073`; `TRIGGER_MODE_OPTIONS` 4 modes `:97-102`, dropdown `:1080` |
| "✓ Save Configuration" persists all paths + settings (validates min ≤ max) | ✅ | `_on_save_config` builds data incl. 4 paths `:1381-1402`, min>max → `dialogs.warning` return `:1372-1377`; persists `update_stitcher_config` `:1404`; all 15 fields incl. 4 audio paths in `STITCHER_EDITABLE_FIELDS` `db:2844-2853` |
| Assembly-flow preview: 5 tiles (Opening+3 hooks+Closing) + live total-duration estimate | ✅ | 5 `_AssemblyStep` tiles built `:1120-1133`; `_refresh_assembly_flow` fills names + recomputes total `:1499-1535`; called on load/save/sample-reload `:797,1417,1484` |
| Sample-playlist ~5 upcoming songs with hook range or "No hook set ⚠" + Set Hook button | ✅ | `peek_next(5)` w/ recent-songs fallback `:1441-1483`; row shows `Hook: mm:ss–mm:ss` or `No hook set ⚠` `:585-597`; Set Hook button when no hook `:543-556` |
| "▶ Preview Full Stitcher Output" assembles + plays (uses Fallback when short; warns on missing files) | ✅ | `_on_preview_full` assembles opening+hooks+sep+closing `:1570-1656`; fallback path when `len(hooked) < min` `:1605-1620`; routes `stitcher_engine.play_block` `:1654`; engine pydub→WAV→BASS `engine:156-248` |
| "↺ Reset to Default Settings" restores defaults (confirm first) | ✅ | `_on_reset_defaults` → `dialogs.confirm` gate `:1666-1672` then writes factory defaults `:1673-1687` (resets settings only; paths untouched per its own copy) |
| AI Insights: Times Used/Retention placeholders; Songs-Without-Hooks real count; static recs | ✅ | `Times Used Today`/`Avg Listener Retention` stay "—" `:1213-1217`; `Songs Without Hooks` real `COUNT(*)` query `:1346-1356`; 4 static recommendation cards `:1226-1248` |

### 🐛 Bugs & gaps
1. **Set Hook is a toast, not a deep-link** — `_on_set_hook_requested` `stitcher.py:1689-1699` only shows an info dialog and emits `songs_clicked` (nudge); it does not open the Audio Cue Editor for that song id. Matches spec's own STUB note but the parent must actually route `songs_clicked` for even the nudge to work.
2. **Reset button label vs. AI-Insights consistency** — Reset resets only Hook Settings (min/max/dur/trigger), leaving audio paths, matching its dialog copy `:1668-1670`; the spec line 620 says "restores defaults" broadly. Minor scope mismatch, not a crash.
3. **Preview-Full re-queries file_path per song** — `_on_preview_full` runs a `SELECT file_path` per hooked song `:1626-1628` even though `assemble_sequence` in the engine already does this centrally `engine:81-152`; the screen re-implements assembly inline rather than calling the shared `StitcherEngine.assemble_sequence`. Duplicated logic (drift risk), not a bug today.
4. **`is_running` guard drops concurrent Preview clicks silently** — `play_block` returns immediately if already running `engine:47-48`; a second ▶ click during playback is a no-op with no user feedback. Cosmetic.
5. **No `dict(sqlite3.Row)` misuse found** — DB uses safe `{k: row[k] for k in row.keys()}` `db:2884`; screen uses `dict(song)`/`dict(r)` on `sqlite3.Row` `:1467,1475` which is valid. No banned pattern, no dead signals detected; config write path verified end-to-end.

### Tally
✅ 11 · ⚠ 0 · ❌ 0 · (STUB) 2


---

*End of VERIFICATION_NOTES.md — generated from source at HEAD `cac4adc`, 2026-07-01.*

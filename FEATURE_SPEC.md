# RadioAI Studio Pro — FEATURE SPECIFICATION (Expected Behavior)

> **Purpose.** This document lists EVERY feature of EVERY screen/tab,
> and how each SHOULD ideally work. Use it to cross-verify: go screen
> by screen, tick each `[ ]` box if the actual app behaves as written,
> flag it if it doesn't.
>
> **How to use with a new Claude session:** "Open FEATURE_SPEC.md.
> We are on SCREEN X. Go feature by feature — for each, tell me if the
> code actually does this. Mark ✅ works / ❌ broken / ⚠ partial."
>
> **Ground rules for this doc:**
> - Each screen is a self-contained section. Nothing is mixed between screens.
> - Every `- [ ]` is one testable behavior (the IDEAL — what it should do).
> - Derived from the actual source code (2026-07-01), not guesses. Where
>   the code shows a feature is a stub / "coming soon", it is marked **(STUB)**.
> - Exact pixel positions and live DB counts are intentionally omitted —
>   this is a BEHAVIOR spec, not a pixel spec.
>
> **Screen index:**
> 1. Control Panel · 2. Songs Library (+dialogs) · 3. Spots & Commercials (+dialogs)
> · 4. Jingles Library · 5. Sweepers Library · 6. Instant Jingles · 7. Studio
> · 8. Scheduling Hub · 9. Main Auto Schedule · 10. Clock Editor
> · 11. Playlists (Browse / New / Edit) · 12. AI Magic Hub
> · 13. Spot on the Go (Shell + 4 steps) · 14. Scheduling Automation (Hub + Plan Review)
> · 15. Rotation Health · 16. Settings (Hub / General / Soundcard / Studio)
> · 17. Final Log · 18. Play History · 19. Category Performance · 20. The Stitcher

---

# 1. CONTROL PANEL (Home Hub)

**Purpose:** Central dashboard — 6-7 library cards + top navigation, real-time stats.

**Header / chrome**
- [ ] Logo + "RadioAI / STUDIO PRO / BROADCAST AUTOMATION" branding shows top-left.
- [ ] Top nav tabs "Libraries / Scheduling / Settings / AI Magic ✦" are clickable; each routes to its screen.
- [ ] Header clock shows live HH:MM :SS + weekday + date, updating every second.
- [ ] Active-Station card shows station name + location + a pulsing green dot.
- [ ] "Open Studio" CTA opens the Studio broadcast screen.
- [ ] "LIVE" pill top-right shows a live HH:MM:SS clock with a pulsing red dot.

**Library cards (grid)**
- [ ] Each card (Songs, Instant Jingles, Spots & Commercials, Jingles, Sweepers, Stitcher, Scheduling) shows its real DB stat line (song count, jingle count, active campaigns, etc.).
- [ ] Each card has an icon, an accent color, a category badge, and an "Open →" button.
- [ ] Clicking a card (or its Open button) navigates to that library screen.
- [ ] Card hover brightens the border/background to the accent color.

**Footer**
- [ ] Footer shows "RadioAI Studio Pro • v2.0.0 • Program running X minutes".
- [ ] "⚙ Settings" link opens the Settings hub.

---

# 2. SONGS LIBRARY

**Purpose:** Master music catalog — view, filter, search, preview, edit categories, cue points, analytics.

**Header**
- [ ] Breadcrumb "Control Panel | Libraries | ● Songs" shows; links navigate.
- [ ] Page title "Songs Library" + subtitle shows.
- [ ] Live clock + station name shows; "▶ Open Studio" mini-button shows current Now-Playing.

**Sidebar — actions**
- [ ] Song-count box shows the current filtered song count.
- [ ] "+ Add New Song" opens the Add New Song dialog.
- [ ] "⤓ Mass Import" opens the Mass Import dialog.
- [ ] "✎ Edit Categories" opens the Edit Categories dialog.
- [ ] "✕ Delete" deletes the selected song (only enabled when a song is selected).

**Sidebar — search + filters**
- [ ] Search box filters the table in real time (matches title/artist).
- [ ] Category dropdown filters by category.
- [ ] Energy dropdown filters by Low/Medium/High.
- [ ] Vocal dropdown filters by Male/Female/Instrumental.
- [ ] BPM dropdown filters by range.
- [ ] Enabled dropdown filters Only Enabled / All / Disabled.

**Sidebar — reports**
- [ ] "📊 Category Performance" opens the Category Performance report for the selected category.
- [ ] "🎯 Rotation Health" opens the Rotation Health report.
- [ ] "⏱ Last Played" opens the Last Played report. **(may be STUB)**
- [ ] "📈 Top Songs" opens the Top Songs report. **(may be STUB)**

**Song table**
- [ ] Columns: status dot, Title, Artist, Category pill, Duration, BPM, Last Played.
- [ ] Duration renders MM:SS; Last Played renders relative ("2h ago", "3d ago", "—").
- [ ] Category pill is color-coded to the category.
- [ ] Single click selects a row; Ctrl-click toggles; Shift-click range-selects; click-drag multi-selects.
- [ ] Selected row highlights (cyan tint + left accent + bold title).
- [ ] Per-row ▶ play button previews the song (~15s cap), toggles to ■ while playing, only one preview at a time.

**Detail panel (right)**
- [ ] Tabs: "Song Details" / "Audio Cues" / "Play History".
- [ ] "Audio Cues" tab opens the Audio Cue Editor for the selected song.
- [ ] "Play History" tab opens the per-song Play History report.
- [ ] Song header card shows title, artist·year, and Enabled/Disabled + Category badges.
- [ ] Read-only fields show Title/Artist/Album/Year/Category/Energy/Vocal/BPM.
- [ ] Audio-preview waveform + start/end time labels render.
- [ ] "✎ Edit Cues" opens the Audio Cue Editor.
- [ ] AI insight box shows rotation/frequency hint. **(insight text may be placeholder)**

## 2a. DIALOG — Add New Song
- [ ] AUTO CODE (6-digit) is generated and shown.
- [ ] Artist field is required; "Find Artist" opens the picker, "+ New" opens Add Artist prefilled.
- [ ] Song Title field is required.
- [ ] Optional fields: Album, Playlister Code, Label, CD Key, Barcode, Songwriter, Comments, Composer.
- [ ] Category pills (mutually exclusive) select the song's category.
- [ ] Track property dropdowns: Era, Vocal, Priority, Year (defaults current), BPM.
- [ ] "..." Browse picks an audio file (mp3/wav/flac/m4a/ogg); path shows in the read-only field.
- [ ] Duration is auto-read from the file (mutagen).
- [ ] Enabled checkbox (default on) + Frozen checkbox (default off).
- [ ] **Relaxed validation (2026-05-17):** empty artist → "Unknown Artist"; empty title → filename; but audio file is REQUIRED (else "Audio file required").
- [ ] Save persists the song and closes; Cancel discards.
- [ ] "✦ AI Auto-fill Metadata" shows a "coming in a future phase" info dialog. **(STUB)**

## 2b. DIALOG — Mass Import Songs
- [ ] Counters show Selected / Ready / Errors.
- [ ] "Browse" picks a folder; "Scan" walks it (threaded) reading ID3 tags.
- [ ] Filter chips: Include subfolders, MP3, WAV, FLAC (toggle which types scan).
- [ ] Review table columns: checkbox, Filename, Artist(ID3), Title(ID3), Duration, Status.
- [ ] Status pill: "Ready" (green, tags found) / "No Tags" (amber, importable via fallback) / "Error" (red, unreadable).
- [ ] **Relaxed (2026-05-17):** "No Tags" rows are IMPORTABLE — checkbox enabled; row shows the fallback (filename→title, "Unknown Artist"→artist) that will actually be saved. Only "Error" rows stay disabled.
- [ ] "Select All" / "Deselect All" toggle importable rows.
- [ ] Default settings apply to all imported: Category, Era, Year, Priority, Enabled.
- [ ] "Skip duplicate songs" checkbox (default on) + match mode (Artist+Title / File path / Filename).
- [ ] Import runs threaded with a progress bar 0→100%; UI disables during import.
- [ ] On finish, summary shows "N added • M skipped • P errors".

## 2c. DIALOG — Edit Categories
- [ ] Left pane lists all categories with color dot, name, description, song count.
- [ ] "+ Add" creates a category; "✎ Rename" renames; "✕ Delete" deletes (with confirm; cannot delete the last remaining one).
- [ ] Right pane edits: Name (required, unique), Color (10 swatches), Description, Auto-Rotate mode, Min Separation Time.
- [ ] "Songs in this category" preview shows first ~5 artist names + "+N more".
- [ ] "✓ Save Category" writes to DB, flashes success, and emits a categories-changed refresh.
- [ ] Deleting a category with songs warns that those songs will be unassigned.

## 2d. DIALOG — Audio Cue Editor
- [ ] Shows the song's synthetic waveform with a time ruler.
- [ ] 6 draggable markers: START, INTRO, HOOK IN, HOOK OUT, OUTRO, MIX.
- [ ] Waveform bars are color-zoned by marker (green/white/pink/white/red).
- [ ] Dragging a marker clamps to its neighbors' bounds and snaps to a 100ms grid.
- [ ] HOOK OUT − HOOK IN must stay ≥ 100ms.
- [ ] Order is enforced: START ≤ INTRO ≤ HOOK IN < HOOK OUT ≤ OUTRO ≤ MIX ≤ duration.
- [ ] Six cue cards (one per marker) show the current time + "<<100ms"/">>100ms" nudge + Preview + Reset buttons.
- [ ] Fade In / Fade Out sliders (0–2000ms).
- [ ] "✓ Save Cues" validates and writes cue points to the song; Cancel discards.
- [ ] Preview button flashes (audio preview is **STUB** in this phase).

## 2e. DIALOG — Find Artist / Add Artist
- [ ] Find Artist: live search on name/country/genre + filter pills (All / Recently Added / Most Played / Favorites).
- [ ] Artist row shows avatar initial, name, country·genre, favorite star, song count.
- [ ] Click selects; double-click selects + closes; star toggles favorite.
- [ ] "+ Add New" opens Add Artist prefilled with the search text.
- [ ] Add Artist: Name (required) + Display Name, Country, Primary Genre, Era, Notes.
- [ ] Save enforces unique artist name; duplicate → error; success closes and returns the new artist.
- [ ] "✦ AI Auto-fill from artist name" shows a "coming soon" dialog. **(STUB)**

---

# 3. SPOTS & COMMERCIALS

**Purpose:** Manage ad campaigns, spot files, break schedule, and play reports.

**Sidebar**
- [ ] Counter shows "active/total campaigns".
- [ ] "+ Add Campaign" opens Add Campaign in create mode.
- [ ] "✎ Edit Campaign" opens Add Campaign in edit mode for the selected row.
- [ ] "🗓 Schedule Breaks" opens the Spot Programming (break grid) dialog.
- [ ] "✕ Delete" deletes the selected campaign (with confirm) + its data.
- [ ] Filters: Status (Active/Expired/All), Category, Priority, Day.
- [ ] Reports section links (Actual Play Times / Spot Schedule / Daily Programming / Break Duration / Traffic). **(deferred/STUB)**

**Campaign table**
- [ ] Columns: status dot, Name, Spots(file count), Category pill, Priority pill, Start Date, End Date.
- [ ] Single-click selects + populates detail panel; double-click opens edit.
- [ ] Row highlight on select; zebra striping; scrollable.

**Now Airing strip (manual preview)**
- [ ] ▶/■ plays the first active spot file of the selected campaign (green idle, red playing).
- [ ] Shows "NOW AIRING: [name]" + progress bar + "MM:SS / MM:SS".
- [ ] Playback stops when the screen is hidden.

**Detail panel tabs**
- [ ] "Campaign Details" shows metadata + spot files + a weekly break grid preview.
- [ ] "+ Add File" adds an audio file to the campaign.
- [ ] Each spot file row shows filename + duration + Active/Off badge.
- [ ] "Play Reports" tab: mode (Actual Broadcast / Scheduled), Start/End date pickers, "Reset to campaign window", "✦ Generate PDF Report".
- [ ] Generate PDF writes a PDF to the reports dir, opens it, and shows the save path + timestamp; warns if 0 bytes.

## 3a. DIALOG — Add Campaign
- [ ] AUTO CODE box shows/edits the campaign code.
- [ ] Required: Campaign Name, Start Date, End Date (date pickers via "...").
- [ ] Dropdowns: Programming Mode, Playback Order, Category, Priority.
- [ ] Audio Files panel lists attached files; "+ Add File" adds more; empty state shows "No files added yet".
- [ ] Availability: Active vs Draft (one selected).
- [ ] Campaign Type pills: Commercials / Station ID / News Break / Sponsor / Promo / Custom.
- [ ] Save validates + inserts the campaign and returns its id; Cancel discards.
- [ ] "✦ AI Auto-fill Campaign" is a **STUB** toast.

## 3b. DIALOG — Campaign Date Picker
- [ ] Month nav (‹ ›) + "Month Year" label.
- [ ] 6×7 calendar grid; out-of-month + before-min days are dim/non-clickable; today has a ring; selected day is filled.
- [ ] Quick-select: Today, In One Month, and (start-date mode only) "Never".
- [ ] OK returns the chosen date (or "Never"); Cancel discards.

## 3c. DIALOG — Spot Programming (break grid)
- [ ] Grid is 144 rows (10-min slots, 00:00–23:50) × 7 day columns.
- [ ] Left panel: live total-spots count + Priority selector (High/Medium/Low).
- [ ] Presets: Morning Drive / Lunch Hour / Drive Time / Late Night populate the grid.
- [ ] "+ Add" fills selected cells at current priority; "− Remove" clears; "Clear All" wipes all (confirm).
- [ ] "Paste to All Days" / "Paste to Selection" copy a day's pattern.
- [ ] Cells color by priority: High=red, Medium=amber, Low=cyan.
- [ ] Click toggles a cell; drag rectangle-selects; Esc clears selection; right-click menu (add/delete/change priority).
- [ ] Apply saves to campaign_schedule (or stages to the parent dialog).

---

# 4. JINGLES LIBRARY

**Purpose:** Station-identity audio catalog.

- [ ] Header: breadcrumb, live clock, station name, "Open Studio".
- [ ] Counter shows "X jingles / Y enabled".
- [ ] "+ Add New Jingle" opens the Jingle Editor dialog.
- [ ] Search filters by name/category/playlister code.
- [ ] Filters: Category, Properties, Duration; "Only Enabled" checkbox.
- [ ] Table columns: bell dot, Name, Category pill, Duration, Properties pill, Last Used.
- [ ] Single-click selects; double-click opens the editor; right-side ▶ previews (~15s cap, mono, ▶↔■).
- [ ] Detail tabs: Jingle Details (read-only fields) / Schedule / Usage Stats.
- [ ] AI rotation insight + 7-day play count show. **(insight may be placeholder)**
- [ ] Mass Import / Edit Categories / Delete / Export-to-Playlister are **STUB** toasts.

---

# 5. SWEEPERS LIBRARY

**Purpose:** Audio overlays that play on top of songs at timing positions.

- [ ] Header: breadcrumb, clock, station, "Open Studio".
- [ ] Counter shows "active/total sweepers".
- [ ] "+ Add New" opens the Sweeper Editor dialog.
- [ ] Position filter list: All / Start of Song / Before Intro / Before End / Bridge at End / Independent / Custom Position (selecting one filters the table).
- [ ] Table columns: status dot, Name, Position pill, Duration, Category pill, Properties, Last Used.
- [ ] Single-click selects; double-click opens editor.
- [ ] "How Sweeper Positions Work" explainer shows a song timeline with position markers.
- [ ] Detail panel: read-only fields + a Position-Settings selector (6 positions).
- [ ] ▶ preview (wiring may be partial).
- [ ] Mass Import / Edit Categories / Delete / Export are **STUB** toasts.

---

# 6. INSTANT JINGLES (Live Pad Grid)

**Purpose:** Live DJ tool — trigger jingles instantly with hotkeys.

- [ ] Header: breadcrumb, clock, station, "Open Studio".
- [ ] Left sidebar lists pallets; clicking one loads its pads into the grid; selected pallet highlights.
- [ ] Tabs across the top switch between pallets.
- [ ] Pad grid (up to 5×6): filled pads show color + label + duration; empty pads show "NEW ENTRY / Empty slot".
- [ ] Left-click a filled pad → plays it immediately (▶→■ while playing).
- [ ] Right-click a pad → opens the pad editor on the right.
- [ ] Number keys 1–9 (and 0) trigger the corresponding pads; Escape stops all.
- [ ] Pad editor: mini preview, 10 color swatches, Label, Audio File (assign/clear), Output (1–8), Volume %, Behaviour (Play once / Loop / Latch), Test/Preview.
- [ ] AI insight box shows the pad's 7-day usage.
- [ ] Bottom controls: "Stop All" (works), AutoGain / MixFade / Loop / Latch toggles. **(AutoGain/MixFade are STUBs)**
- [ ] Polyphony: up to 8 pads play at once through the InstantJingleEngine.

---

# 7. STUDIO (Broadcast Workstation)

**Purpose:** The on-air control center. Zones: Header, Master Strip, Libraries, Up Coming, Instant Jingles, History/Break/RDS/Problems, Bottom Transport.

## 7a. Header
- [ ] Logo + wordmark + "BROADCAST AUTOMATION" show.
- [ ] Center analog/digital clock shows HH:MM :SS + weekday + date.
- [ ] Active-Station card shows station name + location (or the active clock name).
- [ ] SIGNAL pill: green dot when engine streaming OK, red otherwise.
- [ ] STREAM pill: green when streaming, amber otherwise.
- [ ] AUTO pill: purple; PULSES green when the scheduler is running.
- [ ] "‹ Control Panel" button returns to the hub.
- [ ] "⚙" settings cog opens Studio Settings.

## 7b. Master Strip (Now Playing + transport)
- [ ] NOW player shows title, artist·year, elapsed / total, REMAINING box.
- [ ] "● ON AIR · LIVE" pulsing dot shows only while a track plays.
- [ ] Waveform renders with a moving playhead.
- [ ] CROSSFADE PREVIEW purple zone shows on the waveform when the Studio-Settings toggle is on.
- [ ] Flash-mix-point green line animates within ~10s before the mix point when its toggle is on.
- [ ] NEXT chip shows the next item's title/artist + a "TO AIR in Ns" countdown + INTRO badge when applicable.
- [ ] Control cluster: Restart (always on), Loop (toggle), Pause (toggle, disabled when idle), Stop Next (disabled when idle).
- [ ] Level meters (L/R VU) react to audio with peak-hold decay.
- [ ] Analog clock ticks discretely (hour/minute/second hands).
- [ ] MIC pill toggles mic state and emits a mic signal (audio ducks when live — **wiring may be partial**).

## 7c. Libraries panel (left)
- [ ] 7 type tiles: Songs (default) / Tracks / Jingles / Spots / Voice / Sweepers / Favorites; clicking one loads that library.
- [ ] Action buttons: ADD (append to queue), INSERT (at queue head), REPLACE (overwrite head), PREPAIR (load to deck paused), DELETE (remove from queue). INSERT/REPLACE/DELETE require a selected row.
- [ ] Songs table shows Artist + Title; single-click selects; double-click loads.
- [ ] Search + Search/Reset buttons + checkboxes (SuperSearch / Show Only NEW / Sort by Surname).
- [ ] Category dropdown opens a category menu; shows the current category + song count.

## 7d. Up Coming queue
- [ ] Shows the next items as rich cards, each with AT-time, duration, type glyph + colored tile + type badge (SONG/JINGLE/BREAK/VOICE/SOTG/SWEEPER/STATION).
- [ ] The NEXT card gets a rose glow + "NEXT" pill.
- [ ] Pending Spots/SOTG appear at the TOP of the queue (before songs), and items scheduled within the next 60s appear as preview cards.
- [ ] Single-click selects a card (selection persists across refreshes); double-click acts on it.
- [ ] "FADE NEXT" toggle sets whether to fade into the next queued song.
- [ ] Footer shows loaded-playlist total duration + name.
- [ ] **Queue does NOT reshuffle every second** — it only rebuilds on a real change (cursor advance / schedule reload / pending change).

## 7e. Instant Jingles panel (in Studio)
- [ ] 3×3 pad grid; filled pads show color + label + duration; empty pads show "NEW ENTRY".
- [ ] Click a pad → plays it; hotkeys 1–5 trigger the first five.
- [ ] A DEMO box shows the currently-playing jingle name + countdown.
- [ ] "Edit Bank" link opens the standalone Instant Jingles screen; "Last played: X" shows.

## 7f. History / Next Break / RDS / Problems
- [ ] History shows the last ~12 plays (time + artist − title), newest on top, refreshed as items air.
- [ ] "View Full History →" opens the full history.
- [ ] Next Break shows a big MM:SS countdown + break type / duration / spots; "Skip Break" and "Preview" buttons.
- [ ] RDS panel shows a live HH:MM + the on-air artist/title.
- [ ] Problems panel shows warnings (missing files etc.) with a count, or "All systems nominal".

## 7g. Bottom Transport
- [ ] ▶ Play (start/resume) + ■ Stop (hard stop).
- [ ] Progress slider shows "MM:SS / MM:SS"; clicking seeks to that position.
- [ ] AutoPlay toggle sets auto-advance on EOS.
- [ ] Right cluster: Up/Down (scroll queue), Stop All, Auto, MixFade, Loop.

## 7h. Playback & dispatch rules (the core behavior)
- [ ] **Song → song:** at the mix point (per-song `mix_point_ms`, else `duration − fade_out_start`), the outgoing song fades and the next starts on a fresh channel (crossfade). Both overlap for the crossfade duration.
- [ ] **Priority order is SOTG > Spot > Song** at every fade/EOS decision.
- [ ] **Pending FIFO:** multiple spots/SOTG at the same minute all queue (no overwrite) and fire back-to-back.
- [ ] **Defer-fade-when-pending:** if a Spot or SOTG is pending, the song does NOT fade early — it plays to natural EOS, then the spot/SOTG fires on a silent deck (no music-under-voice overlap).
- [ ] **Spot resume / SOTG resume:** after a spot/SOTG ends, chain (SOTG > Spot) then resume the song queue from the anchored song.
- [ ] **Stop Next:** current song plays to end, then idle; all pending spots/SOTG are dropped.
- [ ] **Loop:** current song repeats; all pending spots/SOTG are dropped.
- [ ] **Sweepers:** overlay-positioned sweepers play on top of the current song; sequential ones load like a song; sweepers with a missing/empty file are skipped (broadcast never stalls).
- [ ] **Auto-advance ON** (default) fires the next item at EOS; **OFF** (Live-Assist) goes idle until the operator clicks Play.

---

# 8. SCHEDULING HUB

**Purpose:** Navigation dashboard for the scheduling family.

- [ ] Header with clock, station, and nav buttons (Libraries / Settings / AI Magic / Studio).
- [ ] Tiles route to: Playlists, Main Auto Schedule, Force Clocks Schedule **(STUB)**, Rebroadcast Schedule **(STUB)**, RDS **(STUB)**, Final Log Creator, Log Viewer **(STUB)**.
- [ ] Studio launcher card shows NOW PLAYING + "▶ Go Live Now".
- [ ] Status footer shows "SYSTEM HEALTHY" (green) or "ENGINE STOPPED" (rose) + uptime.

---

# 9. MAIN AUTO SCHEDULE (24×7 clock grid)

**Purpose:** Assign clocks to each day+hour cell.

**Available Clocks panel**
- [ ] Lists all clocks; **scrollable** via mouse wheel + ▲/▼ chevrons + a thumb (2026-05-17 fix — all clocks reachable, not just 3).
- [ ] Clicking a clock selects it (rose highlight); shows a "N SLOTS" hint.

**SET + actions**
- [ ] "SET ›››" applies the selected clock to all selected grid cells; enabled only when both a clock AND cells are selected.
- [ ] "⊙ Create Clock" opens a new clock; "✎ Edit Clock" / "⧉ Duplicate Clock" (enabled only with a selection).
- [ ] "🗑 Delete Clock": **refuses** if the clock is still assigned to any grid cell (warns to clear cells first); otherwise confirms + deletes (2026-05-17 fix).
- [ ] "⚙ Auto Program Settings" routes to that screen. **(may be STUB)**

**Grid**
- [ ] 24 rows (hours) × 7 day columns; each assigned cell shows the clock name + color.
- [ ] Single-click selects a cell; Ctrl toggles; Shift range-selects; drag lasso-selects; Esc clears; Ctrl+A selects all 168.
- [ ] Mode tabs "Weekdays" vs "Specific Days": Weekdays applies SET to Mon–Fri uniformly at the chosen hour; Specific Days applies per exact cell.
- [ ] "Clear" wipes the grid (with confirm).
- [ ] Assignments persist to DB; the scheduler picks them up on its next tick.

---

# 10. CLOCK EDITOR (Create / Edit / Duplicate)

**Purpose:** Build a clock = ordered list of content slots.

- [ ] Title reflects mode: "Create New Clock" / "Edit [name]" / "Duplicate (Copy of [name])".
- [ ] Meta strip: Clock Name (required), Comments, Color (6 options), Backup-song filter pill.
- [ ] Element-type tiles: Song / Jingle / Spot / Voice / Sweeper — switching changes the filter panel.
- [ ] Filters per type: Era, Vocal, Year, Priority, BPM (song/spot/voice); sweeper adds a Position picker; jingle = random.
- [ ] Category picker dropdown ("All Songs" or a specific category + count).
- [ ] Filter results card shows match count + avg duration; "Reset All Filters".
- [ ] Action stack: + ADD / ↳ INSERT / ⇄ REPLACE / 🎙 PREPAIR / 🗑 DELETE (act on the clock's slot list).
- [ ] Clock face (circular) visualizes slots colored by type; center shows total duration.
- [ ] OK saves the clock + slots and returns to Auto Schedule; Cancel discards.
- [ ] Duplicate mode saves as a NEW clock (no id reuse).
- [ ] Sub-tabs "Song Tracks" / "Artists" are **STUB** ("coming soon").

---

# 11. PLAYLISTS

## 11a. Playlists (Browse)
- [ ] Search box (debounced) + filter chips All / Manual / Imported / Smart (with counts).
- [ ] "+ New Playlist" opens the create screen; "Import" is a **STUB** toast.
- [ ] 4 stat cards: Total Playlists / Total Tracks / Avg Duration / Scheduled.
- [ ] Playlist cards: cover, type badge, title, track count + duration, last edit, "▶ Preview", "Open →", schedule status pill.
- [ ] Preview plays the first track (with an on-air confirm if Studio is live); "Open →" opens the editor.
- [ ] Selecting a card fills the right detail panel (cover, meta, first ~5 tracks, Edit / Add to Schedule / overflow).
- [ ] "Add to Schedule" adds the playlist to the schedule.
- [ ] Overflow menu (Duplicate/Delete/Export) is a **STUB** toast.

## 11b. Create New Playlist
- [ ] Cancel (with "discard changes?" confirm if dirty) / "✓ Save Playlist".
- [ ] Meta: cover picker, Name (default "Untitled Playlist"), Type dropdown, Color swatches, Tags (comma-split).
- [ ] Left library browser: search (debounced) + category chips + BPM/Year/Sort filters + result count + pagination (10/page).
- [ ] Each library row has "+ ADD" → appends to the queue, button becomes "✓ ADDED".
- [ ] Right queue builder: rows with drag-handle, rank, title/artist, duration, × remove; drag to reorder.
- [ ] Auto-save persists the draft (name/type/color/tags/cover + song order) after edits.

## 11c. Edit Playlist
- [ ] Toolbar: Preview (with on-air confirm), Preview Breaks **(STUB)**, Search, Mic.
- [ ] Tabs: Edit Playlist (active) / Memos / Schedule & Details / Export Playlist.
- [ ] Preview slot shows the selected track; element-type tiles switch the library filter (folder/heart tiles are **STUB**).
- [ ] Action stack: +ADD / ↳INSERT / ⇄REPLACE / 🎙PREPAIR / 🗑DELETE.
- [ ] Playlist table (Name/Title/Run Time); drag rows to reorder.
- [ ] Filter panel: search + Search/Reset + checkboxes + category dropdown.
- [ ] Analyze panel shows the selected track's metadata + a play-history placeholder **(STUB)**.
- [ ] Bottom transport + "✓ Save Playlist" persists name + song order.

---

# 12. AI MAGIC HUB

**Purpose:** Landing for the AI automation suite.

- [ ] Header (logo, clock, station, "Open Studio") + breadcrumb "✦ AI Magic".
- [ ] Hero "✦ AI MAGIC" + subtitle + status pills (ENGINE STANDBY / N/2 MODULES ACTIVE / PREMIUM AUTOMATION).
- [ ] "Spot on the Go" card → routes to the SOTG shell.
- [ ] "Scheduling Automation" card → routes to the rotation-AI hub.
- [ ] Whole card is clickable (same as its "Configure →" button).
- [ ] Roadmap banner lists future modules.

---

# 13. SPOT ON THE GO (SOTG)

## 13a. Shell
- [ ] Breadcrumb "✦ Spot on the Go" + hero + module/scheduled/links pills.
- [ ] 4 step cards: Create Schedule / Assign / Generate Report / Assign API Key — each routes to its screen.
- [ ] Priority ladder strip explains: (1) Paid Spots win, (2) SOTG plays at sharp time (songs fade), (3) Songs are baseline.

## 13b. Step 1 — Create Schedule
- [ ] "Shows saved" + "Total links" pills update live.
- [ ] Form: RJ Name (required), Show Name (required), Days (Daily/Weekdays/Weekends), Time Start, Time End, Color (6), # of Links (1–12, default 9), Description.
- [ ] Changing "# of Links" rebuilds the link-name row (boxes auto-shrink for 10–12) and updates the auto-calc.
- [ ] Auto-calc strip shows envelope hours + link count + ~interval; handles overnight wraparound.
- [ ] "Create Show" validates (RJ, show, valid HH:MM) and saves; "Reset" clears.
- [ ] Saved-shows table: color chip, name, RJ, days, time slot, links, interval, description, EDIT, DELETE.
- [ ] Row click (or EDIT) loads the show into the form for inline editing ("Update Show" + "Cancel Edit").
- [ ] DELETE confirms, then removes the show + its links.

## 13c. Step 2 — Assign
- [ ] Pills: Links Queued / Fired / Conflict / Missed (live).
- [ ] Today / Tomorrow toggle + formatted date label.
- [ ] Left: saved-show cards (color chip, name, RJ, time, "X/Y ready" badge); click selects.
- [ ] Right: links table — #, Link Name, Audio File, Dur, Sharp, Priority, ▶, Status.
- [ ] File button picks audio (mp3/wav/ogg/flac/m4a) → shows "filename · MM:SS".
- [ ] Sharp-time input (HH:MM); **past-time validation:** for today, a past time turns the field red + disables Save; for tomorrow, no check.
- [ ] Priority toggle ⚡ HIGH / ⏱ LOW.
- [ ] ▶ preview plays the file locally (not on air); ■ stops.
- [ ] Status badge: PENDING / READY / FIRED(✓) / MISSED(✕) / CONFLICT(⚠).
- [ ] Save enabled only with file + sharp time + priority (and not an invalid past time); becomes "Update" if the assignment exists.
- [ ] FIRED/MISSED rows are read-only.
- [ ] Auto-suggested sharp times pre-fill spread across the show envelope (operator can override).
- [ ] Legend explains each status (CONFLICT = a paid break occupies that minute).

## 13d. Step 3 — Generate Report
- [ ] Stat pills: Total Drops / Played(✓) / Missed(✕).
- [ ] Date bar: ◀ / date pill (calendar) / ▶ / Today / "Show pending too" toggle.
- [ ] Table: #, Time, Show, RJ, Link, Status, File, Duration.
- [ ] Rows expand to show a 4-line AI summary when one exists (FIRED + ai_summary).
- [ ] "Show pending too" off (default) hides PENDING/READY; a hint shows how many are hidden.
- [ ] "📥 Download PDF" builds the daily PDF, saves it to the reports dir, and opens it.
- [ ] Note shows the auto-save path (23:59 daily) + last-save time.

## 13e. Step 4 — Assign API Key
- [ ] Pills: Done Today / Queue / Errors (live).
- [ ] Provider cards: GEMINI + OPENAI with connection dot (green/red), tagline, hint, Activate/Configure.
- [ ] Switching provider activates it; Configure focuses the key input.
- [ ] Key card: password-masked key input + "👁 Reveal/Hide", Model dropdown (provider-specific), "↻ Test Connection", "Save & Activate".
- [ ] Test Connection pings the provider and reports reachable ✓ or the error.
- [ ] Save & Activate stores the key/model in Settings, reloads the engine, confirms.
- [ ] Live activity log shows today's transcriptions grouped by show, each row with a DONE/PROCESSING/FAILED/SKIPPED/MISSED pill + the 4-line summary when done.
- [ ] "↺ Backfill Missing (50 max)" enqueues past FIRED drops lacking summaries.
- [ ] Privacy note: keys stored locally in radioai.db; audio sent only to the active provider.

---

# 14. SCHEDULING AUTOMATION (Rotation AI)

## 14a. Hub
- [ ] Hero "🤖 SCHEDULING AUTOMATION" + engine/balanced/groups pills.
- [ ] Engine card: big state dot, "ENGINE: ON/OFF/WARMING/ERROR", last/next tick, algorithm line, last-error line.
- [ ] "🔄 Refresh" ticks the engine; "⏹ Stop AI Engine" stops it (obeys the enabled flag).
- [ ] Sister-group cards: group id, category chips (2–5), member count "N/5", total songs, EDIT + UNGROUP.
- [ ] "✚ New Sister Group" opens the sister-group picker (choose 2–5 categories; already-grouped categories are disabled).
- [ ] "Today's AI Actions": Rested / Promoted / Balanced counts + a recent-decisions log.
- [ ] "📅 Review Today's Plan →" opens the Daily Plan Review.

## 14b. Daily Plan Review
- [ ] Hero "📅 TODAY'S PLAN REVIEW" + date + diff legend (🟢 added / 🔴 rested / ⚪ unchanged).
- [ ] Per-clock cards (collapsible): header shows time range + clock + group badge + change summary + chevron.
- [ ] Expanded: LEFT = songs random would pick but AI rested ("WILL BE RESTED"); RIGHT = songs AI picks, promoted ones marked "+ FRESH · from sister".
- [ ] AI reasoning line explains the changes.
- [ ] "✓ Approve & Apply Now" applies the plan; "✕ Discard Plan" reverts to random+separation.
- [ ] Note: if untouched, the plan auto-applies at 5 PM.
- [ ] Empty state when no decisions exist yet.

---

# 15. ROTATION HEALTH

**Purpose:** Day-wise audit of AI rotation decisions per category.

- [ ] Breadcrumb "Rotation Health" + "← Back to Songs".
- [ ] Date pill (calendar, max = today) + refresh + filter dropdown (All / Rested only / Promoted only / Has changes) + "Hide empty cards" toggle.
- [ ] Stat pills: RESTED / PROMOTED / CLOCKS / ERRORS / PLAN STATUS.
- [ ] Category cards (3-col grid) with sections RESTED / PROMOTED OUT / PROMOTED IN; each decision row shows clock, song, parent category + a hover tooltip (7-day + all-time plays + reason).
- [ ] Empty categories show a dashed "no changes today" card (unless hidden).

---

# 16. SETTINGS

## 16a. Settings Hub
- [ ] 3 cards: General / Soundcard / Studio — each opens its sub-page.
- [ ] Header clock + station + "Open Studio".

## 16b. General
- [ ] Station Identity: Name, City, Region, Frequency, Slogan, Contact Email (load/save from DB).
- [ ] File Paths: Music / Recordings / Logs / Exports (Browse folder pickers).
- [ ] "Save Station Settings" saves the left column + refreshes the header station label live.
- [ ] Startup toggles: Start on Windows startup **(persist only, registry deferred)**, Auto-load last session, Start in AUTO MODE, Show splash, Minimize to tray, Check for updates, Send usage stats.
- [ ] Date/Time: Date Format, Time Format, Timezone (default IST), Language (default English India).
- [ ] Backup: interval dropdown + destination picker; "Backup Now" / "Restore" are **STUB** ("coming in v1.1").
- [ ] "Save All Preferences" saves everything + shows a success dialog.

## 16c. Soundcard
- [ ] 5 channel cards: Output 1 Main On-Air (CRITICAL), Output 2 Monitor, Output 3 Cue/Preview, Output 4 Instant Jingles, Input 1 Microphone.
- [ ] Each card: Device dropdown (enumerated Windows devices + "(none)"), Volume slider + "VOL: X%", Channel dropdown, Test/Monitor button **(STUB)**, connection status (green Connected / gray Not assigned).
- [ ] Warning strip: driver/volume changes need a restart.
- [ ] "Save Routing" persists all device/volume/channel selections.
- [ ] "Test ALL" is a **STUB**.

## 16d. Studio
- [ ] Crossfade & Transitions: Crossfade Duration (0–10s), Fade Out Start (0–10s), Fade Curve (Linear/Log/Exp/S-Curve).
- [ ] Next Song Load: load-next dropdown, preload buffer, AutoMix trigger.
- [ ] Playback Fallback: fallback action dropdown + "missing file alert" toggle.
- [ ] "Save Transition Settings" persists the left column.
- [ ] AutoCue: dB threshold slider + scan-mode dropdown.
- [ ] Volume & Levels: Master / Cue / Jingle / Mic sliders.
- [ ] VU Meters: decay speed + peak-hold + clip indicator toggle.
- [ ] "Save Audio Settings" persists the center column.
- [ ] Cue Split radio group (Off / L-cue R-air / L-air R-cue / Blend).
- [ ] Crossfade Preview toggles (show overlap zone / flash mix point) — these drive the Studio waveform overlays.
- [ ] Audio Engine info (buffer/sample-rate/bit-depth/engine) is read-only.
- [ ] "Save Studio Settings" persists cue-split + preview toggles.
- [ ] **Note:** changing crossfade/fade/mix settings here should live-apply to Studio (broadcast from `_apply_studio_settings`).

---

# 17. FINAL LOG

**Purpose:** Per-hour broadcast history for a chosen date.

- [ ] Header shows live date + time + a "Jump To Screen" pill **(decorative in v1)**.
- [ ] Date selectors: Day / Month / Year dropdowns + "🔍 FETCH REPORT".
- [ ] "HOUR SLOTS" sidebar: 24 rows (00:00–01:00 … 23:00–24:00) with per-hour entry counts; clicking loads that hour.
- [ ] Broadcast log table: #, Time, Type (color chip), Title, Artist/Details, Category, Duration, Status(PLAYED).
- [ ] "DOWNLOAD .TXT" saves the hour's log to a file + shows the path.
- [ ] Stats strip: Total Items / Songs / Spots / Jingles / Sweepers / Total Air Time.
- [ ] "PRINT LOG" is a **STUB** ("coming in v1.1").

---

# 18. PLAY HISTORY (per song)

**Purpose:** Analytics for one song.

- [ ] Hero: album-art placeholder + title + artist·album·year + category pill + duration·BPM·energy + TOTAL PLAYS + "since [date added]".
- [ ] 4 stat cards: Plays This Month / This Week / Avg per Week / Last Played (with deltas vs prior period).
- [ ] 12-month bar chart: current month cyan, peak purple, others dim; gridlines + Y-axis + month labels + peak callout.
- [ ] "Recent Plays — Last 5" table: #, Date, Time, Clock, Slot, Operator, Deck.
- [ ] Empty states when no plays logged.

---

# 19. CATEGORY PERFORMANCE

**Purpose:** Analytics for one category.

- [ ] Hero: category tile + name + "N songs · total plays" + category pill + top-song line + TOTAL PLAYS.
- [ ] 4 stat cards: Plays This Month / This Week / Avg per Song / Most Played.
- [ ] 12-month bar chart (same style as Play History).
- [ ] "Songs in Category — ranked by total plays" table: #, Title, Artist, Total Plays, Week, Month, Last Played, Energy·Vocal.
- [ ] Zero-play (dead-inventory) rows are dimmed so they stand out.
- [ ] Empty states when the category has no plays/songs.

---

# 20. THE STITCHER

**Purpose:** Pre-mix a "Coming Up Next" hook montage (opening + song hooks + separators + closing) into one block.

- [ ] Tabs: "Next Songs Hooks" (active) / "Real Time Announcement" **(STUB)** / "News Assembly" **(STUB)**.
- [ ] Module Enabled card toggles on/off.
- [ ] 4 audio-file rows (Opening / Separator / Closing / Fallback): each with a path field, Browse, and ▶ Preview (plays if the file exists, else "file missing").
- [ ] Hook Settings: Min hooks required (0–10), Max hooks (1–20), Hook preview duration (1–30s), Trigger mode (Break reference / Every N songs / Top of hour / Manual).
- [ ] "✓ Save Configuration" persists all paths + settings (validates min ≤ max).
- [ ] Assembly-flow preview shows 5 tiles (Opening + 3 hooks + Closing) with a total-duration estimate that updates live.
- [ ] Sample-playlist preview shows ~5 upcoming songs with their hook range or "No hook set ⚠" + a "Set Hook" button.
- [ ] "▶ Preview Full Stitcher Output" assembles + plays the sequence (uses Fallback audio when not enough hooks; warns on missing files).
- [ ] "↺ Reset to Default Settings" restores defaults (confirm first).
- [ ] AI Insights panel: Times Used Today / Retention are **placeholders**; "Songs Without Hooks" is a real computed count; recommendation cards are static text.

---

## APPENDIX — Cross-cutting behaviors (apply to most screens)

- [ ] Every screen's header clock updates every second.
- [ ] Every screen's station-name label reflects Settings.station_display live.
- [ ] Breadcrumb links + top-nav route correctly and highlight the active location.
- [ ] Confirm/warning/info dialogs use the premium themed dialog, centered on the parent window.
- [ ] Required fields block save when empty; save shows a success confirmation.
- [ ] Tables scroll smoothly; rows zebra-stripe; selection highlights.
- [ ] Any button marked **(STUB)** should show a "coming soon" message and do nothing else — this is intentional, not a bug (operator's "lock unbuilt features" directive).

---

*End of FEATURE_SPEC.md — cross-verify each `[ ]` against the running app.*

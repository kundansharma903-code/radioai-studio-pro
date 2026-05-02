# RadioAI Studio Pro — Complete Design Document
**Version:** 1.0.0  
**Design Tool:** Figma  
**File Key:** `7oN9K61g94wKx3nu44KKDF`  
**URL:** https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF  
**Theme:** Dark Premium — AI Native Radio Automation

---

## Table of Contents
1. [Design Philosophy](#1-design-philosophy)
2. [Color System](#2-color-system)
3. [Typography](#3-typography)
4. [Spacing & Layout](#4-spacing--layout)
5. [Component Library](#5-component-library)
6. [Screen Designs](#6-screen-designs)
7. [Navigation System](#7-navigation-system)
8. [Animation & Motion](#8-animation--motion)
9. [Status System](#9-status-system)
10. [Iconography](#10-iconography)
11. [Responsive Behavior](#11-responsive-behavior)
12. [Design Decisions Log](#12-design-decisions-log)

---

## 1. Design Philosophy

### Core Principles

```
1. INFORMATION FIRST
   Radio operators need data instantly.
   No hunting, no clicking deep menus.
   Critical info visible at a glance.

2. PROFESSIONAL DARK THEME
   Radio stations run 24/7 in dimly lit rooms.
   Dark theme reduces eye strain.
   High contrast for quick scanning.

3. AI FEELS ALIVE
   AI features must look intelligent.
   Animations convey "thinking" state.
   Real data — never static mockups.

4. JAZLER DNA — RADIOAI SOUL
   Familiar layout for existing Jazler users.
   But elevated — premium, modern, AI-powered.
   Same mental model, better execution.

5. COLOR AS COMMUNICATION
   Every color has ONE meaning, always.
   Green = Active/Good
   Amber = Warning/Caution
   Red = Error/Exceeded
   Cyan = Songs/Morning
   Purple = AI/Settings
```

### Design Inspiration
```
Primary: Jazler SOHO (radio software standard)
Secondary: Spotify (music visualization)
Tertiary: Trading terminals (data density)
AI aesthetic: Neural network visualizations
```

---

## 2. Color System

### Background Palette
```css
--bg-deepest:    #04050f;  /* Page background */
--bg-dark:       #070812;  /* Screen background */
--bg-panel:      #0a0b18;  /* Panel background */
--bg-card:       #0e1020;  /* Card background */
--bg-elevated:   #131626;  /* Elevated elements */
--bg-interactive:#1c1f38;  /* Hover states */
```

### Border Colors
```css
--border-subtle:  #1c1f38;  /* Subtle dividers */
--border-medium:  #252840;  /* Medium emphasis */
--border-strong:  #454d6d;  /* Strong borders */
```

### Text Colors
```css
--text-primary:   #f1f5ff;  /* Main content */
--text-secondary: #8891b8;  /* Supporting text */
--text-muted:     #454d6d;  /* Labels, captions */
--text-disabled:  #252840;  /* Disabled state */
```

### Accent Colors — Semantic Mapping
```css
/* CYAN — Songs, Morning Drive, Info */
--cyan-500:  #06b6d4;
--cyan-bg:   #083344;
--cyan-glow: rgba(6, 182, 212, 0.15);

/* PURPLE — AI, Settings, Magic */
--purple-500: #8b5cf6;
--purple-400: #a78bfa;
--purple-bg:  #1e1535;
--purple-glow: rgba(139, 92, 246, 0.15);

/* GREEN — Active, Done, Success */
--green-500: #10b981;
--green-bg:  #052e16;
--green-glow: rgba(16, 185, 129, 0.15);

/* AMBER — Warning, Afternoon, Caution */
--amber-500: #f59e0b;
--amber-bg:  #2d1a00;
--amber-glow: rgba(245, 158, 11, 0.15);

/* RED — Error, Late Night, Exceeded */
--red-500:   #f43f5e;
--red-bg:    #1f0a12;
--red-glow:  rgba(244, 63, 94, 0.15);

/* PINK — Weekend, Special */
--pink-500:  #ec4899;
--pink-bg:   #2d0a1e;
```

### Clock/Time Slot Colors
```css
Night Rotation:  #252840 (dark muted)
Morning Drive:   #06b6d4 (cyan)
Daytime Hit:     #8b5cf6 (purple)
Afternoon Mix:   #f59e0b (amber)
Evening Drive:   #10b981 (green)
Late Night:      #f43f5e (red)
Weekend Morning: #ec4899 (pink)
```

### Status Colors
```css
/* Broadcast Status */
ON AIR:      #f43f5e (red — urgency)
LIVE:        #10b981 (green — active)
LOADED:      #06b6d4 (cyan — ready)
QUEUED:      #454d6d (muted — waiting)
BREAK:       #f59e0b (amber — ad break)
OVERPLAY:    #f43f5e (red — warning)

/* AI Status */
AI ACTIVE:   #10b981 (green)
AI WARNING:  #f59e0b (amber)
AI ERROR:    #f43f5e (red)
ENGINE RUNNING: #10b981 (green pulse)
```

---

## 3. Typography

### Font Stack
```css
/* UI Text — All interface elements */
font-family: 'Inter', -apple-system, sans-serif;

/* Monospace — Numbers, times, codes */
font-family: 'Roboto Mono', 'Courier New', monospace;
```

### Type Scale
```css
/* Display — Clock, major numbers */
.text-display {
  font-family: 'Roboto Mono', monospace;
  font-size: 32px;
  font-weight: 700;
  color: #f1f5ff;
  letter-spacing: -0.5px;
}

/* Heading — Section titles */
.text-heading {
  font-family: 'Inter', sans-serif;
  font-size: 18-28px;
  font-weight: 700;
  color: #f1f5ff;
}

/* Sub-heading — Card titles */
.text-subheading {
  font-family: 'Inter', sans-serif;
  font-size: 14px;
  font-weight: 600;
  color: #f1f5ff;
}

/* Body — Regular content */
.text-body {
  font-family: 'Inter', sans-serif;
  font-size: 11-12px;
  font-weight: 400;
  color: #8891b8;
}

/* Label — Small labels */
.text-label {
  font-family: 'Inter', sans-serif;
  font-size: 9-10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: #454d6d;
}

/* Mono — Times, durations, counts */
.text-mono {
  font-family: 'Roboto Mono', monospace;
  font-size: 10-14px;
  font-weight: 400;
  color: #8891b8;
}

/* Mono Bold — Highlighted numbers */
.text-mono-bold {
  font-family: 'Roboto Mono', monospace;
  font-size: 14-24px;
  font-weight: 700;
  color: accent-color;
}
```

---

## 4. Spacing & Layout

### Grid System
```
Window Size: 1440 × 900px (fixed)
Platform: Windows 10/11 desktop only

Header Height:     86px
Status Bar Height: 36px
Content Area:      900 - 86 - 36 = 778px
```

### Spacing Scale
```css
--space-xs:  4px;
--space-sm:  8px;
--space-md:  12px;
--space-lg:  16px;
--space-xl:  20px;
--space-2xl: 24px;
--space-3xl: 32px;
```

### Panel Widths
```
Left sidebar (Libraries):  170px
Left sidebar (Clock Ed):   300px
Left sidebar (Schedule):   240px
Right panel (Spots):       ~660px (W - other panels)
Content area:              Remaining space
```

### Border Radius
```css
--radius-sm:   4px;   /* Tags, badges */
--radius-md:   6-8px; /* Buttons, inputs */
--radius-lg:   10px;  /* Cards, panels */
--radius-xl:   16px;  /* Major sections */
--radius-full: 9999px; /* Pills */
```

---

## 5. Component Library

### 5.1 Header (Global)
```
Height: 86px
Background: #0e1020
Bottom border: 1px #1c1f38

LEFT:
- Logo area (52×52px, purple glow)
  - 5 equalizer bars (animated in studio)
  - "RadioAI" 18px Bold
  - "STUDIO PRO" 9px SemiBold purple
  - "BROADCAST AUTOMATION" 8px muted

CENTER-LEFT:
- Breadcrumb navigation
  "Control Panel ▸ Libraries ▸ Songs"
- Active tab highlighted:
  Background: accent-color 8% opacity
  Bottom border: 4px accent-color
  Text: accent-color SemiBold

CENTER-RIGHT:
- Live clock: 32px Roboto Mono Bold
  "14:50:54" 
- Date: 9px Inter Regular muted

RIGHT:
- Station badge (160×54px)
  Left border: 3px green
  "ACTIVE STATION" label
  Station name 14px Bold
  Location 8px muted
  
- Open Studio button (160×50px)
  Background: accent-color
  "▶  Open Studio" white Bold
  Radius: 10px
```

### 5.2 Status Bar (Global)
```
Height: 36px
Position: Bottom of screen
Background: #0e1020
Top border: 1px #1c1f38

LEFT: Status badges (96px each)
  Background: colored bg
  Left border: 2px accent-color
  "⬤ Label" 9px SemiBold
  
  Examples:
  ● AUTO MODE (purple)
  ● AI Active (green)
  ● ON AIR (red)
  ● 7 Clocks (cyan)
  ⚡ SOHO Auto (purple)

RIGHT:
  Version info (muted)
  Settings button (purple)
```

### 5.3 Buttons

#### Primary Button
```css
.btn-primary {
  height: 28-32px;
  padding: 0 16px;
  background: accent-color;
  border-radius: 8px;
  font: 11px Inter SemiBold;
  color: white;
  border: none;
}
```

#### Accent Button (with left border)
```css
.btn-accent {
  height: 28px;
  padding: 0 12px;
  background: accent-bg;
  border-left: 2px solid accent-color;
  border-radius: 6px;
  font: 10px Inter SemiBold;
  color: accent-color;
}
```

#### Danger Button
```css
.btn-danger {
  background: #1f0a12;
  border-left: 2px solid #f43f5e;
  color: #f43f5e;
}
```

#### Action Buttons Row (Clock Editor)
```
Change (cyan) | Delete (red) | Add (green) | 
Insert (amber) | Move Up (purple) | Move Down (purple) |
AI Optimise (purple glow) | Preview (green) |
Validate (cyan) | Save Clock (green)

Each: height 28px, dynamic width, 
left border 2px accent, radius 6px
```

### 5.4 Badges & Tags
```css
/* Status badge */
.badge {
  display: inline-flex;
  align-items: center;
  height: 18-24px;
  padding: 0 8px;
  border-radius: 9999px;
  font: 8-9px Inter SemiBold;
  border-left: 2px solid color;
  background: color-bg;
  color: color;
}

/* Category tag (colored pill) */
.tag-category {
  height: 18px;
  padding: 0 8px;
  border-radius: 4px;
  background: category-color 20% opacity;
  font: 8px Inter SemiBold;
  color: category-color;
}

/* Priority tag */
High:   green bg + text
Medium: amber bg + text
Low:    cyan bg + text
Always: blue bg + text
```

### 5.5 Input Fields
```css
.input {
  height: 26-28px;
  padding: 0 10px;
  background: #0a0c18;
  border: none;
  border-left: 2px solid accent-color;
  border-radius: 5px;
  font: 10-11px Inter Regular;
  color: #f1f5ff;
}

.input:focus {
  border-left-color: accent-color;
  background: #131626;
  outline: none;
}
```

### 5.6 Dropdowns
```css
.dropdown {
  height: 22-26px;
  padding: 0 10px;
  background: #131626;
  border-radius: 5px;
  font: 9-10px Inter Regular;
  color: #8891b8;
  /* ▾ arrow right-aligned */
}
```

### 5.7 Table / List Rows
```css
/* Alternating rows */
.row-even { background: #0d0f1e; }
.row-odd  { background: #0a0c18; }

/* Selected/Active row */
.row-active {
  background: accent-color 10% opacity;
  border-left: 3px solid accent-color;
  color: #f1f5ff;
  font-weight: 600;
}

/* Row height */
Standard list:    36px
Compact list:     28px
Detailed list:    52-58px (with subtitle)

/* Row divider */
border-bottom: 1px solid #1c1f38 30% opacity;
```

### 5.8 Cards
```css
.card {
  background: #0a0b18;
  border-radius: 12-16px;
  /* Top accent border */
  border-top: 3px solid accent-color;
  overflow: hidden;
}

.card-glow {
  /* Subtle color tint */
  background: linear-gradient(
    135deg,
    accent-color 3% opacity,
    transparent
  );
}
```

### 5.9 Progress Bars
```css
.progress-bar {
  height: 6-8px;
  background: #131626;
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: accent-color 80% opacity;
  border-radius: 4px;
  transition: width 0.3s ease;
}
```

### 5.10 Pie/Donut Chart
```javascript
// Canvas-based donut chart
// Outer radius: 70-80px
// Inner radius: 42-50px (donut hole)
// Center text: total minutes
// Segment stroke: 2px #070812 separator
// Colors: cyan, amber, purple, green

// Segments:
Songs:    #06b6d4 (75%)
Ads:      #f59e0b (13%)  
Jingles:  #a78bfa (7%)
Sweepers: #10b981 (5%)
```

### 5.11 Timeline Component
```
Vertical timeline (Last Run Timeline):

● Dot (8px) ← colored per status
│ Line (2px, 32px tall) ← colored, 30% opacity
  
Left:  Timestamp (Roboto Mono, 8px, muted)
Right: Checkmark ✓ (green) or ⚠ (amber)
Title: 10px Inter SemiBold (white or amber)
Detail: 8px Inter Regular (muted)

Animation: stepIn keyframe
  opacity: 0→1, translateX(-20px→0)
  Delay: i × 300ms
```

---

## 6. Screen Designs

### 6.1 Studio Screen
**Node:** Main studio view  
**Layout:** Full-width, complex multi-panel

```
┌──────────────────────────────────────────────┐
│ HEADER (86px)                                │
├──────────┬───────────────────────┬───────────┤
│ DECK A   │    CENTER CONTROL     │ DECK B    │
│ (420px)  │      (360px)          │ (420px)   │
│          │   AUTO MIX badge      │           │
│ Artist   │   NEXT BREAK timer    │ Artist    │
│ Title    │   CROSSFADER          │ Title     │
│ Waveform │   MASTER vol          │ Waveform  │
│ Timer    │   [MIX NOW →]         │ Timer     │
│ BPM/Key  │   PREV PLAYED         │ BPM/Key   │
│ [CUE]    │                       │ [CUE]     │
│ [PLAY]   │                       │ [LOAD]    │
│ [FADE]   │                       │           │
├──────────┴───────────────────────┴───────────┤
│ JINGLE PADS RIGHT (N25-N30) — 240px wide     │
├──────────────────────────────────────────────┤
│ PLAYLIST QUEUE (full width, scrollable)      │
│ AI | # | Artist | Title | Dur | Cat | Time  │
│ Status | AI Insight per row                  │
├──────────────────────────────────────────────┤
│ STATUS BAR (36px)                            │
└──────────────────────────────────────────────┘
```

**Color Logic in Queue:**
```
Row colors by AI Insight:
🔴 Overplay alert → red left border
🟡 Warning → amber left border  
🟢 AI Pick → green left border
⚪ Normal → no border

Status badges:
▶ PLAYING  → green
● LOADED   → cyan
○ Queued   → muted
🔴 BREAK   → amber
```

---

### 6.2 Songs Library
**Node:** 12:2 | Canvas X: 1500

```
┌──────────────────────────────────────────────┐
│ HEADER                                       │
├───────────┬──────────────────┬───────────────┤
│ LEFT      │ CENTER           │ RIGHT         │
│ SIDEBAR   │ SONG LIST        │ DETAIL PANEL  │
│ (170px)   │ (scrollable)     │ (tabs)        │
│           │                  │               │
│ + Add New │ # Artist  Title  │ Broadcast     │
│ Mass Imp  │   Duration Cat   │ Analytics     │
│ × Delete  │                  │               │
│           │ [Search bar]     │ AI Insights   │
│ SEARCH    │ [Filter row]     │               │
│           │                  │ Song Details  │
│ Filters:  │ Rows (36px each) │               │
│ Sound Code│ Alt bg colors    │ Sep Settings  │
│ Popularity│ Selected = cyan  │               │
│ Era       │ border+bg tint   │               │
│ Year      │                  │               │
│ Priorities│                  │               │
│ Properties│                  │               │
│ Vocal     │                  │               │
│ Hook      │                  │               │
│ Frozen    │                  │               │
│ BPM range │                  │               │
├───────────┴──────────────────┴───────────────┤
│ BOTTOM TOOLBAR                               │
│ Edit Song | Mass Change | Export | Delete    │
│ Normalize | + Add Song                       │
└──────────────────────────────────────────────┘
```

**Right Panel Tabs:**
```
[Broadcast Analytics] [All Insights ✨] [Song Details]

Broadcast Analytics:
- Bar chart: plays per day (30 days)
- Play Statistics cards:
  Total Plays | This Month | Last Played | Avg/Day
- AI INSIGHTS section (purple):
  ⚠ Overplay Alert (red card)
  ✓ Good Energy Match (green card)
  ♦ Similar Songs (blue card)
  ○ Rotation Health (purple card)
- Song Separation Settings
```

---

### 6.3 Audio Cue Editor
**Node:** Embedded dialog | Canvas: 3000, y=830

```
┌─────────────────────────────────────────────┐
│ AUDIO CUE EDITOR                            │
│ "Set mix points, hooks, fade settings"      │
│ [Song file path]              [...] [Edit]  │
├─────────────────────────────────────────────┤
│ WAVEFORM (full width, 140px tall)           │
│                                             │
│ ↓START  ↓INTRO  ↓HOOK IN ↓HOOK OUT        │
│ [████████████████████████████████████]     │
│         ↓OUTRO         ↓MIX POINT          │
│                                             │
│ Timeline: 0:00  0:47  1:04  2:21  3:08...  │
├─────┬──────┬───────┬────────┬───────┬──────┤
│FadeI│START │ INTRO │ HOOK IN│HOOKOUT│OUTRO │
│     │24.7s │  0.0s │  63.6s │115.1s │197.7s│
│sldr │<< >> │ << >> │  << >> │ << >> │ << >>│
│     │PREVW │ PREVW │  PREVW │ PREVW │ PREVW│
│     │Reset │ Reset │  Reset │ Reset │ Reset│
│     │0.1s  │ 0.1s  │  0.1s  │ 0.1s  │ 0.1s │
├─────┴──────┴───────┴────────┴───────┴──────┤
│                         MIX POINT │ FadeOut│
│                            260.3s │  sldr  │
│                         << >>     │        │
│                         PREVIEW   │        │
│                         Reset     │        │
├─────────────────────────────────────────────┤
│[× Variable Length] [↺ Reset] [● AutoCue]   │
│                          Volume: 100% [Norm]│
│                                    [32-bit] │
├─────────────────────────────────────────────┤
│        [← Song Info] [Cancel] [✓ Save]     │
└─────────────────────────────────────────────┘
```

**Marker Colors:**
```
START:     #10b981 (green)
INTRO:     #06b6d4 (cyan)
HOOK IN:   #06b6d4 (cyan)
HOOK OUT:  #06b6d4 (cyan)
OUTRO:     #f59e0b (amber)
MIX POINT: #f43f5e (red)
```

---

### 6.4 Spots & Commercials
**Node:** 35:2 | Canvas X: 4900

```
┌──────────────────────────────────────────────────┐
│ HEADER — $ Spots & Commercials                   │
├──────────┬─────────────────────┬─────────────────┤
│ LEFT     │ CENTER              │ RIGHT           │
│ (170px)  │ Campaign List       │ AI MONITOR      │
│          │                     │ (scrollable)    │
│ + Add    │ [Campaign Name]     │                 │
│ Edit Brk │ [Spots][Cat][Pri]   │ THIS HOUR USAGE │
│ Brk Set  │ [Start][End Date]   │ 8/15 min ✅     │
│ × Delete │                     │                 │
│          │ Rows (36px each)    │ PIE CHART       │
│ FILTERS  │ Selected = green    │ Songs/Ads/etc   │
│ All Camp │                     │                 │
│ Active   │                     │ HOURLY TREND    │
│ Category │                     │ 16-bar chart    │
│ Priority │                     │                 │
│ Day      │                     │ CLIENT ROTATION │
│          │                     │ High→Low table  │
│ REPORTS  │                     │                 │
│ Actual   │                     │ AI INSIGHT bar  │
│ Schedule │                     │                 │
│ Daily    │                     │                 │
│ Duration │                     │                 │
│ Traffic  │                     │                 │
├──────────┴─────────────────────┴─────────────────┤
│ NOW AIRING: [Campaign] ████████████ 0:12/0:30    │
│                                      AutoPlay ON  │
└──────────────────────────────────────────────────┘
```

**Client Rotation Table:**
```
Columns: # | CLIENT/CAMPAIGN | ROTATIONS | MIN/HOUR | 7-DAY | STATUS

Status colors:
HIGH   (>3 min/hr):  red badge
MEDIUM (1-3 min/hr): cyan badge  
LOW    (<1 min/hr):  green badge

Row height: 58px (name + sub + bar)
Color bar shows rotation %
```

---

### 6.5 Scheduling Screen
**Node:** 50:2

```
┌──────────────────────────────────────────────┐
│ HEADER                                       │
├──────────────────────────────────────────────┤
│ Scheduling                        LIVE 14:50 │
│ Plan your broadcast week                     │
│                                              │
│ [7 Clocks Built] [Log Ready] [⚡ SOHO Auto]  │
│                                              │
│ ┌────────────── AI DAILY SCHEDULER ─────────┐│
│ │ ✅ Today's scheduling done • 7 warnings   ││
│ │ Generated: 12:03 AM • 247 songs           ││
│ │ • Morning Vibes: only 8 songs             ││
│ │                    [View Schedule →]      ││
│ └───────────────────────────────────────────┘│
│                                              │
│ THIS WEEK — CLOCK ASSIGNMENTS                │
│ [+ New Clock] [▶ Gen Log] [⚡ Force] [View] │
│                                              │
│ ┌──────┬──────┬──────┬──────┬──────┬──────┐ │
│ │      │ MON  │ TUE  │ WED  │ SAT  │ SUN  │ │
│ │00-06 │Night │Night │Night │Night │Night │ │
│ │06-10 │Morn  │Morn  │Morn  │WkMrn │WkMrn │ │
│ │10-14 │Day   │Day   │Day   │Day   │Day   │ │
│ │14-18 │Aftnn │Aftnn │Aftnn │Aftnn │Aftnn │ │
│ │18-22 │Evng  │Evng  │Evng  │Evng  │Evng  │ │
│ │22-00 │Late  │Late  │Late  │Late  │Late  │ │
│ └──────┴──────┴──────┴──────┴──────┴──────┘ │
│                                              │
│ [Clock Editor] [Final Log] [Force Clocks]   │
│ [Playlists] [Log Viewer] [Rebroadcast] [RDS]│
│                                              │
│ SONG SEPARATION RULES                        │
│ Same Artist: 2h | Same Song: 7d | ...       │
│                                              │
│ ✦ AI SCHEDULING INSIGHT ──────── Fix Now →  │
└──────────────────────────────────────────────┘
```

**AI Scheduler Card States:**
```
Done (green border):
  ✅ Background: dark green tint
  Border: 3px left green

Warning (amber border):
  ⚠️ Background: dark amber tint
  Border: 3px left amber

Failed (red border):
  🔴 Background: dark red tint
  Border: 3px left red
```

---

### 6.6 Main Auto Schedule
**Node:** 161:2

```
┌──────────────────────────────────────────────┐
│ HEADER — breadcrumb: ...▸ Main Auto Schedule │
├───────────┬──────────────────────────────────┤
│ LEFT (240)│ Clocks Schedule                  │
│           │ "each cell = 1 hour of broadcast" │
│ AVAILABLE │ [Weekdays] [Specific Days]  ClearAll│
│ CLOCKS    │                                  │
│           │ ┌──────┬─────┬─────┬─────┬─────┐│
│ ● Morning │ │ HOUR │ MON │ TUE │ SAT │ SUN ││
│ ● Daytime │ │00:00 │Night│Night│Night│Night││
│ ● Aftnoon │ │01:00 │Night│Night│Night│Night││
│ ● Evening │ │...   │ ... │ ... │ ... │ ... ││
│ ● Late Nt │ │06:00 │Morn │Morn │WkMrn│WkMrn││
│ ● Night   │ │...24 rows total...            ││
│ ● Weekend │ └──────┴─────┴─────┴─────┴─────┘│
│           │ Each cell: color fill + name text │
│           │ Selected: highlighted border      │
│           │ Today column: cyan tint           │
│ [SET ▶▶]  │                                  │
│ (RED btn) │                                  │
│           │                                  │
│ Edit Clock│                                  │
│ Duplicate │                                  │
│ Auto Prog │                                  │
│ Delete    │                                  │
└───────────┴──────────────────────────────────┘
```

**Grid Cell Design:**
```css
.grid-cell {
  /* Color fill */
  background: clock-color 12% opacity;
  border-left: 2px solid clock-color 80%;
  
  /* Text */
  font: 8px Inter Regular clock-color;
  padding: 7px 8px;
  
  /* Hover */
  background: clock-color 20% opacity;
  cursor: pointer;
  
  /* Selected */
  outline: 2px solid clock-color;
  background: clock-color 25% opacity;
}
```

---

### 6.7 Clock Editor
**Node:** 165:2 | Canvas X: 15100

```
┌──────────────────────────────────────────────────────┐
│ HEADER — breadcrumb: ...▸ Clock Editor               │
├──────────────┬──────────────────────────┬────────────┤
│ LEFT (300px) │ CENTER                   │ RIGHT(280) │
│ FILTER PANEL │ SLOT EDITOR              │ PROPERTIES │
│              │                          │            │
│ [Songs][Jngl]│ [Clock Name field]       │ EDITING:   │
│ [Spots][Swpr]│ [Comments field]         │ Slot 1-Song│
│ [Events]     │ ━━━ Stats ━━━━━━━━━━━━━ │            │
│              │ Songs:15 Brks:3 Total:59 │ Slot Type  │
│ Category     │                          │ [Song ▾]   │
│ Spec Song    │ [Change][Delete][Add]    │            │
│ Spec Artist  │ [Insert][↑][↓][AI Opt]  │ Category   │
│              │ [Preview][Validate][Save]│ [Hot Cur ▾]│
│ CATEGORIES:  │                          │            │
│ [All ▾]      │ ┌─────────────────────┐ │ Energy     │
│ Category 2   │ │#│TYPE│TIME│DESC│CAT │ │ [High ▾]   │
│ Category 3   │ │1│Song│0→4 │Song│HotC│ │            │
│ Properties   │ │2│Swpr│4→4 │Swpr│Stn │ │ Vocal      │
│ Vocal Type   │ │3│Song│4→8 │Song│HotC│ │ [Any ▾]    │
│              │ │4│Jngl│8→8 │Jngl│StnI│ │            │
│ SCALES:      │ │5│Swpr│8→8 │Swpr│Stn │ │ Priority   │
│ Time Period  │ │...             ...  │ │ [Normal ▾] │
│ Priority     │ └─────────────────────┘ │            │
│ BPM          │                          │ Separation │
│              │                          │[UseDefault▾│
│ Songs: 1,962 │                          │            │
│              │                          │[✔ Apply]   │
│ [Reset][Prev]│                          │[✕ Remove]  │
│              │                          │            │
│              │                          │ OVERVIEW   │
│              │                          │ Songs:15   │
│              │                          │ Brks:3     │
│              │                          │ Total:59:45│
│              │                          │            │
│              │                          │ CAT SLOTS  │
│              │                          │ HotCur ██7 │
│              │                          │ Classic ██3│
└──────────────┴──────────────────────────┴────────────┘
```

**Sweepers Tab Special:**
```
SWEEPER WILL BE PLACED:
┌─────────────────────────┐
│ Start of Song      ▾    │  ← Prominent dropdown
└─────────────────────────┘
Options:
• BEFORE INTRO
• START OF SONG  
• BEFORE END
• BRIDGE AT END
• INDEPENDENT
• CUSTOM POSITION

● Random Sweeper based on category
○ Specific Sweeper

CATEGORY: [All ▾]

LIST:
Title                    Duration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KISS Open Bridge         0:08
RR sweeper New           0:11
SW 01 Fast               0:09
Shekhawati hook          0:03
```

---

### 6.8 AI Magic Tab
**Node:** 170:2 | Canvas X: 16600

```
┌─────────────────────────────────────────────────────────┐
│ HEADER — active: ✦ AI Magic (purple)                    │
├─────────────────────────────────────────────────────────┤
│ ✦ AI MAGIC ENGINE                                       │
│ Real-time view of how AI manages your radio             │
│ [● ENGINE RUNNING] [✦ LAST RUN: 12:03] [NEXT: 5h 4m]   │
├──────────────────┬──────────────────┬───────────────────┤
│ LEFT (480px)     │ CENTER (400px)   │ RIGHT (~560px)    │
│ AI ENGINE        │ LAST RUN         │ STATS + HEALTH    │
│                  │ TIMELINE         │                   │
│ "AI SCHEDULING   │                  │ ┌────┐ ┌────┐    │
│  ENGINE v2.0"    │ 00:00:00 ● Trig  │ │176 │ │ 7  │    │
│                  │ 00:00:01 ● Grid  │ │Song│ │Warn│    │
│ [3D ORBITAL      │ 00:00:02 ● Hist  │ └────┘ └────┘    │
│  BRAIN ANIMATION]│ 00:00:04 ⚠ Cat  │ ┌────┐ ┌────┐    │
│                  │ 00:00:06 ● Rules │ │2/8 │ │12:0│    │
│  Rings rotating  │ 00:00:08 ● Gen  │ │Cat │ │Next│    │
│  Planets orbit   │ 00:00:11 ⚠ Warn │ └────┘ └────┘    │
│  Core pulses     │ 00:00:12 ● Log  │                   │
│                  │ 00:00:13 ● Done │ CATEGORY HEALTH   │
│                  │                  │ Morning ████ ✅   │
│ ENGINE PARTS:    │                  │ Hot Cur ░ 🔴      │
│ ┌──────────────┐ │                  │ Classics ░ 🔴     │
│ │History Scan  │ │                  │ Pop     ░ 🔴      │
│ │● ACTIVE      │ │                  │ Evening ░ 🔴      │
│ ├──────────────┤ │                  │                   │
│ │Rule Engine   │ │                  │ ✦ AI suggestion   │
│ │● ACTIVE      │ │                  │ "Add 50+ songs"   │
│ ├──────────────┤ │                  │                   │
│ │Song Picker   │ │                  │                   │
│ │● ACTIVE      │ │                  │                   │
│ ├──────────────┤ │                  │                   │
│ │Warning Sys   │ │                  │                   │
│ │⚠ 7 WARNS    │ │                  │                   │
│ ├──────────────┤ │                  │                   │
│ │Log Writer    │ │                  │                   │
│ │● DONE        │ │                  │                   │
│ ├──────────────┤ │                  │                   │
│ │Midnight Timer│ │                  │                   │
│ │○ WAITING     │ │                  │                   │
│ └──────────────┘ │                  │                   │
├──────────────────┴──────────────────┴───────────────────┤
│ AI DECISION LOG                                         │
│ 00:00:06 ● "Skipped Kesariya — played 2 days ago"      │
│ 00:00:06 ● "Selected Raataan — 9 days fresh (92%)"     │
│ 00:00:07 ● "Artist separation: Arijit → next 12:04+"   │
│ 00:00:08 ⚠ "Hot Currents 0 songs — fallback used"     │
└─────────────────────────────────────────────────────────┘
```

---

## 7. Navigation System

### Primary Navigation (Header)
```
Control Panel → Libraries → [Active Screen]

Tab Items:
- Control Panel (always first)
- Libraries (or Scheduling, Settings, AI Magic)
- Current Screen Name (highlighted)

Active tab:
  Background: accent-color 8% opacity
  Bottom border: 4px solid accent-color
  Text: accent-color SemiBold 14px
  
Inactive:
  Text: #454d6d Regular 13px
  No background
```

### Secondary Navigation (Within Screens)
```
Spots Screen: 
  [Campaign Details] [Break Schedule] [Play Reports]
  
Songs Library:
  [Broadcast Analytics] [All Insights ✨] [Song Details]

Clock Editor Left:
  [Songs] [Jingles] [Spots] [Sweepers] [Events]
  Sub: [Category] [Specific Song] [Specific Artist]

Main Auto Schedule:
  [Weekdays] [Specific Days]

Client Rotation:
  [This Hour] [Last 7 Days]
```

### "Open Studio" Button
```
Present in ALL screen headers (top right)
Background: purple (#8b5cf6) OR green
Text: "▶  Open Studio" white Bold
Action: Switch to Studio tab (NEVER reload)
Result: Studio continues playing seamlessly
```

---

## 8. Animation & Motion

### AI Brain Animation (CSS Only)
```css
/* Ring 1 — Cyan, horizontal orbit */
@keyframes orbit1 {
  from { transform: rotateZ(0deg) rotateX(75deg); }
  to   { transform: rotateZ(360deg) rotateX(75deg); }
}
animation: orbit1 6s linear infinite;

/* Ring 2 — Purple, tilted orbit */
@keyframes orbit2 {
  from { transform: rotateZ(0deg) rotateX(45deg) rotateY(20deg); }
  to   { transform: rotateZ(-360deg) rotateX(45deg) rotateY(20deg); }
}
animation: orbit2 8s linear infinite;

/* Ring 3 — Light purple, vertical */
@keyframes orbit3 {
  from { transform: rotateZ(0deg) rotateY(60deg); }
  to   { transform: rotateZ(360deg) rotateY(60deg); }
}
animation: orbit3 4s linear infinite;

/* Core pulse */
@keyframes corePulse {
  0%,100% {
    box-shadow: 0 0 20px #7c3aed,
                0 0 40px #7c3aed44;
    transform: scale(1);
  }
  50% {
    box-shadow: 0 0 30px #a78bfa,
                0 0 60px #7c3aed66;
    transform: scale(1.05);
  }
}
animation: corePulse 3s ease-in-out infinite;

/* Planet orbit */
@keyframes planet1 {
  from { transform: rotate(0deg) translateX(80px); }
  to   { transform: rotate(360deg) translateX(80px); }
}
/* 6 planets with different start angles (-0s, -1s, -2s...) */
```

### Timeline Step Animation
```css
@keyframes stepIn {
  from { opacity: 0; transform: translateX(-20px); }
  to   { opacity: 1; transform: translateX(0); }
}

/* Applied per step with delay */
.timeline-step:nth-child(n) {
  animation: stepIn 0.3s ease forwards;
  animation-delay: calc(n * 300ms);
  opacity: 0; /* starts hidden */
}
```

### Status Dot Pulse
```css
@keyframes statusPulse {
  0%,100% { opacity: 1; transform: scale(1); }
  50%     { opacity: 0.5; transform: scale(0.8); }
}
.status-dot-active {
  animation: statusPulse 2s ease-in-out infinite;
}
```

### Waveform Bars (Studio Equalizer Logo)
```css
@keyframes barPulse {
  0%,100% { height: 6px; }
  50%     { height: var(--bar-height); }
}
/* 5 bars with staggered delays */
```

### Countdown Timer
```javascript
// Live countdown to midnight
function updateCountdown() {
  const now = new Date()
  const midnight = new Date()
  midnight.setHours(24, 0, 0, 0)
  const diff = midnight - now
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  const s = Math.floor((diff % 60000) / 1000)
  el.textContent = `NEXT: ${h}h ${m}m ${s}s`
}
setInterval(updateCountdown, 1000)
```

---

## 9. Status System

### Global Status Badges (Status Bar)
```
⬤ AUTO MODE    purple  — AutoScheduler active
⬤ AI Active    green   — AI engine running
⬤ ON AIR       red     — Studio broadcasting
⬤ Log Ready    green   — Broadcast log ready
⬤ No Log       amber   — Log not generated
⬤ X Clocks     cyan    — Number of clocks
⚡ SOHO Auto   purple  — AI scheduling mode
⬤ Sync OK      cyan    — DB sync healthy
⬤ X Campaigns  green   — Active ad campaigns
```

### AI Schedule States
```
Status    Color   Badge Text
done      green   ✅ Today's scheduling done
pending   amber   ⚠️ No scheduling done
failed    red     🔴 Scheduling Failed
building  purple  ⏳ Generating...
```

### Ad Monitor States
```
0-11 min    green   ✅ Under limit
12-14 min   amber   ⚠️ Warning
15+ min     red     🔴 Exceeded
```

### Client Rotation Status
```
>3 min/hr   red     ● HIGH
1-3 min/hr  cyan    ● MEDIUM
<1 min/hr   green   ● LOW
```

### Song Overplay (Future)
```
15+ plays/month   red     🔴 Overplayed
12-14 plays       amber   🟡 Warning
<12 plays         —       Normal
```

---

## 10. Iconography

### Custom Icons Used
```
Music/Audio:
♪  — Songs, music notes
♩  — Jingle
◉  — Record/broadcast dot
▶  — Play
■  — Stop
⏸  — Pause
≫  — Fast forward (Stitcher)

Navigation:
▸  — Breadcrumb separator
▾  — Dropdown arrow
→  — Arrow/link
←  — Back
↑↓ — Move up/down

Status:
●  — Filled dot (status)
○  — Empty dot (inactive)
⬤  — Large dot (status bar)
✅ — Done/success
⚠️ — Warning
🔴 — Error/exceeded
✓  — Checkmark

AI/Special:
✦  — AI Magic (star diamond)
⚡ — SOHO Auto / Force
⚙  — Settings/gear
✎  — Edit
↺  — Reset/refresh
⧉  — Duplicate
◷  — Clock/timer
◈  — Categories diamond
```

### Left Border as Visual Accent
```
Every interactive element uses
a 2-3px left border as accent:
→ Identifies the type/color of item
→ Consistent design language
→ High contrast against dark bg
→ Used on: buttons, cards, rows, 
   inputs, panels, badges
```

---

## 11. Responsive Behavior

### Fixed Resolution
```
RadioAI is a DESKTOP Windows app.
Fixed at 1440 × 900px minimum.
No mobile/tablet support.
No responsive breakpoints needed.

If window smaller than 1440px:
→ Scrollbars appear
→ Layout stays fixed
→ No reflow
```

### Scrollable Areas
```
Scrollable (overflow-y: auto):
- Song list (center panel)
- Campaign list (spots center)
- Playlist queue (studio)
- Clock slot list (clock editor)
- AI Monitor right panel (spots)
- Timeline (AI Magic)
- Client rotation table

Scrollbar styling:
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #0a0b18; }
::-webkit-scrollbar-thumb { 
  background: #252840;
  border-radius: 2px;
}
::-webkit-scrollbar-thumb:hover {
  background: #454d6d;
}
```

---

## 12. Design Decisions Log

### Decision 1 — Dark Theme Only
```
Reason: Radio stations run 24/7 in dark rooms.
Light theme would cause eye strain.
Industry standard: all pro radio software is dark.
```

### Decision 2 — Jazler-Inspired Layout
```
Reason: Target users are Jazler SOHO users.
Familiar layout reduces learning curve.
Same mental model: clocks, grid, library.
But elevated with modern dark premium aesthetic.
```

### Decision 3 — Left Border as Accent
```
Reason: Needs to work on very dark backgrounds.
Traditional cards with colored borders were too heavy.
Left border = subtle but clear color coding.
Used consistently everywhere = strong design language.
```

### Decision 4 — Roboto Mono for Numbers
```
Reason: Time values (14:50:54) need fixed-width font.
Prevents layout shift as numbers change.
Looks professional and technical.
High contrast against dark background.
```

### Decision 5 — Removed Campaign Details Tab
```
Original: Right panel had 3 tabs.
Decision: Remove Campaign Details + Break Schedule.
Reason: Campaign details visible when clicking campaign.
Right panel = purely AI Monitor.
Result: More screen real estate for analytics.
```

### Decision 6 — AI Brain 3D Animation
```
Reason: AI Magic tab needed to "feel alive."
Pure CSS 3D rings — no heavy libraries.
Orbital motion = data processing metaphor.
Car engine metaphor: visible moving parts.
Performance: CSS transforms are GPU-accelerated.
```

### Decision 7 — Status Bar Always Visible
```
Reason: Radio operators need constant status.
36px at bottom = minimal space, maximum info.
Auto Mode, AI Active, On Air always visible.
No need to navigate to check system status.
```

### Decision 8 — Color = One Meaning Always
```
Rule: Each color has ONE semantic meaning.
Cyan = Songs/Music ALWAYS
Purple = AI/Settings ALWAYS
Green = Active/Done ALWAYS
Amber = Warning/Caution ALWAYS
Red = Error/Exceeded ALWAYS
Never use color decoratively.
```

### Decision 9 — Open Studio Never Reloads
```
Problem: Tab switch was stopping audio.
Solution: Studio is a persistent WebView.
"Open Studio" = switch tab only (never reload URL).
Bridge slot: open_studio() → setCurrentWidget()
Result: Seamless audio across all tab switches.
```

### Decision 10 — Spots Play Full Duration
```
Jazler Manual: "Spots play from start to END 
of actual audio file without mixing."
Decision: Spots ignore cue points entirely.
Song→Spot: song fade out 1s
Spot end: pre-load next item at T-2000ms
Spot→Song: song fade in 1s
Result: Professional ad break experience.
```

---

*RadioAI Studio Pro — Design System v1.0.0*  
*Dark Premium • AI Native • Jazler Compatible*  
*Designed for KISS FM 91.5, Jaipur, Rajasthan* 🎙️

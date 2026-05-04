# RADIOAI v2.0 — FIGMA-TO-PYQT6 LEARNING GUIDE

This is the TRAINING document for replicating Figma designs in PyQt6 with EXACT visual fidelity.

Read this BEFORE building every screen. Non-negotiable. No exceptions.

---

## LESSON 1 — UNDERSTAND THE GAP

Why past PyQt6 outputs looked LESS PREMIUM than the Figma designs:

**PROBLEMS TO AVOID:**
1. Using FLAT colors instead of gradients
2. Skipping multi-layer shadows (Figma has 2–3 stacked)
3. Ignoring inner shadows / highlights
4. Approximating spacing (12px instead of 8px)
5. Using system fonts instead of loaded fonts
6. Skipping glow effects (drop_shadow with color)
7. Not adding hover states
8. Using emoji instead of custom-drawn icons
9. Ignoring letter-spacing on labels
10. Making borders solid `#1c1f38` instead of `rgba(255,255,255,0.06)`

**SOLUTION:** This document teaches EXACTLY how to translate every Figma effect to PyQt6 correctly.

---

## LESSON 2 — THE WORKFLOW (MANDATORY)

For EVERY screen built, follow this exact order:

### STEP 1: Read Figma EXACTLY
Tool: Figma MCP `get_design_context`
Parameters:
- `fileKey`: `7oN9K61g94wKx3nu44KKDF`
- `nodeId`: `<screen node id>`

Get:
- Every element's exact x, y, width, height
- Every fill (gradient stops, colors, opacities)
- Every effect (shadows, blurs)
- Every text (font, size, weight, spacing)
- Every stroke (color, opacity, weight)

### STEP 2: Take Screenshot Reference
Tool: Figma MCP `get_screenshot`
Save it locally for visual comparison.

### STEP 3: Map to PyQt6 Using This Guide
Use the translation tables below. DO NOT IMPROVISE. Match every value.

### STEP 4: Build with Custom Widgets
Use widgets from `ui/widgets/`. Never inline-style if a widget exists.

### STEP 5: Take Screenshot of Built Output
Run `python main.py`. Take screenshot.

### STEP 6: Self-Compare
Side-by-side: Figma screenshot vs PyQt6 screenshot. List every difference.
- If different → fix and repeat.
- If matches → commit.

---

## LESSON 3 — TRANSLATION TABLES

### COLORS

```
Figma fill: #f1f5ff (solid)
PyQt6 QSS:  color: #f1f5ff;
PyQt6 code: widget.setStyleSheet("color: #f1f5ff;")
```

ALWAYS use exact hex from Figma. No approximation. If Figma says `#06b6d4`, use `#06b6d4` (not "cyan" or `#00bcd4`).

### GRADIENTS — CRITICAL

**Figma 2-stop linear gradient (top to bottom):**
- Stop 0: `#131626`
- Stop 1: `#0a0b18`

PyQt6 QSS:
```css
background: qlineargradient(
  x1:0, y1:0, x2:0, y2:1,
  stop:0 #131626,
  stop:1 #0a0b18
);
```

**Figma 3-stop gradient (135° diagonal):**
- Stop 0:   `#a78bfa`
- Stop 0.5: `#8b5cf6`
- Stop 1:   `#7c3aed`

PyQt6 QSS:
```css
background: qlineargradient(
  x1:0, y1:0, x2:1, y2:1,
  stop:0 #a78bfa,
  stop:0.5 #8b5cf6,
  stop:1 #7c3aed
);
```

**DIRECTION MAPPING:**
| Figma angle           | PyQt6 stops                  |
|-----------------------|------------------------------|
| 0° (top-down)         | x1:0, y1:0, x2:0, y2:1       |
| 90° (left-right)      | x1:0, y1:0, x2:1, y2:0       |
| 135° (diagonal)       | x1:0, y1:0, x2:1, y2:1       |
| 180° (bottom-up)      | x1:0, y1:1, x2:0, y2:0       |

### RADIAL GRADIENTS (Glows)

```css
background: qradialgradient(
  cx:0.5, cy:0.5, radius:0.7,
  fx:0.5, fy:0.5,
  stop:0 #7c3aed,
  stop:1 transparent
);
```

### SHADOWS — MOST IMPORTANT

Figma drop shadow:
- Offset: x=0, y=8
- Blur:   24
- Color:  `#7c3aed` at 50% opacity

PyQt6 code (NOT QSS — must use Python):

```python
from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor

shadow = QGraphicsDropShadowEffect()
shadow.setOffset(0, 8)
shadow.setBlurRadius(24)
shadow.setColor(QColor(124, 58, 237, 128))  # 50% = 128/255
widget.setGraphicsEffect(shadow)
```

**MULTI-LAYER SHADOWS:**
PyQt6 supports only ONE `QGraphicsDropShadowEffect` per widget.

WORKAROUND — create wrapper QFrames stacked behind each other, each with its own shadow.

Example: Premium button needs:
- Layer 1 (back):  blur 40, glow color, low opacity
- Layer 2 (mid):   blur 24, button color, 50%
- Layer 3 (front): the actual button

Stack them with same x, y, w, h.

### INNER SHADOWS

Figma inner shadow: white 1px down (subtle highlight).

PyQt6: There is NO native inner shadow. WORKAROUND — paint a 1px gradient line at top:

```css
border-top: 1px solid rgba(255, 255, 255, 0.15);
```

Or use QPainter to draw inner highlight.

### BORDERS — RGBA OPACITY

Figma border: white at 6% opacity.

```css
border: 1px solid rgba(255, 255, 255, 0.06);
```

NEVER USE:
```css
border: 1px solid #1c1f38;  /* loses translucency */
```

ALWAYS USE `rgba()` for subtle borders.

### TYPOGRAPHY — LETTER-SPACING

Figma text:
- Font: Inter Bold
- Size: 9px
- Letter-spacing: 1.5px
- Case: UPPERCASE
- Color: `#06b6d4`

PyQt6 code:
```python
from PyQt6.QtGui import QFont

label = QLabel("LIBRARIES")
font = QFont("Inter")
font.setBold(True)
font.setPixelSize(9)
font.setLetterSpacing(
    QFont.SpacingType.AbsoluteSpacing, 1.5
)
label.setFont(font)
label.setStyleSheet("color: #06b6d4;")
```

### FONT WEIGHTS

Figma uses: Regular (400), Medium (500), Semi Bold (600), Bold (700), Black (900).

PyQt6 mapping:
| Figma     | PyQt6                              |
|-----------|------------------------------------|
| Regular   | `QFont.Weight.Normal`   (400)      |
| Medium    | `QFont.Weight.Medium`   (500)      |
| Semi Bold | `QFont.Weight.DemiBold` (600)      |
| Bold      | `QFont.Weight.Bold`     (700)      |
| Black     | `QFont.Weight.Black`    (900)      |

For Inter Black 22px:
```python
font = QFont("Inter")
font.setWeight(QFont.Weight.Black)
font.setPixelSize(22)
font.setLetterSpacing(
    QFont.SpacingType.AbsoluteSpacing, -0.5
)
```

### FONTS — INSTALL THEM

If Figma uses "Inter" font, you MUST install it.

**Step 1:** Download Inter from https://rsms.me/inter/

**Step 2:** Place `.ttf` files in `assets/fonts/`:
- `Inter-Regular.ttf`
- `Inter-Medium.ttf`
- `Inter-SemiBold.ttf`
- `Inter-Bold.ttf`
- `Inter-Black.ttf`

**Step 3:** Load in `main.py` BEFORE creating windows:

```python
from PyQt6.QtGui import QFontDatabase
import os

fonts_dir = os.path.join(
    os.path.dirname(__file__),
    'assets', 'fonts'
)
for fname in os.listdir(fonts_dir):
    if fname.endswith('.ttf'):
        QFontDatabase.addApplicationFont(
            os.path.join(fonts_dir, fname)
        )
```

### SPACING — 8PX GRID RULE

Figma uses an 8px grid system. ALL spacing values MUST be multiples of 4 or 8:
- ✅ 4, 8, 12, 16, 20, 24, 32, 40, 48, 56, 64
- ❌ 11, 13, 17, 19, 22, 25, 30, 33

If Figma says padding 16, use 16. If Figma says gap 24, use 24. NEVER round to nearest 5 or 10.

### ROUNDED CORNERS

```css
/* uniform */
border-radius: 14px;

/* per corner (rare) */
border-top-left-radius: 14px;
border-top-right-radius: 14px;
border-bottom-left-radius: 0;
border-bottom-right-radius: 0;
```

---

## LESSON 4 — CUSTOM WIDGETS PATTERN

For premium effects beyond QSS, build CUSTOM `QWidget`s using `QPainter`.

**EXAMPLE — Glowing Button:**

```python
class GlowingButton(QPushButton):
    """Premium gradient button with glow."""

    def __init__(self, text="", color="#7c3aed",
                 light="#a78bfa", parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self._light = QColor(light)
        self.setMinimumHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Outer glow
        glow = QGraphicsDropShadowEffect()
        glow.setOffset(0, 8)
        glow.setBlurRadius(32)
        glow.setColor(QColor(124, 58, 237, 128))
        self.setGraphicsEffect(glow)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        rect = self.rect()

        # Background gradient
        gradient = QLinearGradient(
            0, 0, 0, rect.height()
        )
        gradient.setColorAt(0, self._light)
        gradient.setColorAt(0.5, self._color)
        gradient.setColorAt(1, QColor("#5b21b6"))

        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 14, 14)

        # Inner highlight (top half)
        highlight = QLinearGradient(
            0, 0, 0, rect.height() / 2
        )
        highlight.setColorAt(0, QColor(255, 255, 255, 38))
        highlight.setColorAt(1, QColor(255, 255, 255, 0))

        painter.setBrush(QBrush(highlight))
        painter.drawRoundedRect(
            rect.adjusted(0, 0, 0, -rect.height()//2),
            14, 14
        )

        # Text
        painter.setPen(QColor("#ffffff"))
        font = QFont("Inter")
        font.setWeight(QFont.Weight.Bold)
        font.setPixelSize(14)
        font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, -0.2
        )
        painter.setFont(font)
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignCenter, self.text()
        )
```

USE LIKE THIS:
```python
btn = GlowingButton("Open Studio", "#7c3aed", "#a78bfa")
```

---

## LESSON 5 — REQUIRED WIDGETS LIBRARY

Build these in `E:\RadioAI_v2\ui\widgets\`. Create them once, then reuse:

1. **`premium_card.py`**
   - QFrame with multi-stop gradient bg
   - Top 3px accent gradient bar
   - Subtle 1px white border @ 6%
   - Multi-layer drop shadows

2. **`glowing_button.py`**
   - Custom paint with gradient
   - Outer glow with color matching theme
   - Inner top highlight
   - Hover state animation

3. **`stat_card.py`**
   - Premium card with mini icon
   - Big stat number with glow
   - Label uppercase with letter-spacing
   - Color accent bar at top

4. **`waveform_widget.py`**
   - Custom QPainter
   - Gradient bars (played vs unplayed)
   - Smooth 60fps animation
   - Glowing playhead

5. **`premium_table.py`**
   - Styled QTableWidget subclass
   - Alternating row colors
   - Selected row with cyan accent + tint
   - Custom row painting

6. **`premium_badge.py`**
   - Pill-shaped badge with subtle gradient
   - Letter-spacing label
   - Color customizable

7. **`pictorial_icon.py`**
   - Custom drawn icons (no emoji)
   - Multiple types: songs, jingle, spot, sweeper, stitcher, instant
   - Fillable with gradient

8. **`live_indicator.py`**
   - Pulsing red dot with glow
   - Animated opacity

9. **`category_pill.py`**
   - Colored mini-badge for categories
   - Auto-sized to text

10. **`live_clock.py`**
    - Big mono font clock
    - Auto-updates every second
    - Date subtitle

---

## LESSON 6 — QSS STYLE SHEET PATTERN

Create `E:\RadioAI_v2\assets\premium.qss`. This is the CENTRAL style file. Apply once on QApplication:

```python
with open('assets/premium.qss', 'r') as f:
    app.setStyleSheet(f.read())
```

Use property selectors for variants:

```css
QPushButton[role="primary"]   { ... }
QPushButton[role="secondary"] { ... }
QFrame[role="card"]           { ... }
QFrame[role="card-cyan"]      { ... }
QFrame[role="card-purple"]    { ... }
QLabel[role="page-title"]     { ... }
QLabel[role="section-label"]  { ... }
QLabel[role="stat-value"]     { ... }
```

In code:
```python
card = QFrame()
card.setProperty("role", "card-cyan")
# QSS auto-applies cyan accent
```

---

## LESSON 7 — VERIFICATION PROTOCOL

After EVERY screen build, run this protocol:

### CHECK 1 — Visual Match
- [ ] Take screenshot of running app
- [ ] Open Figma design side by side
- [ ] Same layout positions?
- [ ] Same colors (use color picker)?
- [ ] Same fonts loading?
- [ ] Same shadows/glows visible?

### CHECK 2 — Spacing Audit
- [ ] All paddings multiples of 4 or 8?
- [ ] All gaps multiples of 4 or 8?
- [ ] All margins matching Figma exactly?

### CHECK 3 — Typography Audit
- [ ] All fonts loaded (no fallback rendering)?
- [ ] Letter-spacings applied?
- [ ] Uppercase labels actually uppercase?
- [ ] Font weights correct?

### CHECK 4 — Polish Audit
- [ ] Buttons have hover states?
- [ ] Cards have subtle borders (rgba)?
- [ ] Shadows have color (not just black)?
- [ ] Gradients multi-stop (not flat)?
- [ ] Icons custom drawn (not emoji)?

If ANY check fails → fix it. Don't proceed.
If ALL pass → commit and report success.

---

## LESSON 8 — COMMON MISTAKES TO AVOID

❌ **MISTAKE 1: Using hex without alpha for borders**
```css
/* Wrong */ border: 1px solid #1c1f38;
/* Right */ border: 1px solid rgba(255,255,255,0.06);
```

❌ **MISTAKE 2: Flat color where gradient exists**
```css
/* Wrong */ background: #0e1020;
/* Right */ background: qlineargradient(stop:0 #131626, stop:1 #0a0b18);
```

❌ **MISTAKE 3: Skipping shadows because "QSS doesn't support"**
- Wrong: no shadow added
- Right: use `QGraphicsDropShadowEffect` (Python code)

❌ **MISTAKE 4: Emoji as icons**
```python
# Wrong
label.setText("♪")
# Right
# Custom QPainter drawn icon
```

❌ **MISTAKE 5: Default font**
```python
# Wrong
QFont()  # uses system font
# Right
QFont("Inter")  # + load .ttf first
```

❌ **MISTAKE 6: No letter-spacing**
```python
# Wrong
font.setPixelSize(9)
# Right
font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
```

❌ **MISTAKE 7: Approximating spacing**
```css
/* Wrong */ padding: 15px;  /* Figma had 16 */
/* Right */ padding: 16px;  /* exact */
```

❌ **MISTAKE 8: Single-layer shadows**
- Wrong: one drop shadow only
- Right: stack 2–3 shadows for premium glow

❌ **MISTAKE 9: Hard-coded styles inline**
```python
# Wrong
widget.setStyleSheet("background: red;")
# Right
widget.setProperty("role", "danger")
# + central QSS rule for [role="danger"]
```

❌ **MISTAKE 10: Building without screenshot comparison**
- Wrong: build → declare done
- Right: build → screenshot → compare → fix → repeat

---

## LESSON 9 — WHEN STUCK, ASK

If you cannot achieve a Figma effect in PyQt6:

**DON'T:** Give up and use a simpler version.

**DO:** Stop and report:

> "I cannot replicate [SPECIFIC EFFECT] in PyQt6.
>  Figma shows: [describe effect]
>  My attempt: [describe what you tried]
>  Result: [why it doesn't match]
>
>  Should I:
>  A) Use this approximation: [describe]
>  B) Skip this effect
>  C) Wait for guidance"

User will guide you. Don't silently downgrade.

---

## LESSON 10 — REFERENCE QUALITY BENCHMARK

Output should match this quality standard:

- ✅ Linear (linear.app desktop)
- ✅ Notion (notion.so desktop)
- ✅ Vercel Dashboard
- ✅ Spotify Desktop
- ✅ Discord (despite issues, UI is polished)

Study these apps' visual treatments:
- Multi-layer shadows
- Subtle gradients
- Letter-spacing on labels
- Custom icons
- Smooth hover states
- Glassmorphism

If output looks like:
- ❌ Basic Tkinter
- ❌ Default WinForms
- ❌ Old Java Swing

You've failed. Rebuild using this guide.

---

## EXECUTION PROTOCOL

When the user asks you to build a screen:

1. **ACKNOWLEDGE:** "Building [screen name] from Figma node X:Y. Following `FIGMA_TO_PYQT6.md` guide."
2. **READ FIGMA:** Call `get_design_context` with exact `nodeId`. Save the response.
3. **SCREENSHOT:** Call `get_screenshot`. Save locally.
4. **PLAN:** List which custom widgets you'll use, which need to be built fresh.
5. **BUILD:** Code with EXACT values from Figma. Use central QSS + custom widgets.
6. **TEST:** Run `python main.py`. Take screenshot.
7. **COMPARE:** Check against Figma screenshot. List differences.
8. **ITERATE:** Fix differences. Re-screenshot. Repeat until visually identical.
9. **COMMIT:**
   ```
   git add .
   git commit -m "feat: [screen] - exact Figma match"
   ```
10. **REPORT:** "Done. Visual match: 95%+. Differences: [list any minor remaining]."

---

Save this file. Reference it before EVERY screen. Update it if you learn new techniques.

This is the training. Master it.

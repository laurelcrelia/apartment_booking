---
name: Atelier Reserve
colors:
  surface: '#faf8ff'
  surface-dim: '#d2d9f4'
  surface-bright: '#faf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3ff'
  surface-container: '#eaedff'
  surface-container-high: '#e2e7ff'
  surface-container-highest: '#dae2fd'
  on-surface: '#131b2e'
  on-surface-variant: '#444653'
  inverse-surface: '#283044'
  inverse-on-surface: '#eef0ff'
  outline: '#757684'
  outline-variant: '#c4c5d5'
  surface-tint: '#3755c3'
  primary: '#00288e'
  on-primary: '#ffffff'
  primary-container: '#1e40af'
  on-primary-container: '#a8b8ff'
  inverse-primary: '#b8c4ff'
  secondary: '#006a61'
  on-secondary: '#ffffff'
  secondary-container: '#86f2e4'
  on-secondary-container: '#006f66'
  tertiary: '#611e00'
  on-tertiary: '#ffffff'
  tertiary-container: '#872d00'
  on-tertiary-container: '#ffa583'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dde1ff'
  primary-fixed-dim: '#b8c4ff'
  on-primary-fixed: '#001453'
  on-primary-fixed-variant: '#173bab'
  secondary-fixed: '#89f5e7'
  secondary-fixed-dim: '#6bd8cb'
  on-secondary-fixed: '#00201d'
  on-secondary-fixed-variant: '#005049'
  tertiary-fixed: '#ffdbce'
  tertiary-fixed-dim: '#ffb59a'
  on-tertiary-fixed: '#380d00'
  on-tertiary-fixed-variant: '#802a00'
  background: '#faf8ff'
  on-background: '#131b2e'
  surface-variant: '#dae2fd'
typography:
  display:
    fontFamily: Plus Jakarta Sans
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-lg:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-compact: 0.75rem
  margin: 2rem
  margin-compact: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

The design system establishes a poised, architectural atmosphere tailored for boutique residential property management. It balances modern operational efficiency with the understated quiet luxury of high-end hospitality. The target users are independent boutique operators, asset managers, and concierge teams who navigate complex booking schedules, guest profiles, and financial metrics daily. 

The aesthetic is anchored in **Minimalism** enriched with subtle tactile precision:
- **Calm Authority:** High-density booking workflows are counterbalanced by disciplined negative space and harmonious structural hierarchy.
- **Architectural Clarity:** Flat plane compositions rely on surface luminance shifts (#F8FAFC to #FFFFFF) and hairline structural borders rather than aggressive decorative elevations.
- **Functional Sophistication:** Color is reserved strictly for focal intent, semantic health, and direct interaction affordances, ensuring data clarity remains the primary focus.

## Colors

The palette is engineered to reduce ocular fatigue over extended operational shifts while maintaining crisp, high-contrast readability across critical booking details.

- **Primary Canvas & Surfaces:** Background is a calibrated warm off-white (`#F8FAFC`), establishing depth beneath pure white elevated cards and panels (`#FFFFFF`).
- **Primary Accent (`#1E40AF`):** A deep, architectural slate-indigo deployed strictly for key CTAs, active reservation indicators, selected calendar slots, and prominent navigation states.
- **Secondary Accent (`#0D9488`):** Deep spruce teal used for secondary metrics, verified guest indicators, and luxury amenity markers.
- **Text & Hierarchy:**
  - High Emphasis / Primary Headlines: Slate 900 (`#0F172A`)
  - Medium Emphasis / Body & Metadata: Slate 700 (`#334155`)
  - Low Emphasis / Captions & Placeholders: Slate 500 (`#64748B`)
- **Borders & Dividers:** Subtle hairline tones (`#E2E8F0`) provide crisp structural containment without visual clutter.
- **Semantic Feedback:**
  - Confirmed / Active: Emerald (`#059669` text, `#ECFDF5` container, `#A7F3D0` border)
  - Pending / Review: Amber (`#D97706` text, `#FFFBEB` container, `#FDE68A` border)
  - Cancelled / Inactive: Slate (`#475569` text, `#F1F5F9` container, `#CBD5E1` border)
  - Urgent / Blocked: Rose (`#E11D48` text, `#FFF1F2` container, `#FECDD3` border)

## Typography

The pairing leverages **Plus Jakarta Sans** for display and narrative body text to impart a warm, contemporary architectural cadence, paired with **Inter** for dense transactional labels, tabular data, and UI chrome.

- **Numerics & Tabular Data:** All numerical display—such as revenue stats, nightly rates, room counts, and stay dates—must enforce tabular figures (`font-variant-numeric: tabular-nums`) via Inter to preserve strict vertical column alignment.
- **Headlines:** Set with slightly tightened tracking (`-0.01em` to `-0.02em`) to enhance structural cohesion in dashboards and modal headers.
- **Metadata & Badges:** Micro labels use Inter semi-bold (`fontWeight: 600`) with modest letter-spacing (`0.02em` to `0.04em`) to maintain legibility when styled in uppercase or within constrained pill tags.

## Layout & Spacing

The web app uses a 12-column fluid grid system pinned to a maximum canvas constraint of `1600px` for ultra-wide desktop monitors, ensuring wide multi-unit schedule views do not over-stretch.

- **Primary Layout Structure:**
  - **Sidebar:** Fixed at `260px` for global navigation, collapsing to an icon rail (`72px`) on compact laptop screens (< 1280px).
  - **Main Canvas:** Fluid 12-column layout with `2rem` outer page margins and `1.5rem` gutters.
  - **Inspector / Detail Drawer:** Sliding right-hand panel fixed at `420px` for in-depth reservation modification and guest intake.
- **Vertical Rhythm:**
  - Page header to content block: `space-xl` (`2.5rem`).
  - Section-to-section flow inside cards: `space-lg` (`1.5rem`).
  - Form field groupings and data pairs: `space-md` (`1rem`).
  - Micro spacings between labels, validation messages, and icons: `space-xs` to `space-sm`.

## Elevation & Depth

This design system avoids heavy shadows, instead relying on tonal surface boundaries and ambient, feather-weight diffusion to convey z-axis hierarchy:

- **Flat Surface (Level 0):** Application canvas background (`#F8FAFC`). No shadow.
- **Base Card & Table Surface (Level 1):** Solid white (`#FFFFFF`) framed by a 1px continuous border of `#E2E8F0`. Shadow: `0 1px 3px 0 rgba(15, 23, 42, 0.04), 0 1px 2px -1px rgba(15, 23, 42, 0.02)`.
- **Interactive Hover & Dropdown (Level 2):** Elevated cards on pointer hover, context menus, and inline autocomplete popovers. Shadow: `0 4px 6px -1px rgba(15, 23, 42, 0.06), 0 2px 4px -2px rgba(15, 23, 42, 0.04)`.
- **Floating Modals, Drawers & Toast Notifications (Level 3):** Right drawer sheets, modal dialogs, and top-right toast alerts. Shadow: `0 20px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.03)`. Modals use a backdrop overlay of `#0F172A` with 20% opacity and a backdrop blur of `4px`.

## Shapes

The interface balances sharp architectural lines with soft geometry to convey professional precision without clinical coldness:

- **Cards, Panels & Data Tables:** Standardized at `0.5rem` (`rounded-md` / level 2), creating cohesive containment blocks across the screen.
- **Form Inputs, Buttons & Controls:** Formally bounded at `0.5rem` to match parent card geometry.
- **Status Chips & Pills:** Full pill treatment (`9999px`) to differentiate static structural bounds from reactive state metadata.
- **Modal Containers & Drawers:** Scaled up to `rounded-lg` (`1rem`) on top corners to soften deep-layer overlays.

## Components

### Buttons
- **Primary:** Solid `#1E40AF` fill with `#FFFFFF` text. Subtle hover state shifting to `#1D4ED8`. Active state scales subtly (`transform: scale(0.99)`). 38px standard height, `space-md` horizontal padding.
- **Secondary:** Surface `#FFFFFF` background with 1px border `#E2E8F0`, slate-700 text (`#334155`). Hover transition to `#F8FAFC` and border `#CBD5E1`.
- **Destructive / Cancellation:** Transparent background, rose text (`#E11D48`). Hover fills with `#FFF1F2`.

### Status Badges & Chips
- Configured as pill shapes with `0.25rem` vertical and `0.625rem` horizontal padding. Typography: `label-sm`.
- **Confirmed / Active:** `#ECFDF5` background, `#047857` text, subtle `#A7F3D0` border. Includes a 6px solid emerald dot before text.
- **Pending:** `#FFFBEB` background, `#B45309` text, `#FDE68A` border. Includes an amber pulsing dot.
- **Cancelled / Archived:** `#F1F5F9` background, `#475569` text, `#CBD5E1` border.

### Data Tables
- Container framed with 1px `#E2E8F0` border and `rounded-md` corners. Table header rendered on `#F8FAFC` with `label-md` uppercase text in `#64748B`.
- Row styling: Alternating subtle zebra striping (`#FFFFFF` to `#FBFCFD`) with hairline bottom borders (`#F1F5F9`). Row height set to a generous `52px` for comfortable scanning.
- Hover state: Entire row shifts to `#F8FAFC` with direct action buttons fading into view.

### Input Fields & Form Controls
- Inputs use `#FFFFFF` background, 1px `#E2E8F0` border, `0.5rem` radius, and `38px` fixed height. Text is `#0F172A` with `#94A3B8` placeholder.
- **Focus State:** Hairline ring with primary color: `box-shadow: 0 0 0 1px #1E40AF`, no heavy glowing halos.
- **Inline Validation:** Error messages sit `4px` directly below the field in rose (`#E11D48`, `label-sm`), accompanying a red-tinted input border (`#FCA5A5`).

### Toast Notifications
- Floated top-right at `margin: 1.5rem`, max width `380px`.
- High surface luminance (`#FFFFFF`) with Level 3 elevation shadow, a left accent border (3px solid `#1E40AF` or `#059669`), body text in `#334155`, and an effortless dismiss cross icon in `#94A3B8`.

### Specialized: Multi-Unit Booking Timeline
- Compact Gantt/calendar matrix displaying individual apartments along the y-axis and dates across the x-axis.
- Reserved blocks render as rounded bars (`rounded-sm`) using `#DBEAFE` background with `#1E40AF` borders and primary text. 
- Maintenance/blocked intervals utilize muted angled striping over slate `#F1F5F9`.
---
name: ReviewMind
colors:
  surface: '#101418'
  surface-dim: '#101418'
  surface-bright: '#363a3e'
  surface-container-lowest: '#0b0f13'
  surface-container-low: '#181c20'
  surface-container: '#1c2024'
  surface-container-high: '#262a2f'
  surface-container-highest: '#31353a'
  on-surface: '#e0e2e8'
  on-surface-variant: '#b9caca'
  inverse-surface: '#e0e2e8'
  inverse-on-surface: '#2d3135'
  outline: '#849495'
  outline-variant: '#3a494a'
  surface-tint: '#00dce5'
  primary: '#e9feff'
  on-primary: '#003739'
  primary-container: '#00f5ff'
  on-primary-container: '#006c71'
  inverse-primary: '#00696e'
  secondary: '#c2c7d0'
  on-secondary: '#2c3138'
  secondary-container: '#42474f'
  on-secondary-container: '#b1b5bf'
  tertiary: '#fff9f0'
  on-tertiary: '#3a3000'
  tertiary-container: '#ffdb3f'
  on-tertiary-container: '#736000'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#63f7ff'
  primary-fixed-dim: '#00dce5'
  on-primary-fixed: '#002021'
  on-primary-fixed-variant: '#004f53'
  secondary-fixed: '#dee2ec'
  secondary-fixed-dim: '#c2c7d0'
  on-secondary-fixed: '#171c23'
  on-secondary-fixed-variant: '#42474f'
  tertiary-fixed: '#ffe16c'
  tertiary-fixed-dim: '#e7c427'
  on-tertiary-fixed: '#221b00'
  on-tertiary-fixed-variant: '#544600'
  background: '#101418'
  on-background: '#e0e2e8'
  surface-variant: '#31353a'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 16px
  margin: 24px
---

## Brand & Style
The design system is built on a **Technical Minimalist** aesthetic, blending the precision of an IDE with the clarity of a high-end SaaS dashboard. It evokes a sense of deep focus and industrial-grade reliability. The interface mimics a sophisticated terminal environment without the clutter, utilizing heavy black levels and sharp accents to guide the user's eye through dense code analysis data.

**Target Audience:** Software engineers, security researchers, and DevOps leads who value information density and rapid cognitive processing.

**Visual Principles:**
- **Information Density:** Prioritize data over decoration.
- **Agent Presence:** Distinct color signatures for autonomous agents.
- **Motion:** Subtle, low-latency transitions that feel "instant" and mechanical.

## Colors
The palette is dominated by a true-black and deep charcoal foundation to minimize eye strain during long review sessions. 

- **Primary Accent:** Electric Cyan (#00F5FF) is reserved for the primary agent (Orchestrator) and active states.
- **Surface Strategy:** Backgrounds use `#0A0E12`, while interactive surfaces and cards use `#161B22`.
- **Semantic Logic:** Agent identities are color-coded to provide instant visual grouping. These colors should be used as thin borders (left-edge), status dots, or low-opacity background washes (10% alpha).
- **Event Timeline:** Specific hex codes for thinking, tools, and errors allow users to scan the multi-agent orchestration logs at high speed.

## Typography
This design system employs a dual-font strategy:
- **Inter** handles the administrative and structural UI, providing a modern, legible experience for high-level navigation and communication.
- **JetBrains Mono** is used for all technical artifacts, including code blocks, agent names, tool parameters, and metadata labels. 

**Mobile Strategy:** 
Headlines scale down by 20% on mobile devices. Code blocks use a horizontal scroll to maintain the monospaced character grid.

## Layout & Spacing
The layout follows a **Fluid Content / Fixed Sidebar** model. 
- **Sidebars:** Fixed at 280px for agent orchestration logs and navigation.
- **Main View:** A fluid grid that accommodates side-by-side code diffs.
- **Rhythm:** An 8px base grid is used for all padding and margins to maintain a structured, mathematical feel.
- **Density:** Spacing is generous between major sections (24px+) but tight within data groups (8px) to maximize the vertical visibility of code and logs.

## Elevation & Depth
Elevation is communicated through **Tonal Layering** and **Low-Contrast Outlines** rather than traditional shadows.
- **Level 0 (Background):** `#0A0E12` (Base).
- **Level 1 (Surface):** `#161B22` with a 1px border of `#30363D`.
- **Level 2 (Popovers/Tooltips):** `#1C2128` with a subtle Electric Cyan glow (2px blur, 10% opacity) for active agents.
- **Interaction:** Hovering over a card should change the border color to a slightly brighter gray (`#8B949E`) or the specific agent color if applicable.

## Shapes
A consistent 8px (`rounded-md`) radius is applied to all primary containers, cards, and input fields. 
- **Buttons:** Use `rounded-md` (8px).
- **Chips/Badges:** Use `rounded-full` (Pill-shaped) for status indicators to contrast against the rectangular layout of code blocks.
- **Code Highlights:** Use 0px roundedness for inline code markers within paragraphs to maintain the "text block" aesthetic.

## Components
- **Buttons:** 
  - *Primary:* Solid Electric Cyan with Black text. 
  - *Ghost:* No background, Electric Cyan border, only for secondary actions.
- **Agent Cards:** Feature a 4px solid left border colored according to the agent's identity. Titles are set in `label-caps`.
- **Code Blocks:** Syntax highlighting follows a customized "Dark Terminal" theme. Line numbers are rendered in a muted Slate color.
- **Timeline/Logs:** Continuous vertical line on the left, with circular nodes color-coded by the "Event Color Coding" rules (e.g., Amber for thinking).
- **Input Fields:** Dark background (`#0D1117`), 1px border, focused state uses an Electric Cyan glow.
- **Agent Badges:** Small pill shapes with an icon and the agent name in `code-sm` font.
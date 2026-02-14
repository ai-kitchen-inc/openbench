# Design System

Notion-inspired. Monochrome. Icon-driven. No emojis.

Applies to **all UI/UX across the project** — chat interfaces, forms, dashboards, components, and any future frontend surfaces.

---

## Design Philosophy

The UI follows Notion's visual language: content-first, distraction-free, black ink on white paper. Every element earns its place through function, not decoration.

**Principles:**
1. **Content over chrome** -- minimal UI furniture, maximum content visibility
2. **Monochrome hierarchy** -- use weight and opacity, not color, for emphasis
3. **Flat and precise** -- 1px borders, no gradients, no heavy shadows
4. **Icon-driven** -- Lucide icons replace all emoji and decorative elements
5. **Typographic scale** -- size and weight carry meaning, not color

---

## Color Tokens

```css
:root {
  /* ── Base ── */
  --ob-white:           #ffffff;
  --ob-black:           #1a1a1a;

  /* ── Gray Scale (Carbon) ── */
  --ob-gray-50:         #fafafa;
  --ob-gray-100:        #f5f5f5;
  --ob-gray-150:        #efefef;
  --ob-gray-200:        #e5e5e5;
  --ob-gray-300:        #d4d4d4;
  --ob-gray-400:        #a3a3a3;
  --ob-gray-500:        #737373;
  --ob-gray-600:        #525252;
  --ob-gray-700:        #404040;
  --ob-gray-800:        #262626;
  --ob-gray-900:        #1a1a1a;

  /* ── Semantic ── */
  --ob-text-primary:    var(--ob-gray-900);    /* Headings, body */
  --ob-text-secondary:  var(--ob-gray-500);    /* Captions, timestamps */
  --ob-text-tertiary:   var(--ob-gray-400);    /* Placeholders, disabled */
  --ob-text-inverse:    var(--ob-white);       /* On dark backgrounds */

  --ob-bg-primary:      var(--ob-white);       /* Page background */
  --ob-bg-secondary:    var(--ob-gray-50);     /* Sidebar, code blocks */
  --ob-bg-tertiary:     var(--ob-gray-100);    /* Hover states, chips */
  --ob-bg-elevated:     var(--ob-white);       /* Cards, modals */

  --ob-border-default:  rgba(0, 0, 0, 0.08);  /* Subtle dividers */
  --ob-border-strong:   rgba(0, 0, 0, 0.15);  /* Focused inputs */

  /* ── Accent (minimal use) ── */
  --ob-accent:          #2383e2;               /* Links, active states only */
  --ob-accent-hover:    #1b6ec2;
  --ob-accent-subtle:   rgba(35, 131, 226, 0.08);

  /* ── Status ── */
  --ob-success:         #2d8a56;
  --ob-warning:         #c27a1a;
  --ob-error:           #cc3333;
  --ob-info:            var(--ob-accent);
}
```

### Dark Mode Override

```css
[data-theme="dark"] {
  --ob-text-primary:    #ebebeb;
  --ob-text-secondary:  #8a8a8a;
  --ob-text-tertiary:   #5c5c5c;
  --ob-text-inverse:    var(--ob-gray-900);

  --ob-bg-primary:      #191919;
  --ob-bg-secondary:    #212121;
  --ob-bg-tertiary:     #2a2a2a;
  --ob-bg-elevated:     #252525;

  --ob-border-default:  rgba(255, 255, 255, 0.08);
  --ob-border-strong:   rgba(255, 255, 255, 0.15);
}
```

---

## Typography

System font stack. No web font requests, instant render.

```css
:root {
  --ob-font-sans:       -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter",
                        "Roboto", "Helvetica Neue", Arial, sans-serif;
  --ob-font-mono:       "SF Mono", "Fira Code", "Fira Mono", "Roboto Mono",
                        "Consolas", "Monaco", monospace;

  /* ── Scale ── */
  --ob-text-xs:         0.75rem;     /* 12px — timestamps, badges */
  --ob-text-sm:         0.8125rem;   /* 13px — captions, sidebar items */
  --ob-text-base:       0.875rem;    /* 14px — body text (Notion default) */
  --ob-text-md:         0.9375rem;   /* 15px — message content */
  --ob-text-lg:         1.125rem;    /* 18px — section headings */
  --ob-text-xl:         1.5rem;      /* 24px — page titles */

  /* ── Weight ── */
  --ob-font-normal:     400;
  --ob-font-medium:     500;
  --ob-font-semibold:   600;

  /* ── Line Height ── */
  --ob-leading-tight:   1.3;
  --ob-leading-normal:  1.5;
  --ob-leading-relaxed: 1.625;
}
```

### Usage

| Element | Size | Weight | Color |
|---------|------|--------|-------|
| Page title | `--ob-text-xl` | `--ob-font-semibold` | `--ob-text-primary` |
| Section heading | `--ob-text-lg` | `--ob-font-semibold` | `--ob-text-primary` |
| Body / message | `--ob-text-md` | `--ob-font-normal` | `--ob-text-primary` |
| Sidebar item | `--ob-text-sm` | `--ob-font-normal` | `--ob-text-primary` |
| Timestamp | `--ob-text-xs` | `--ob-font-normal` | `--ob-text-secondary` |
| Placeholder | `--ob-text-base` | `--ob-font-normal` | `--ob-text-tertiary` |
| Code | `--ob-text-sm` | `--ob-font-normal` | `--ob-text-primary`, mono |

---

## Spacing

4px base unit. All spacing is a multiple of 4.

```css
:root {
  --ob-space-0:     0;
  --ob-space-0.5:   2px;
  --ob-space-1:     4px;
  --ob-space-1.5:   6px;
  --ob-space-2:     8px;
  --ob-space-3:     12px;
  --ob-space-4:     16px;
  --ob-space-5:     20px;
  --ob-space-6:     24px;
  --ob-space-8:     32px;
  --ob-space-10:    40px;
  --ob-space-12:    48px;
  --ob-space-16:    64px;
}
```

---

## Border Radius

Minimal. Notion uses very slight rounding.

```css
:root {
  --ob-radius-sm:    3px;     /* Buttons, inputs, badges */
  --ob-radius-md:    5px;     /* Cards, panels */
  --ob-radius-lg:    8px;     /* Modals, large containers */
  --ob-radius-full:  9999px;  /* Avatars, pills */
}
```

---

## Shadows

Almost none. Notion uses elevation sparingly.

```css
:root {
  --ob-shadow-sm:    0 1px 2px rgba(0, 0, 0, 0.04);
  --ob-shadow-md:    0 2px 8px rgba(0, 0, 0, 0.08);   /* Dropdowns, popovers */
  --ob-shadow-lg:    0 8px 24px rgba(0, 0, 0, 0.12);   /* Modals only */
}
```

---

## Icons

**Lucide React** -- consistent 24x24 grid, 1.5px stroke, rounded joins.

```bash
pnpm add lucide-react
```

### Icon Mapping

Use these specific Lucide icons throughout the UI:

| Purpose | Icon | Lucide Name |
|---------|------|-------------|
| Send message | Arrow up in circle | `ArrowUp` |
| Attach file | Paperclip | `Paperclip` |
| New chat | Square with pen | `SquarePen` |
| Delete | Trash | `Trash2` |
| Close | X mark | `X` |
| Settings | Gear | `Settings` |
| Search | Magnifying glass | `Search` |
| Copy | Two squares | `Copy` |
| Check / copied | Checkmark | `Check` |
| Download | Arrow down to line | `Download` |
| File | Document | `FileText` |
| Image | Landscape | `Image` |
| Audio | Headphones | `Headphones` |
| Video | Play circle | `Play` |
| Chart | Bar chart | `BarChart3` |
| Code | Brackets | `Code2` |
| Markdown | Text | `Type` |
| User avatar | Circle user | `CircleUser` |
| Bot avatar | Sparkles | `Sparkles` |
| Streaming | Loader | `Loader2` (animated) |
| Expand | Maximize | `Maximize2` |
| Collapse sidebar | Panel left close | `PanelLeftClose` |
| Open sidebar | Panel left open | `PanelLeftOpen` |
| More actions | Ellipsis | `MoreHorizontal` |
| Time / clock | Clock | `Clock` |
| Link | Chain link | `Link` |
| External link | Arrow up right | `ExternalLink` |
| Warning | Triangle | `AlertTriangle` |
| Error | Circle X | `XCircle` |
| Success | Circle check | `CheckCircle` |
| Info | Circle i | `Info` |

### Icon Usage Rules

```tsx
import { ArrowUp, Paperclip, SquarePen } from 'lucide-react';

// Standard size: 16px for inline, 18px for buttons, 20px for sidebar
<ArrowUp size={18} strokeWidth={1.5} />

// Color inherits from parent text color
// Never use colored icons except for status (error, success, warning)
```

**Rules:**
- Default size: 16px (inline), 18px (buttons), 20px (sidebar/nav)
- Stroke width: 1.5px (default Lucide)
- Color: inherit from parent — never hardcode icon colors
- Status icons only use semantic colors: `--ob-error`, `--ob-success`, `--ob-warning`
- Never use emojis. Ever. Use Lucide icons for all visual indicators.

---

## Component Patterns

### Message Bubble

```
┌──────────────────────────────────────────────────────────┐
│ [CircleUser 16px]  You                     10:34 AM      │
│                                                          │
│  Show me Q4 sales by region                              │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ [Sparkles 16px]  Assistant                 10:34 AM      │
│                                                          │
│  Here's the Q4 sales breakdown by region:                │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  [BarChart3] Q4 Regional Sales                     │  │
│  │  ████████████  North America    $4.2M              │  │
│  │  ██████████    Europe           $3.1M              │  │
│  │  ████████      APAC             $2.8M              │  │
│  │  ███████       LATAM            $1.9M              │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  [FileText]  Q4-Report.pdf  2.1 MB   [Download]   │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**Bubble styling:**
- No background color for messages (content on white)
- Subtle `--ob-border-default` separator between messages
- Left-aligned for both user and assistant (Notion style, not chat bubbles)
- Timestamp in `--ob-text-secondary`, right-aligned

### Session Sidebar

```
┌─────────────────────────┐
│  [SquarePen]  New chat  │  ← subtle hover bg
│─────────────────────────│
│  [Search]  Search...    │  ← input with --ob-bg-secondary
│─────────────────────────│
│  Today                  │  ← --ob-text-secondary, --ob-text-xs
│  ○ Q4 Sales Analysis    │  ← active: --ob-font-medium
│  ○ Research Summary     │
│─────────────────────────│
│  Yesterday              │
│  ○ Product Roadmap      │
│  ○ Budget Review        │
└─────────────────────────┘
```

**Sidebar styling:**
- Width: 240px
- Background: `--ob-bg-secondary`
- Session items: `--ob-text-sm`, hover `--ob-bg-tertiary`
- Active session: `--ob-font-medium`, `--ob-bg-tertiary`
- Date groups: `--ob-text-xs`, `--ob-text-secondary`, uppercase

### Chat Input

```
┌──────────────────────────────────────────────────────────┐
│  [Paperclip]  Type a message...              [ArrowUp]   │
└──────────────────────────────────────────────────────────┘
```

**Input styling:**
- Border: `1px solid var(--ob-border-default)`
- Focus: `1px solid var(--ob-border-strong)`
- No box-shadow on focus (Notion style)
- Send button: filled `--ob-gray-900` circle with white arrow when has content
- Send button disabled: `--ob-gray-300`
- Min height: 44px, auto-grow to max 200px

### Streaming Indicator

```
[Loader2 rotating]  Thinking...
```

- `Loader2` icon with CSS `animation: spin 1s linear infinite`
- Text: "Thinking..." in `--ob-text-secondary`
- Positioned below last message

---

## CSS Custom Properties Summary

All tokens available as CSS custom properties with `--ob-` prefix:

```css
/* Apply to root */
.ob-chat {
  font-family: var(--ob-font-sans);
  font-size: var(--ob-text-base);
  color: var(--ob-text-primary);
  background: var(--ob-bg-primary);
  line-height: var(--ob-leading-normal);
}

/* Message text */
.ob-message-content {
  font-size: var(--ob-text-md);
  line-height: var(--ob-leading-relaxed);
}

/* Sidebar */
.ob-sidebar {
  width: 240px;
  background: var(--ob-bg-secondary);
  border-right: 1px solid var(--ob-border-default);
}

/* Input */
.ob-chat-input {
  border: 1px solid var(--ob-border-default);
  border-radius: var(--ob-radius-lg);
  padding: var(--ob-space-3) var(--ob-space-4);
  font-size: var(--ob-text-base);
}

.ob-chat-input:focus-within {
  border-color: var(--ob-border-strong);
}

/* Card surfaces (charts, files, etc.) */
.ob-surface-card {
  border: 1px solid var(--ob-border-default);
  border-radius: var(--ob-radius-md);
  padding: var(--ob-space-4);
  background: var(--ob-bg-primary);
}

/* Code blocks */
.ob-code-block {
  font-family: var(--ob-font-mono);
  font-size: var(--ob-text-sm);
  background: var(--ob-bg-secondary);
  border-radius: var(--ob-radius-sm);
  padding: var(--ob-space-4);
}
```

---

## Transitions

Minimal, purposeful. 150ms for micro-interactions, 200ms for layout.

```css
:root {
  --ob-transition-fast:   100ms ease;
  --ob-transition-base:   150ms ease;
  --ob-transition-slow:   200ms ease;
}

/* Apply to interactive elements */
.ob-interactive {
  transition: background var(--ob-transition-fast),
              border-color var(--ob-transition-fast),
              color var(--ob-transition-fast);
}
```

---

## Responsive Breakpoints

```css
:root {
  --ob-breakpoint-sm:   640px;   /* Mobile */
  --ob-breakpoint-md:   768px;   /* Tablet — sidebar collapses */
  --ob-breakpoint-lg:   1024px;  /* Desktop */
}

/* Sidebar hidden on mobile */
@media (max-width: 768px) {
  .ob-sidebar { display: none; }
  .ob-sidebar[data-open="true"] {
    display: flex;
    position: fixed;
    inset: 0;
    z-index: 50;
  }
}
```

---

## Reference: Notion Visual DNA

What we borrow from Notion:

| Aspect | Notion's Approach | Our Implementation |
|--------|-------------------|-------------------|
| Color | Near-monochrome, one accent | Carbon gray scale, blue accent for links only |
| Typography | System fonts, 14px base | Same — system stack, 14px base |
| Layout | Content-width centered | Full-width chat with 240px sidebar |
| Borders | 1px, very low opacity | `rgba(0,0,0,0.08)` default |
| Shadows | Almost none | Only on modals and dropdowns |
| Icons | Custom SVG set | Lucide React (similar aesthetic) |
| Hover | Subtle bg change | `--ob-bg-tertiary` on hover |
| Animations | Minimal, fast | 150ms transitions, no bounce/spring |
| Empty states | Centered, helpful text | WelcomeScreen with suggestion prompts |

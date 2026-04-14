# Design System Specification: The Value Architect

## 1. Overview & Creative North Star: "The Digital Curator"
This design system moves away from the traditional "coupon-clipping" aesthetic of the past, evolving into a high-end, editorial experience. Our Creative North Star is **The Digital Curator**. We are not just a marketplace; we are a sophisticated guide to local experiences. 

To achieve this, the system breaks the "standard template" look through **intentional asymmetry** and **tonal depth**. We replace rigid grids with breathable layouts, overlapping imagery, and a hierarchy that feels as much like a premium magazine as it does a digital tool. The goal is to make "value" feel like a "luxury" through meticulous attention to white space and sophisticated layering.

---

## 2. Color Philosophy & Logic
We move beyond flat application by using the color palette to define atmospheric depth.

### The Palette
*   **Primary (#2f6900):** Our "Growth Green." Used for core actions and brand anchors.
*   **Secondary (#116682):** "Deep Sky." Provides a professional, trustworthy counterpoint to the green.
*   **Surface Tiers:** We utilize a range of neutrals from `surface-container-lowest` (#ffffff) to `surface-dim` (#d5dae9) to define hierarchy.

### Visual Rules
*   **The "No-Line" Rule:** 1px solid borders are strictly prohibited for sectioning. Boundaries must be defined solely through background color shifts. For example, a `surface-container-low` card sits on a `surface` background to define its edges.
*   **Surface Hierarchy & Nesting:** Treat the UI as stacked sheets of fine paper. An inner container should always be one tier "higher" or "lower" than its parent (e.g., a `surface-container-highest` search bar nested within a `surface-container-low` header).
*   **The "Glass & Gradient" Rule:** Floating elements (like Safari extension popovers) must use **Glassmorphism**. Apply `surface` colors at 85% opacity with a 12px backdrop-blur. 
*   **Signature Textures:** Main CTAs should not be flat. Use a subtle linear gradient from `primary` (#2f6900) to `primary-container` (#3d8400) at a 135-degree angle to provide "soul" and a tactile, premium feel.

---

## 3. Typography: Editorial Authority
We use **Plus Jakarta Sans** for its geometric clarity and modern warmth, replacing the standard Nunito Sans with a more contemporary, wide-aperture typeface.

*   **Display & Headlines (The Hook):** Use `display-md` and `headline-lg` with tight letter-spacing (-0.02em). These are your editorial "hooks." Use them asymmetrically—don't always center them. 
*   **Titles (The Guide):** `title-lg` and `title-md` act as the authoritative voice for deal categories.
*   **Body & Labels (The Detail):** `body-md` is our workhorse for trust-building descriptions. We prioritize line heights of 1.5x for maximum readability.

The typography scale conveys brand identity by pairing large, bold headlines with significantly smaller, high-contrast labels (`label-md`), creating a "luxury boutique" information density.

---

## 4. Elevation & Depth: Tonal Layering
Traditional drop shadows are largely replaced by **Tonal Layering**.

*   **The Layering Principle:** Depth is achieved by stacking. Place a `surface-container-lowest` card on a `surface-container-low` section. This creates a soft, natural lift that feels integrated into the OS environment.
*   **Ambient Shadows:** For floating elements (Modals/Extension popups), use an "Ambient Shadow": `box-shadow: 0 12px 32px rgba(22, 28, 38, 0.06);`. The shadow color is a tinted version of `on-surface`, never pure black.
*   **The "Ghost Border" Fallback:** If a border is required for accessibility, use the `outline-variant` token at **15% opacity**. High-contrast, 100% opaque borders are forbidden.
*   **Glassmorphism:** To integrate with Safari’s native feel, use backdrop blurs on any element that "hovers" over content. This allows the primary brand green to bleed through subtly, softening the interface.

---

## 5. Component Signatures

### Buttons & Interaction
*   **Primary:** Gradient fill (`primary` to `primary-container`), `xl` roundedness (1.5rem), and white text. No border.
*   **Secondary:** `surface-container-highest` background with `on-surface` text. Feels like part of the UI, not an interruption.
*   **Tertiary:** Pure text with an underline that appears only on hover, using the `primary` color.

### Cards & Lists (The Collection)
*   **No Dividers:** Forbid the use of horizontal rules. Separate list items using 16px or 24px of vertical white space or alternating `surface-container-low` and `surface-container-lowest` backgrounds.
*   **Deal Cards:** Use "Organic Asymmetry." Images should have `lg` (1rem) rounding on the top-left and bottom-right, with `none` on the other corners to create a signature, custom look.

### Input Fields & Controls
*   **Inputs:** Use `surface-container-low` backgrounds instead of white boxes with borders. On focus, transition the background to `surface-container-lowest` and add a 2px `primary` ghost-border at 20% opacity.
*   **Chips:** Selection chips use `primary-fixed-dim` with `on-primary-fixed` text for a soft, rewarding "active" state.

### Specialized Components
*   **The Reward Streak:** A glassmorphic progress bar using a `primary` to `tertiary` gradient to visualize user savings and rewards.
*   **The "Extension Ribbon":** A slim, semi-transparent element designed for Safari that uses `surface-bright` with a heavy backdrop blur to feel like a native browser component.

---

## 6. Do’s and Don'ts

### Do
*   **Do** use overlapping elements (e.g., an image slightly breaking the container of a text block) to create editorial flow.
*   **Do** use "Surface-on-Surface" logic to create hierarchy.
*   **Do** prioritize `primary` green for moments of "Value" and `secondary` blue for moments of "Security/Checkout."

### Don't
*   **Don't** use 1px solid borders (unless at 15% opacity for accessibility).
*   **Don't** use standard "Material" blue for links; use our signature `primary` green or `secondary` blue.
*   **Don't** crowd the layout. If you think it needs more content, it probably needs more white space instead.
*   **Don't** use harsh drop shadows. If it looks like it's "floating," the shadow should be almost invisible.
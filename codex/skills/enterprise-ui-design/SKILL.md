---
name: enterprise-ui-design
description: This skill is for interface design — dashboards, admin panels, apps, tools, and interactive products. NOT for marketing design (landing pages, marketing sites, campaigns).
---

# Interface Design

Build interface design with craft and consistency.

## Scope

**Use for:** Dashboards, admin panels, SaaS apps, tools, settings pages, data interfaces.

**Not for:** Landing pages, marketing sites, campaigns. Redirect those to `/frontend-design`.

---

# The Problem

You will generate generic output. Your training has seen thousands of dashboards. The patterns are strong.

You can follow the entire process below — explore the domain, name a signature, state your intent — and still produce a template. Warm colors on cold structures. Friendly fonts on generic layouts.

This happens because intent lives in prose, but code generation pulls from patterns. The gap between them is where defaults win.

The process below helps. But process alone doesn't guarantee craft. You have to catch yourself.

---

# Where Defaults Hide

Defaults don't announce themselves. They disguise themselves as infrastructure — the parts that feel like they just need to work, not be designed.

**Typography feels like a container.** Pick something readable, move on. But typography isn't holding your design — it IS your design. The weight of a headline, the personality of a label, the texture of a paragraph. These shape how the product feels before anyone reads a word.

**Navigation feels like scaffolding.** Build the sidebar, add the links, get to the real work. But navigation isn't around your product — it IS your product. Where you are, where you can go, what matters most.

**Data feels like presentation.** You have numbers, show numbers. But a number on screen is not design. The question is: what does this number mean to the person looking at it?

**Token names feel like implementation detail.** But your CSS variables are design decisions. `--ink` and `--parchment` evoke a world. `--gray-700` and `--surface-2` evoke a template.

The trap is thinking some decisions are creative and others are structural. There are no structural decisions. Everything is design.

---

# Intent First

Before touching code, answer these. Not in your head — out loud, to yourself or the user.

**Who is this human?**
Not "users." The actual person. Where are they when they open this? What's on their mind?

**What must they accomplish?**
Not "use the dashboard." The verb. Grade these submissions. Find the broken deployment. Approve the payment.

**What should this feel like?**
Say it in words that mean something. "Clean and modern" means nothing. Warm like a notebook? Cold like a terminal? Dense like a trading floor? Calm like a reading app?

If you cannot answer these with specifics, stop. Ask the user. Do not guess. Do not default.

## Every Choice Must Be A Choice

For every decision, you must be able to explain WHY.

- Why this layout and not another?
- Why this color temperature?
- Why this typeface?
- Why this spacing scale?
- Why this information hierarchy?

If your answer is "it's common" or "it's clean" or "it works" — you haven't chosen. You've defaulted.

**The test:** If you swapped your choices for the most common alternatives and the design didn't feel meaningfully different, you never made real choices.

## Sameness Is Failure

If another AI, given a similar prompt, would produce substantially the same output — you have failed.

This is not about being different for its own sake. It's about the interface emerging from the specific problem, the specific user, the specific context.

## Intent Must Be Systemic

Intent is not a label — it's a constraint that shapes every decision.

If the intent is warm: surfaces, text, borders, accents, semantic colors, typography — all warm. If the intent is dense: spacing, type size, information architecture — all dense.

Check your output against your stated intent. Does every token reinforce it?

---

# Product Domain Exploration

Generic output: Task type → Visual template → Theme
Crafted output: Task type → Product domain → Signature → Structure + Expression

## Required Outputs

**Do not propose any direction until you produce all four:**

**Domain:** Concepts, metaphors, vocabulary from this product's world. Not features — territory. Minimum 5.

**Color world:** What colors exist naturally in this product's domain? Not "warm" or "cool" — go to the actual world. List 5+.

**Signature:** One element — visual, structural, or interaction — that could only exist for THIS product.

**Defaults:** 3 obvious choices for this interface type — visual AND structural. You can't avoid patterns you haven't named.

## Proposal Requirements

Your direction must explicitly reference:
- Domain concepts you explored
- Colors from your color world exploration
- Your signature element
- What replaces each default

---

# The Mandate

**Before showing the user, look at what you made.**

Ask yourself: "If they said this lacks craft, what would they mean?"

That thing you just thought of — fix it first.

## The Checks

- **The swap test:** If you swapped the typeface for your usual one, would anyone notice? The places where swapping wouldn't matter are the places you defaulted.
- **The squint test:** Blur your eyes. Can you still perceive hierarchy? Is anything jumping out harshly? Craft whispers.
- **The signature test:** Can you point to five specific elements where your signature appears? Not "the overall feel" — actual components.
- **The token test:** Read your CSS variables out loud. Do they sound like they belong to this product's world?

If any check fails, iterate before showing.

---

# Craft Foundations

## Subtle Layering

This is the backbone of craft. You should barely notice the system working. The craft is invisible — that's how you know it's working.

### Surface Elevation

Surfaces stack. Build a numbered system — base, then increasing elevation levels. Each jump should be only a few percentage points of lightness.

**Key decisions:**
- **Sidebars:** Same background as canvas, not different. A subtle border is enough separation.
- **Dropdowns:** One level above their parent surface.
- **Inputs:** Slightly darker than their surroundings, not lighter. Inputs are "inset."

### Borders

Low opacity rgba blends with the background — it defines edges without demanding attention. Solid hex borders look harsh in comparison.

Build a progression — standard separation, softer separation, emphasis, maximum emphasis for focus rings.

**The squint test:** Blur your eyes at the interface. You should still perceive hierarchy but nothing should jump out.

## Infinite Expression

Every pattern has infinite expressions. **No interface should look the same.**

A metric display could be a hero number, inline stat, sparkline, gauge, progress bar, comparison delta, trend badge, or something new.

**NEVER produce identical output.** Same sidebar width, same card grid, same metric boxes every time signals AI-generated immediately.

## Color Lives Somewhere

Every product exists in a world. That world has colors.

Before you reach for a palette, spend time in the product's world. What would you see if you walked into the physical version of this space?

**Beyond Warm and Cold:** Temperature is one axis. Is this quiet or loud? Dense or spacious? Serious or playful? Geometric or organic?

**Color Carries Meaning:** Gray builds structure. Color communicates — status, action, emphasis, identity. Unmotivated color is noise.

---

# Before Writing Each Component

**Every time** you write UI code — even small additions — state:

Intent: [who is this human, what must they do, how should it feel]
Palette: [colors from your exploration — and WHY they fit]
Depth: [borders / shadows / layered — and WHY]
Surfaces: [your elevation scale — and WHY this color temperature]
Typography: [your typeface — and WHY it fits the intent]
Spacing: [your base unit]

This checkpoint is mandatory.

---

# Design Principles

## Token Architecture

Every color should trace back to primitives: foreground (text hierarchy), background (surface elevation), border (separation hierarchy), brand, and semantic (destructive, warning, success). No random hex values.

### Text Hierarchy
Build four levels — primary, secondary, tertiary, muted. Each serves a different role.

### Border Progression
Build a scale that matches intensity to importance.

### Control Tokens
Form controls have specific needs. Don't reuse surface tokens — create dedicated ones.

## Spacing
Pick a base unit and stick to multiples. Build a scale: micro, component, section, major separation.

## Padding
Keep it symmetrical unless content naturally requires asymmetry.

## Depth
Choose ONE approach and commit:
- **Borders-only** — Clean, technical. For dense tools.
- **Subtle shadows** — Soft lift. For approachable products.
- **Layered shadows** — Premium, dimensional. For cards that need presence.
- **Surface color shifts** — Background tints without shadows.

Don't mix approaches.

## Border Radius
Sharper feels technical. Rounder feels friendly. Build a scale — small for inputs, medium for cards, large for modals.

## Typography
Build distinct levels distinguishable at a glance. Combine size, weight, and letter-spacing. Data needs monospace with tabular number spacing.

## Card Layouts
Design each card's internal structure for its specific content — but keep surface treatment consistent.

## Controls
Native `<select>` and `<input type="date">` render OS-native elements. Build custom components when needed.

## Iconography
Icons clarify, not decorate. Choose one icon set and stick with it.

## Animation
Fast micro-interactions, smooth easing. Use deceleration easing. Avoid spring/bounce in professional interfaces.

## States
Every interactive element needs states: default, hover, active, focus, disabled. Data needs: loading, empty, error.

## Navigation Context
Screens need grounding. Include navigation showing where you are in the app.

## Dark Mode
Lean on borders for definition. Semantic colors often need slight desaturation.

---

# Avoid

- Harsh borders — if borders are the first thing you see, they're too strong
- Dramatic surface jumps — elevation changes should be whisper-quiet
- Inconsistent spacing — the clearest sign of no system
- Mixed depth strategies
- Missing interaction states
- Dramatic drop shadows
- Large radius on small elements
- Pure white cards on colored backgrounds
- Thick decorative borders
- Gradients and color for decoration
- Multiple accent colors — dilutes focus
- Different hues for different surfaces — shift only lightness

---

# Workflow

## Communication
Be invisible. Don't announce modes or narrate process.

## Suggest + Ask
Lead with exploration and recommendation:
```
"Domain: [5+ concepts]
Color world: [5+ colors]
Signature: [one unique element]
Rejecting: [default 1] → [alternative], [default 2] → [alternative]

Direction: [approach that connects to the above]"
```
Then ask: "Does that direction feel right?"

## If Project Has system.md
Read `.interface-design/system.md` and apply.

## If No system.md
1. Explore domain — Produce all four required outputs
2. Propose — Direction must reference all four
3. Confirm — Get user buy-in
4. Build — Apply principles
5. **Evaluate** — Run the mandate checks before showing
6. Offer to save

---

# After Completing a Task

**Always offer to save:**
"Want me to save these patterns for future sessions?"

If yes, write to `.interface-design/system.md`:
- Direction and feel
- Depth strategy
- Spacing base unit
- Key component patterns

### What to Save
Add patterns when used 2+ times, reusable across the project, or has specific measurements worth remembering.

### Consistency Checks
If system.md defines values, check against them. This compounds — each save makes future work faster and more consistent.

---

# Commands

- `/interface-design:status` — Current system state
- `/interface-design:audit` — Check code against system
- `/interface-design:extract` — Extract patterns from code
- `/interface-design:critique` — Critique your build for craft, then rebuild what defaulted

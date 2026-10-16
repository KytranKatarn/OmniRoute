---
name: ui-designer
description: Extract design systems from reference UI images and generate implementation-ready UI design prompts. Use when users provide UI screenshots/mockups and want to create consistent designs, generate design systems, or build MVP UIs matching reference aesthetics.
---

# UI Designer

## Overview
Systematic extraction of design systems from reference UI images: analyze visual patterns, generate design system documentation, create PRD, produce implementation-ready UI prompts.

## When to Use
- User provides UI screenshots, mockups, or design references
- Need to extract color palettes, typography, spacing from existing designs
- Want to generate design system documentation from visual examples
- Building UI that should match reference aesthetics
- Creating multiple UI variations following consistent design principles

## Workflow

### Step 1: Gather Inputs
- **Reference images directory**: Path to folder containing UI screenshots/mockups
- **Project idea file**: Document describing the product concept and goals

### Step 2: Extract Design System from Images
Analyze reference images for:
- Color palettes (primary, secondary, accent, functional colors)
- Typography (font families, sizes, weights, line heights)
- Component styles (buttons, cards, inputs, icons)
- Spacing system
- Animations/transitions patterns
- Dark mode variants if present

Save to: `documents/designs/{image_dir_name}_design_system.md`

### Step 3: Generate PRD (if not provided)
Guide through: elevator pitch, problem statement, target audience, USP, features list, UX/UI considerations

### Step 4: Compose Final UI Implementation Prompt
Combine design system and PRD into implementation-ready prompt containing:
- Design aesthetics principles
- Project-specific color/typography guidelines
- App overview and feature requirements
- Implementation tasks

### Step 5: Implement UI
Use the composed prompt to implement. Create multiple design variations, organize as separate components.

## Best Practices

### Image Analysis
- Read all images before starting analysis
- Look for patterns across multiple screens
- Note both explicit styles and implicit principles
- Capture dark mode if present

### Design System Extraction
- Be systematic: cover all sections
- Use specific values (hex codes, px sizes) not generic descriptions
- Document the "why" for design choices when inferable
- Include variants (hover states, disabled states)

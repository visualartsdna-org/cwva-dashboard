# Visual Arts DNA Dashboard
## Project Handoff Document
**January 2026**

---

## Overview

This document provides a complete handoff for the Visual Arts DNA Function Dashboard (`function2.html`), a reorganized administrative interface for managing content, monitoring instances, and performing file operations.

### Project Summary

| Item | Details |
|------|---------|
| **Original File** | `function.html` - Basic HTML table layout |
| **New File** | `function2.html` - Modern tabbed dashboard |
| **Functionality** | All original endpoints preserved |
| **Compatibility** | Cross-platform (uses HTML entities for special characters) |

---

## File Structure

The dashboard is a single self-contained HTML file with embedded CSS and JavaScript.

| Section | Description |
|---------|-------------|
| `:root` CSS | CSS variables for colors, spacing, transitions |
| `<style>` | Component styles (header, cards, forms, tables) |
| `<header>` | Logo and tab navigation |
| `<main>` | Four tab content areas (Content, Monitoring, Tools, Files) |
| `<script>` | Tab switching, collapsible sections, helper functions |

---

## Tab Organization

### Content Tab
- **Content Management:** SPARQL, RDF Entry, RDF Digital, Proof, Entity, Interpretation, Related Concepts, Concepts, Brand Image, Store
- **Immediate Actions:** Distribute Data, Distribute Metadata
- **Author Documentation:** Account selector form
- **Keep Notes Import:** Google Takeout extraction form

### Monitoring Tab
- **Metrics &amp; Reports:** Stats charts and reports for all instances
- **Instance Control:** Status, Reload, Stats, Stop actions for each server

### Tools Tab
- **Utilities:** GUID generator, Registry printer
- **Certificate of Authenticity:** Generate certificates by GUID

### Files Tab
- **File Operations:** Load JSON/TTL files, Query TTL
- **SHACL Validation:** Validate TTL against SHACL shapes
- **Image Processing:** Scale and convert images
- **Image Synchronization:** Check sync and compare folders (collapsible section)

---

## Adding New Functions

### Method 1: Edit HTML Directly

Locate the appropriate tab section and add a new card to the `.card-grid`:

```html
<a href="your-endpoint" class="card cyan">
    <div class="card-title">Function Name</div>
    <div class="card-desc">Description here</div>
</a>
```

**Color options:** `blue`, `cyan`, `purple`, `orange`, `red`, `yellow`

### Method 2: JavaScript Helper

Use the `addFunctionCard()` helper at the bottom of the file:

```javascript
addFunctionCard({
    section: '#monitoring .card-grid',  // CSS selector for target grid
    href: 'https://visualartsdna.org/agentHealth',
    title: 'Agent Health',
    description: 'Ping the Claude agent',
    color: 'cyan'
});
```

### Adding New Server Instances

Use `addInstance()` for servers with Status/Reload/Stats/Stop controls:

```javascript
addInstance({
    name: 'new-server.com',
    tag: 'prod',
    url: 'https://new-server.com'
});
```

---

## Customization

### Theme Colors (CSS Variables)

All colors are defined in `:root` and can be easily modified:

| Variable | Value | Purpose |
|----------|-------|---------|
| `--bg-primary` | `#0a0a0f` | Page background |
| `--bg-secondary` | `#12121a` | Header background |
| `--bg-card` | `#1a1a24` | Card backgrounds |
| `--bg-card-hover` | `#22222e` | Card hover state |
| `--accent-blue` | `#4a9eff` | Primary accent color |
| `--accent-cyan` | `#00d4aa` | Secondary accent |
| `--accent-purple` | `#a855f7` | Tertiary accent |
| `--accent-orange` | `#ff8844` | Warning/action color |
| `--accent-red` | `#ff5566` | Danger/stop actions |
| `--accent-yellow` | `#ffc107` | Highlight color |
| `--text-primary` | `#e8e8ed` | Main text color |
| `--text-secondary` | `#9090a0` | Secondary text |
| `--text-muted` | `#606070` | Muted/label text |

---

## Technical Notes

### Character Encoding

All special characters use HTML entities for cross-platform compatibility (Windows/Mac/Linux). **Do not use emoji or Unicode characters directly.**

| Character | HTML Entity | Usage |
|-----------|-------------|-------|
| Right arrow (→) | `&#8594;` | Button labels |
| Bullet (•) | `&#8226;` | Separators in descriptions |
| Double arrow (↔) | `&#8596;` | Compare operations |
| Warning (⚠) | `&#9888;` | Warning messages |
| Reload (↻) | `&#8635;` | Reload buttons |
| Stop (■) | `&#9632;` | Stop buttons |
| Status (⊙) | `&#8857;` | Status buttons |
| Down arrow (CSS) | `\25BC` | Collapsible indicators |

### Section Icons

| Section | Entity | Symbol |
|---------|--------|--------|
| Content Management | `&#9998;` | ✎ |
| Immediate Actions | `&#9889;` | ⚡ |
| Author Documentation | `&#9787;` | ☻ |
| Keep Notes | `&#9733;` | ★ |
| Metrics | `&#9636;` | ▦ |
| Instance Control | `&#9881;` | ⚙ |
| Utilities | `&#9874;` | ⚒ |
| Certificate | `&#9001;` | 〈 |
| File Operations | `&#9776;` | ☰ |
| SHACL Validation | `&#10003;` | ✓ |
| Image Processing | `&#9724;` | ◼ |
| Synchronization | `&#8596;` | ↔ |

### Browser Compatibility

- Chrome (Windows, Mac, Linux) - **Tested**
- Firefox - Expected compatible
- Safari - Expected compatible
- Edge - Expected compatible

### Dependencies

- **Google Fonts:** Outfit (body text), JetBrains Mono (code/monospace)
- **Favicon:** https://visualartsdna.org/favicon.png

### Responsive Design

The dashboard includes CSS media queries for mobile devices (768px breakpoint). Cards stack vertically and forms adjust to full width on smaller screens.

---

## Server Instances Configured

| Instance | Tag | URL |
|----------|-----|-----|
| visualartsdna.org | instance-1 | https://visualartsdna.org |
| 34.72.230.88:8081 | instance-1 | http://34.72.230.88:8081 |
| localhost | pc | http://localhost |
| localhost:8080 | pc | http://localhost:8080 |

---

## File Locations

| File | Description |
|------|-------------|
| `function.html` | Original dashboard (keep as backup) |
| `function2.html` | New reorganized dashboard |

---

## Quick Reference: Adding a Function

**Example:** Add "Agent Health" to Monitoring tab

### Option A: HTML
```html
<!-- Add inside #monitoring .card-grid -->
<a href="https://visualartsdna.org/agentHealth" class="card cyan">
    <div class="card-title">Agent Health</div>
    <div class="card-desc">Ping the Claude agent</div>
</a>
```

### Option B: JavaScript
```javascript
// Add before closing </script> tag
addFunctionCard({
    section: '#monitoring .card-grid',
    href: 'https://visualartsdna.org/agentHealth',
    title: 'Agent Health',
    description: 'Ping the Claude agent',
    color: 'cyan'
});
```

---

*Generated by Claude - January 2026*

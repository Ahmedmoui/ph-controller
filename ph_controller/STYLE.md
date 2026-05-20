# Style Reference

Color tokens live in `static/css/theme.css`.
Change a value there and it applies across every page that loads the file.

## How to load it in a template
```html
<link rel="stylesheet" href="/static/css/theme.css">
```

## Token reference

| Variable | Default | Used for |
|---|---|---|
| `--bg-page` | `#0d1117` | Main page / chart background |
| `--bg-panel` | `#161b22` | Side panel, cards |
| `--bg-element` | `#21262d` | Buttons, inputs, badges |
| `--bg-hover` | `#30363d` | Hover state for clickable elements |
| `--border` | `#30363d` | Standard border on cards / inputs |
| `--border-faint` | `#21262d` | Divider lines (hr.rule) |
| `--text-bright` | `#e6edf3` | Headings, important values |
| `--text-body` | `#c9d1d9` | Normal body text |
| `--text-muted` | `#8b949e` | Labels, secondary info |
| `--blue` | `#58a6ff` | pH value display, links, focus rings |
| `--green` | `#56d364` | Running status, dosing badge |
| `--yellow` | `#e3b341` | Paused status, warnings |
| `--red` | `#f85149` | Stopped status, errors |
| `--btn-run` | `#238636` | Start / Run button background |
| `--btn-run-glow` | `#23863688` | Start button outer glow |
| `--btn-stop` | `#da3633` | Stop button background |
| `--btn-stop-glow` | `#da363388` | Stop button outer glow |
| `--chart-ph` | `#58a6ff` | pH line on the graph |
| `--chart-acid` | `#f85149` | Pump 1 (acid) line on the graph |
| `--chart-base` | `#56d364` | Pump 2 (base) line on the graph |
| `--chart-grid` | `#21262d` | Chart grid lines |

## Quick retheme examples

**Softer blue accent:**
```css
--blue: #79b8ff;
--chart-ph: #79b8ff;
```

**Higher contrast background:**
```css
--bg-page: #010409;
--bg-panel: #0d1117;
```

**Amber alert colors:**
```css
--btn-run: #9e6a03;
--btn-run-glow: #9e6a0388;
```
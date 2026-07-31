# Plan: port the claude-template design system to the Streamlit app

Status: phase 1 done 2026-07-31. Phases 2 to 4 outstanding.

## What we are porting

`C:\git\claude-template` is Vite + React + Tailwind 4 + shadcn/ui on the `radix-vega`
style with the `neutral` base colour. Its design system is four things:

1. **Colour tokens** in `src/index.css`, a `:root` block and a `.dark` block, all in
   `oklch()`. The palette is the Tailwind `neutral` ramp with one red `destructive`.
2. **Type**: Inter Variable (`@fontsource-variable/inter`), used for both body and
   headings (`--font-heading: var(--font-sans)`).
3. **Radius**: one `--radius: 0.625rem` token, with sm/md/lg/xl derived by multiplication.
4. **Component idiom**: card surfaces, `text-muted-foreground` labels, large
   `tabular-nums` values, subtle motion on mount (see `src/components/demo/stat-tile.tsx`).

The template's own rebrand instruction is "edit the `:root` and `.dark` variable blocks
only", so a faithful port means moving tokens, not copying components.

## Reality check: what Streamlit can and cannot take

Streamlit 1.60 (now our floor, see `requirements.txt`) has a real theming surface:
`[theme]`, `[theme.light]`, `[theme.dark]`, `[theme.sidebar]`, `[[theme.fontFaces]]`,
`baseRadius`, `buttonRadius`, and `chartCategoricalColors` which feeds Plotly, Altair
and Vega-Lite whenever `st.plotly_chart` runs with its default `theme="streamlit"`.

| Template feature | Ports to Streamlit | How |
|---|---|---|
| Colour tokens (light + dark) | Yes | `[theme.light]` / `[theme.dark]` in `.streamlit/config.toml` |
| Inter Variable | Yes | vendored `.ttf` + `[[theme.fontFaces]]` + `enableStaticServing` |
| `--radius: 0.625rem` | Yes | `baseRadius = "0.625rem"` |
| Chart palette | Yes | `chartCategoricalColors`, but see the open decision below |
| Card surfaces | Partly | `st.container(border=True)` plus a small CSS block |
| `tabular-nums`, muted labels | Partly | CSS on `st.metric` / container classes |
| Motion on mount, NumberFlow counters | No | no Streamlit equivalent; drop them |
| visx charts | No | we stay on Plotly; only the palette and font carry over |

Two gotchas found while checking:

- `config.toml` takes CSS colour strings; `oklch()` is not accepted, so tokens must be
  converted to hex first. Conversions are in the table below.
- Streamlit Cloud has no `node_modules`, so the Inter files must be committed under
  `static/` in this repo.

## Token conversion (oklch to hex)

The template's neutral ramp converts exactly onto Tailwind `neutral`, which is a useful
sanity check that nothing was lost in translation.

| Token | oklch | hex |
|---|---|---|
| background (light) | `oklch(1 0 0)` | `#ffffff` |
| foreground (light) | `oklch(0.145 0 0)` | `#0a0a0a` |
| secondary / muted / card-alt | `oklch(0.97 0 0)` | `#f5f5f5` |
| primary (light) | `oklch(0.205 0 0)` | `#171717` |
| primary-foreground | `oklch(0.985 0 0)` | `#fafafa` |
| muted-foreground | `oklch(0.556 0 0)` | `#737373` |
| border / input | `oklch(0.922 0 0)` | `#e5e5e5` |
| ring | `oklch(0.708 0 0)` | `#a1a1a1` |
| chart-1 … chart-5 | `0.87 / 0.556 / 0.439 / 0.371 / 0.269` | `#d4d4d4 #737373 #525252 #404040 #262626` |
| destructive (light / dark) | `0.577 0.245 27.325` / `0.704 0.191 22.216` | `#e7000b` / `#ff6467` |

Dark mode reuses the same ramp inverted: background `#262626`-adjacent, foreground
`#fafafa`, borders at 10 percent white.

## Open decision: the chart palette

**The template's `chart-1` through `chart-5` are five greys.** That works for a demo with
one or two series. This dashboard routinely plots seven lamb indicators on one axis, and
five greys will make them indistinguishable.

Three options, cheapest first:

1. **Neutral chrome, extended series palette (recommended).** Take the template's greys
   for UI surfaces, and define a separate accessible categorical ramp for
   `chartCategoricalColors`. Documented as a deliberate extension, not a deviation.
2. **Greyscale everywhere.** Faithful to the template, but caps usable series at about
   three. Would force a redesign of the Prices and Exports tabs around small multiples.
3. **Push the extension back upstream.** Add the categorical ramp to `claude-template`'s
   own tokens so both projects share it. Correct long term, extra coordination now.

Nothing else in this plan depends on which is chosen, so phases 1, 2 and 4 can start
before it is settled. Phase 3 cannot.

## Phases

Each phase is independently shippable and independently revertible.

### Phase 1: tokens (DONE, took about 30 min)

`.streamlit/config.toml` now carries `[theme]`, `[theme.light]`, `[theme.dark]` and both
sidebar variants, with `baseRadius = "0.625rem"` and `font = "sans-serif"` as a placeholder
until phase 2. No change to `app.py`. Verified by rendering both modes.

Two things learned:

- Once both `[theme.light]` and `[theme.dark]` exist, the app follows the **viewer's**
  colour-scheme preference. `base` and the `--theme.base` CLI flag no longer force a mode;
  to test dark, emulate `prefers-color-scheme: dark` in the browser or switch it in the
  app's Settings menu.
- Dark mode is now reachable by any viewer, which exposed the hardcoded colours in
  `app.py`: the range pills kept a light background with an indigo active state, and the
  Lead/Lag reference line was a fixed near-black that vanished on the dark background.
  Fixed since, ahead of phase 3: `theme_type()` reads `st.context.theme.type` and the pill
  and ink constants pick their light or dark token from it. Series colours still come from
  `PALETTE`, which phase 3 replaces.

### Phase 2: Inter Variable (about 30 min)

Copy `InterVariable.ttf` and `InterVariable-Italic.ttf` out of the template's
`node_modules/@fontsource-variable/inter` into `static/`, add `[server]
enableStaticServing = true`, declare `[[theme.fontFaces]]` for normal and italic, and set
`font = "inter"`. Commit the font files; note the licence (Inter is SIL OFL 1.1).

Verify: headings and body render in Inter, not the default sans stack.

### Phase 3: charts (about 1.5 h, blocked on the palette decision)

`app.py` still hardcodes its series colours: `PALETTE = px.colors.qualitative.Plotly` and a
`color_for()` helper wired into five chart builders. Explicit per-trace colours override
the theme, so the theme palette does nothing until these are removed. The pill and ink
constants are already token-driven and flip with `theme_type()`, so what remains here is
the palette decision.

1. Delete `PALETTE`; let `chartCategoricalColors` drive series colour. The pill constants
   are done.
2. Keep `color_for()` only where colour carries fixed meaning (price versus volume on the
   dual-axis Supply/Price chart), and point it at named tokens rather than palette indices.
3. Move gridline, axis and font styling onto the token values so charts match the app
   chrome in both light and dark mode.

Verify: every tab renders in both modes; the seven-lamb-indicator case stays readable.

### Phase 4: component idiom (about 2 h)

Replace the ad-hoc `<style>` block at `app.py:29` with one tokenised stylesheet, and move
the KPI row onto bordered containers matching the template's `StatTile`: muted label,
large `tabular-nums` value, card surface. Drop the mount animation and the animated
counter; neither has a Streamlit equivalent worth a dependency.

Verify: side-by-side screenshot against `claude-template`'s `dashboard-demo` page.

## Total

About 5 hours across four phases, or roughly 75 minutes for phases 1 and 2 alone, which
carry most of the visible change. Phases 1, 2 and 4 touch no data code, so they cannot
affect the refresh pipeline. Phase 3 touches only chart construction in `app.py`.

## Follow-up, not in scope here

The CPI and ABS tables added on 2026-07-31 still have no UI. Building those tabs after
phase 1 rather than before means they get the new tokens for free.

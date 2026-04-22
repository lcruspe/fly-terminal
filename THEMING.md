# Terminal theming

The public Railway port now serves a small web shell with a compact settings menu. The terminal itself is proxied under `/terminal/`.

## Fast switching

Open the app root:

```text
https://kruspe.up.railway.app/
```

Open the `Настройки` menu in the toolbar and use:

- color schemes: `Paper`, `Graphite`, `Amber`, `Midnight`, `Forest`, `Ocean`, `Rose`, `Nord`
- font sizes from `8px` to `14px`
- font families such as `JetBrains Mono`, `Fira Code`, `IBM Plex Mono`, `Source Code Pro`, `Cascadia Mono`

The choice is saved in browser `localStorage`, so the same browser opens the next session with the last selected theme, font size, and font family.

## Direct terminal links

The switcher builds a direct ttyd URL with query parameters. ttyd gives URL query parameters higher priority than server-side `-t` options, so links can override the default theme, font size, and font family:

```text
https://kruspe.up.railway.app/terminal/?fontSize=15&theme={"background":"#15171a","foreground":"#e6e0d4"}
```

For convenience, the app root accepts preset links:

```text
https://kruspe.up.railway.app/?preset=paper
https://kruspe.up.railway.app/?preset=graphite
https://kruspe.up.railway.app/?preset=amber
```

Opening one of these links stores that preset for the next browser session.

## Defaults

Set these in Railway service `Variables` only if you want to change the fallback defaults used before a browser preference exists:

```text
TERMINAL_FONT_SIZE=12
TERMINAL_FONT_FAMILY=JetBrains Mono, Menlo, Monaco, monospace
TERMINAL_THEME={"background":"#f7f3e8","foreground":"#28231f","cursor":"#c65f2f","selectionBackground":"#e7d6b3"}
```

## Session persistence

Switching a theme reloads the ttyd iframe. The container starts the shell through:

```text
tmux new-session -A -s fly-terminal
```

This keeps the terminal state attached to the same `tmux` session instead of creating a fresh empty shell on every theme switch.

## Mouse wheel

The container includes `/etc/tmux.conf` with mouse mode enabled. This makes mouse wheel events scroll the terminal/tmux history instead of being translated into shell `Up` / `Down` key presses.

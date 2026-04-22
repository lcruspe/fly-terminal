# Terminal theming

The public Railway port now serves a small web shell with a theme switcher. The terminal itself is proxied under `/terminal/`.

## Fast switching

Open the app root:

```text
https://kruspe.up.railway.app/
```

Use the toolbar buttons:

- `Paper`
- `Graphite`
- `Amber`
- `A-` / `A+`

The choice is saved in browser `localStorage`, so the same browser opens the next session with the last selected theme and font size.

## Independent tabs

Each browser tab gets its own `sessionStorage` id and passes it to ttyd as `?arg=...`. ttyd forwards that argument to `/usr/local/bin/terminal-session.sh`, which opens a separate `tmux` session for that tab.

That means:

- switching theme in one tab keeps that tab's shell state
- opening a second tab gives you a separate terminal, not a mirror of the first one

## Direct terminal links

The switcher builds a direct ttyd URL with query parameters. ttyd gives URL query parameters higher priority than server-side `-t` options, so links can override the default theme:

```text
https://kruspe.up.railway.app/terminal/?arg=tab-1&fontSize=15&theme={"background":"#15171a","foreground":"#e6e0d4"}
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
TERMINAL_FONT_SIZE=15
TERMINAL_FONT_FAMILY=JetBrains Mono, Menlo, Monaco, monospace
TERMINAL_THEME={"background":"#f7f3e8","foreground":"#28231f","cursor":"#c65f2f","selectionBackground":"#e7d6b3"}
```

## Mouse wheel

The container includes `/etc/tmux.conf` with mouse mode enabled. This makes mouse wheel events scroll the terminal/tmux history instead of being translated into shell `Up` / `Down` key presses.

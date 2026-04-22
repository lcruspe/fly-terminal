# Terminal theming

The web terminal is powered by `ttyd`, so theme values are passed to xterm.js through ttyd client options.

## Railway variables

Set these in Railway service `Variables`:

```text
TERMINAL_FONT_SIZE=15
TERMINAL_FONT_FAMILY=JetBrains Mono, Menlo, Monaco, monospace
TERMINAL_THEME={"background":"#f7f3e8","foreground":"#28231f","cursor":"#c65f2f","selectionBackground":"#e7d6b3"}
```

If `TERMINAL_THEME` is not set, the container uses the built-in light theme from `entrypoint.sh`.

## Dark theme example

```text
TERMINAL_THEME={"background":"#1f2430","foreground":"#d8dee9","cursor":"#88c0d0","selectionBackground":"#3b4252"}
```

## Notes

- Railway must redeploy the service after the commit or variable changes.
- Keep the JSON on one line when adding it to Railway Variables.
- The app still listens on Railway's `$PORT`; the theme change does not alter networking.

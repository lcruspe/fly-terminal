[ -f /etc/bash.bashrc ] && . /etc/bash.bashrc
if [ -f "$HOME/.bashrc" ] && [ "$HOME/.bashrc" != "/etc/fly-terminal.bashrc" ]; then
    . "$HOME/.bashrc"
fi

export HISTCONTROL=ignoredups:erasedups
export HISTSIZE="${FLY_TERMINAL_HISTSIZE:-5000}"
export HISTFILESIZE="${FLY_TERMINAL_HISTFILESIZE:-10000}"
shopt -s histappend

if [ -n "${HISTFILE:-}" ] && [ -f "$HISTFILE" ]; then
    history -r "$HISTFILE"
fi

# history -n removed from PROMPT_COMMAND: re-reading history on every Enter adds latency
# keeping only history -a (write to disk)
case ";${PROMPT_COMMAND:-};" in
    *";history -a;"*)  ;;
    *)
        PROMPT_COMMAND="history -a${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
        ;;
esac
export PROMPT_COMMAND

# Disable flow control (Ctrl+S/Q) - common cause of frozen input in browser terminals
stty -ixon 2>/dev/null || true

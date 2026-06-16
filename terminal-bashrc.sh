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

# --- Modern prompt ---
export PS1='\[\e[38;5;208m\]\u\[\e[0m\] \[\e[38;5;245m\]\w\[\e[0m\] \[\e[38;5;208m\]›\[\e[0m\] '
export CLICOLOR=1
export LSCOLORS=GxFxCxDxBxegedabagaced
alias ls='ls -G'
alias ll='ls -G -lh'
alias la='ls -G -A'

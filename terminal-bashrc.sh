[ -f /etc/bash.bashrc ] && . /etc/bash.bashrc

if [ -f "$HOME/.bashrc" ] && [ "$HOME/.bashrc" != "/etc/fly-terminal.bashrc" ]; then
    . "$HOME/.bashrc"
fi

export HISTCONTROL=ignoredups:erasedups
export HISTSIZE=100000
export HISTFILESIZE=200000

shopt -s histappend

if [ -n "${HISTFILE:-}" ] && [ -f "$HISTFILE" ]; then
    history -r "$HISTFILE"
fi

case ";${PROMPT_COMMAND};" in
    *";history -a; history -n;"*) ;;
    *)
        PROMPT_COMMAND="history -a; history -n${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
        ;;
esac

export PROMPT_COMMAND

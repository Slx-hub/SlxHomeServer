# SlxHomeServer – system-wide shell aliases
# Deployed to /etc/profile.d/slx-aliases.sh by setup.sh.
# Add or edit aliases here, then re-run setup.sh to apply.

# ── Navigation ───────────────────────────────────────────────────────────
alias ll='ls -hal'
alias la='ls -A'
alias l='ls -CF'
alias ..='cd ..'
alias ...='cd ../..'

# ── Safety nets ──────────────────────────────────────────────────────────
alias cp='cp -i'
alias mv='mv -i'
alias rm='rm -i'

# ── Convenience ──────────────────────────────────────────────────────────
alias grep='grep --color=auto'
alias df='df -h'
alias du='du -h'
alias free='free -h'
alias ports='ss -tulnp'
alias dps='docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'

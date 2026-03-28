# =============================================================================
# A2A Commerce Platform — Server Shell Config
# Deployed to /root/.bashrc by deploy.sh
# =============================================================================

# --- Prompt ---
# White text on blue background, hostname in green bg, path in magenta bg
PS1='\[\e[1;37;44m\] \u \[\e[0;30;42m\] \h \[\e[0;37;45m\] \w \[\e[0m\] \$ '

# --- Navigation ---
alias ..='cd ..'
alias ...='cd ../..'
alias a2a='cd /opt/a2a'
alias data='cd /var/lib/a2a'
alias logs='cd /var/log/a2a'

# --- Systemd ---
alias ss='systemctl status'
alias sr='systemctl restart'
alias se='systemctl enable'
alias sd='systemctl disable'
alias jf='journalctl -f'

# --- A2A service shortcuts ---
alias gw='systemctl status a2a-gateway'
alias gwr='systemctl restart a2a-gateway && echo "Restarted." && sleep 1 && systemctl status a2a-gateway --no-pager'
alias gwl='journalctl -u a2a-gateway -f'
alias gwlog='journalctl -u a2a-gateway --since "1 hour ago" --no-pager'
alias gwenv='${EDITOR:-nano} /opt/a2a/.env'

# --- Quick checks ---
alias health='curl -s http://localhost:8000/v1/health | python3 -m json.tool'
alias metrics='curl -s http://localhost:8000/v1/metrics'
alias pricing='curl -s http://localhost:8000/v1/pricing | python3 -m json.tool'

# --- Database ---
alias dbs='ls -lh /var/lib/a2a/*.db 2>/dev/null'
alias dbsize='du -sh /var/lib/a2a/*.db 2>/dev/null'
alias dbcheck='sqlite3 /var/lib/a2a/billing.db "PRAGMA integrity_check;"'

# --- Disk / system ---
alias df='df -h'
alias du='du -h'
alias free='free -h'
alias ports='ss -tlnp'
alias myip='curl -s4 ifconfig.me && echo'

# --- Safety ---
alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'

# --- Misc ---
alias ll='ls -lah --color=auto'
alias la='ls -A --color=auto'
alias l='ls -CF --color=auto'
alias grep='grep --color=auto'
alias h='history 25'
alias cls='clear'

# --- Functions ---

# Quick tool execution against local gateway
a2a_exec() {
    local tool="$1"; shift
    local params="${1:-{}}"
    local key
    key=$(grep '^API_KEY=' /opt/a2a/.env 2>/dev/null | cut -d= -f2)
    if [[ -z "$key" ]]; then
        echo "No API_KEY found in /opt/a2a/.env"
        return 1
    fi
    curl -s -X POST http://localhost:8000/v1/execute \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $key" \
        -d "{\"tool\":\"$tool\",\"params\":$params}" | python3 -m json.tool
}

# Tail gateway logs with optional grep filter
gwgrep() {
    if [[ -z "$1" ]]; then
        journalctl -u a2a-gateway -f
    else
        journalctl -u a2a-gateway -f | grep --line-buffered -i "$1"
    fi
}

# Backup all databases
backup_all() {
    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    local dest="/var/lib/a2a/backups/${ts}"
    mkdir -p "$dest"
    for db in /var/lib/a2a/*.db; do
        [[ -f "$db" ]] || continue
        sqlite3 "$db" ".backup '${dest}/$(basename "$db")'"
    done
    echo "Backed up to $dest"
    ls -lh "$dest"
}

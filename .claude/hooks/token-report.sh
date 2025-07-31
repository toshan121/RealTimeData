#!/usr/bin/env bash

# token-report.sh - Generate token usage reports for Claude Code

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common-helpers.sh"

# Load project configuration
load_project_config

main() {
    local days="${1:-7}"
    
    echo -e "${BLUE}🔍 Claude Code Token Usage Report${NC}"
    echo "================================================"
    
    if [[ ! -f "$SCRIPT_DIR/../token_usage.db" ]]; then
        echo -e "${YELLOW}No token usage data found. Run some Claude Code operations first.${NC}"
        echo "Initialize with: $SCRIPT_DIR/token-tracker.sh init"
        exit 0
    fi
    
    "$SCRIPT_DIR/token-tracker.sh" report "$days"
    
    echo ""
    echo -e "${CYAN}💡 Usage:${NC}"
    echo "  $0 [days]          - Show usage for last N days (default: 7)"
    echo "  $SCRIPT_DIR/token-tracker.sh init  - Initialize database"
    echo ""
    echo -e "${CYAN}Database location:${NC} $SCRIPT_DIR/../token_usage.db"
}

main "$@"
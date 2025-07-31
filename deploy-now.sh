#!/bin/bash
# Simple deployment script using SSH credentials from .env
set -e

# Load environment variables
if [ -f .env ]; then
    source .env
fi

# Configuration
TARGET_HOST="192.168.0.32"
TARGET_USER="${SSH_USER:-tcr1n15}"
REPO_URL="https://github.com/toshan121/RealTimeData.git"
PROJECT_DIR="RealTimeData"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Test SSH connection
test_ssh() {
    log_info "Testing SSH connection to $TARGET_USER@$TARGET_HOST..."
    
    if [ -z "$SSH_PASSWORD" ]; then
        log_error "SSH_PASSWORD not found in .env file"
        exit 1
    fi
    
    # Install sshpass if not available
    if ! command -v sshpass &> /dev/null; then
        log_info "Installing sshpass..."
        sudo apt-get update && sudo apt-get install -y sshpass
    fi
    
    # Test connection
    if sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$TARGET_USER@$TARGET_HOST" "echo 'SSH connection successful'"; then
        log_info "✅ SSH connection working"
    else
        log_error "❌ SSH connection failed"
        exit 1
    fi
}

# Deploy to target machine
deploy() {
    log_info "🚀 Deploying to $TARGET_HOST..."
    
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no "$TARGET_USER@$TARGET_HOST" << ENDSSH
        set -e
        
        echo "📦 Installing prerequisites..."
        # Update system (using password for sudo)
        echo "$SSH_PASSWORD" | sudo -S apt update
        
        # Install Docker if not present
        if ! command -v docker &> /dev/null; then
            echo "Installing Docker..."
            curl -fsSL https://get.docker.com -o get-docker.sh
            echo "$SSH_PASSWORD" | sudo -S sh get-docker.sh
            echo "$SSH_PASSWORD" | sudo -S usermod -aG docker \$USER
            rm get-docker.sh
        fi
        
        # Install Docker Compose if not present
        if ! command -v docker-compose &> /dev/null; then
            echo "Installing Docker Compose..."
            echo "$SSH_PASSWORD" | sudo -S curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-\$(uname -s)-\$(uname -m)" -o /usr/local/bin/docker-compose
            echo "$SSH_PASSWORD" | sudo -S chmod +x /usr/local/bin/docker-compose
        fi
        
        # Install Git if not present
        if ! command -v git &> /dev/null; then
            echo "Installing Git..."
            echo "$SSH_PASSWORD" | sudo -S apt install -y git
        fi
        
        echo "✅ Prerequisites installed"
        
        # Clone or update repository
        if [ -d "RealTimeData" ]; then
            echo "📂 Repository exists, updating..."
            cd RealTimeData
            git pull origin main
        else
            echo "📥 Cloning repository..."
            git clone https://github.com/toshan121/RealTimeData.git
            cd RealTimeData
        fi
        
        # Make scripts executable
        chmod +x deploy.sh
        
        # Run deployment
        ./deploy.sh
        
        echo "✅ Deployment complete!"
        echo "🌐 System accessible at: http://192.168.0.32:8080"
ENDSSH
    
    log_info "✅ Deployment finished!"
    log_info "🌐 Access your system at: http://192.168.0.32:8080"
}

# Check system status
check_status() {
    log_info "📊 Checking system status on $TARGET_HOST..."
    
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no "$TARGET_USER@$TARGET_HOST" << 'ENDSSH'
        cd RealTimeData 2>/dev/null || { echo "❌ Project not deployed yet"; exit 1; }
        
        echo "🐳 Docker Status:"
        docker-compose ps || echo "Docker services not running"
        
        echo ""
        echo "📊 System Monitor:"
        python monitor.py status 2>/dev/null || echo "Monitor not available"
        
        echo ""
        echo "🔗 Access URLs:"
        echo "  Web TUI: http://192.168.0.32:8080"
        echo "  ClickHouse: http://192.168.0.32:8123"
        echo "  Redis: 192.168.0.32:6380"
ENDSSH
}

# Check ClickHouse data
check_data() {
    log_info "🔍 Checking ClickHouse data and recording..."
    
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no "$TARGET_USER@$TARGET_HOST" << 'ENDSSH'
        cd RealTimeData 2>/dev/null || { echo "❌ Project not deployed"; exit 1; }
        
        echo "🗄️ ClickHouse Status:"
        docker-compose exec -T clickhouse clickhouse-client -q "SHOW DATABASES" 2>/dev/null || echo "ClickHouse not accessible"
        
        echo ""
        echo "📈 Market Data Tables:"
        docker-compose exec -T clickhouse clickhouse-client -q "SHOW TABLES FROM l2_market_data" 2>/dev/null || echo "Database not ready"
        
        echo ""
        echo "📊 Recent Data Count:"
        docker-compose exec -T clickhouse clickhouse-client -q "SELECT COUNT(*) as total_records FROM l2_market_data.l2_updates WHERE timestamp > now() - INTERVAL 1 HOUR" 2>/dev/null || echo "No recent data"
        
        echo ""
        echo "🎯 Recording Process:"
        ps aux | grep recording || echo "No recording process found"
ENDSSH
}

# Main menu
case "${1:-deploy}" in
    "deploy")
        test_ssh
        deploy
        ;;
    "status")
        test_ssh
        check_status
        ;;
    "data")
        test_ssh
        check_data
        ;;
    "test")
        test_ssh
        ;;
    *)
        echo "Usage: $0 [deploy|status|data|test]"
        echo ""
        echo "Commands:"
        echo "  deploy  - Deploy system to 192.168.0.32"
        echo "  status  - Check system status"
        echo "  data    - Check ClickHouse data and recording"
        echo "  test    - Test SSH connection"
        echo ""
        echo "Configuration from .env:"
        echo "  Target: $TARGET_USER@$TARGET_HOST"
        echo "  Repository: $REPO_URL"
        exit 1
        ;;
esac
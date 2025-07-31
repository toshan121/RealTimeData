#!/bin/bash
# Remote deployment script for 192.168.0.32
# Run this from your local machine to deploy to the target

set -e

# Configuration
TARGET_HOST="192.168.0.32"
TARGET_USER="your_username"  # Replace with actual username
REPO_URL="https://github.com/toshan121/RealTimeData.git"
PROJECT_DIR="RealTimeData"

# Colors for output
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

# Check SSH connectivity
check_ssh() {
    log_info "Testing SSH connection to $TARGET_HOST..."
    if ssh -o ConnectTimeout=10 -o BatchMode=yes "$TARGET_USER@$TARGET_HOST" exit 2>/dev/null; then
        log_info "✅ SSH connection successful"
    else
        log_error "❌ Cannot connect to $TARGET_HOST"
        log_error "Please ensure:"
        log_error "1. SSH keys are set up: ssh-copy-id $TARGET_USER@$TARGET_HOST"
        log_error "2. Target machine is accessible"
        log_error "3. Username is correct"
        exit 1
    fi
}

# Deploy to remote machine
deploy_remote() {
    log_info "🚀 Starting remote deployment to $TARGET_HOST..."
    
    # Create deployment script on remote machine
    ssh "$TARGET_USER@$TARGET_HOST" << 'ENDSSH'
        set -e
        
        # Update system packages
        sudo apt update
        
        # Install Docker if not present
        if ! command -v docker &> /dev/null; then
            echo "Installing Docker..."
            curl -fsSL https://get.docker.com -o get-docker.sh
            sudo sh get-docker.sh
            sudo usermod -aG docker $USER
            rm get-docker.sh
        fi
        
        # Install Docker Compose if not present
        if ! command -v docker-compose &> /dev/null; then
            echo "Installing Docker Compose..."
            sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
            sudo chmod +x /usr/local/bin/docker-compose
        fi
        
        # Install Git if not present
        if ! command -v git &> /dev/null; then
            echo "Installing Git..."
            sudo apt install -y git
        fi
        
        echo "✅ Prerequisites installed"
ENDSSH
    
    # Clone/update repository
    ssh "$TARGET_USER@$TARGET_HOST" << ENDSSH
        set -e
        
        if [ -d "$PROJECT_DIR" ]; then
            echo "Repository exists, updating..."
            cd "$PROJECT_DIR"
            git pull origin main
        else
            echo "Cloning repository..."
            git clone "$REPO_URL" "$PROJECT_DIR"
            cd "$PROJECT_DIR"
        fi
        
        # Make scripts executable
        chmod +x deploy.sh
        
        # Run deployment
        ./deploy.sh
        
        echo "🎉 Deployment complete!"
        echo "Access your system at: http://$TARGET_HOST:8080"
ENDSSH
    
    log_info "✅ Remote deployment complete!"
    log_info "🌐 Access your system at: http://$TARGET_HOST:8080"
}

# Show system status
show_remote_status() {
    log_info "Checking remote system status..."
    ssh "$TARGET_USER@$TARGET_HOST" << ENDSSH
        cd "$PROJECT_DIR" 2>/dev/null || { echo "Project not deployed yet"; exit 1; }
        docker-compose ps
        echo ""
        docker-compose exec -T app python monitor.py status 2>/dev/null || echo "Services starting..."
ENDSSH
}

# Stop remote services
stop_remote() {
    log_info "Stopping remote services..."
    ssh "$TARGET_USER@$TARGET_HOST" << ENDSSH
        cd "$PROJECT_DIR" 2>/dev/null || { echo "Project not found"; exit 1; }
        docker-compose down
        echo "✅ Services stopped"
ENDSSH
}

# View remote logs
show_remote_logs() {
    log_info "Showing remote logs (Ctrl+C to exit)..."
    ssh "$TARGET_USER@$TARGET_HOST" << ENDSSH
        cd "$PROJECT_DIR" 2>/dev/null || { echo "Project not found"; exit 1; }
        docker-compose logs -f
ENDSSH
}

# Main menu
case "${1:-deploy}" in
    "deploy")
        check_ssh
        deploy_remote
        ;;
    "status")
        check_ssh
        show_remote_status
        ;;
    "stop")
        check_ssh
        stop_remote
        ;;
    "logs")
        check_ssh
        show_remote_logs
        ;;
    "ssh")
        log_info "Opening SSH connection to $TARGET_HOST..."
        ssh "$TARGET_USER@$TARGET_HOST"
        ;;
    *)
        echo "Usage: $0 [deploy|status|stop|logs|ssh]"
        echo ""
        echo "Commands:"
        echo "  deploy  - Deploy to remote machine (default)"
        echo "  status  - Check remote system status"
        echo "  stop    - Stop remote services" 
        echo "  logs    - View remote logs"
        echo "  ssh     - Open SSH connection"
        echo ""
        echo "Configuration:"
        echo "  Target: $TARGET_USER@$TARGET_HOST"
        echo "  Repository: $REPO_URL"
        exit 1
        ;;
esac
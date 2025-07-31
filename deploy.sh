#!/bin/bash
# Deployment script for RealTime Data System
# Run this on your target machine

set -e  # Exit on any error

echo "🚀 RealTime Data System Deployment"
echo "=================================="

# Configuration
REPO_URL=""  # Will be set after GitHub setup
PROJECT_DIR="RealTimeData"
SERVICE_NAME="realtime-data-system"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    # Check Git
    if ! command -v git &> /dev/null; then
        log_error "Git is not installed. Please install Git first."
        exit 1
    fi
    
    log_info "✅ All prerequisites satisfied"
}

# Clone or update repository
setup_repository() {
    log_info "Setting up repository..."
    
    if [ -d "$PROJECT_DIR" ]; then
        log_info "Repository exists, updating..."
        cd "$PROJECT_DIR"
        git pull origin main
    else
        log_info "Cloning repository..."
        if [ -z "$REPO_URL" ]; then
            log_error "REPO_URL not set. Please set the GitHub repository URL."
            exit 1
        fi
        git clone "$REPO_URL" "$PROJECT_DIR"
        cd "$PROJECT_DIR"
    fi
}

# Setup environment
setup_environment() {
    log_info "Setting up environment..."
    
    # Create .env if it doesn't exist
    if [ ! -f .env ]; then
        log_info "Creating .env file..."
        cp .env.example .env
        log_warn "Please edit .env file with your configuration"
    fi
    
    # Create data directories
    mkdir -p data/raw_iqfeed
    mkdir -p logs
    
    log_info "✅ Environment setup complete"
}

# Start services
start_services() {
    log_info "Starting services..."
    
    # Stop any existing services
    docker-compose down 2>/dev/null || true
    
    # Build and start services
    docker-compose up -d --build
    
    # Wait for services to be ready
    log_info "Waiting for services to start..."
    sleep 30
    
    # Check service health
    if docker-compose exec -T app python monitor.py test; then
        log_info "✅ All services are running correctly"
    else
        log_warn "⚠️  Some services may not be fully ready (this is normal on first start)"
    fi
}

# Show status
show_status() {
    log_info "System Status:"
    echo "==============="
    
    # Docker containers
    docker-compose ps
    
    echo ""
    log_info "TUI Monitor Status:"
    docker-compose exec -T app python monitor.py status || true
    
    echo ""
    log_info "Access Points:"
    echo "• Web TUI: http://localhost:8080"
    echo "• Direct CLI: docker-compose exec app python monitor.py watch"
    echo "• Logs: docker-compose logs -f"
}

# Main deployment flow
main() {
    log_info "Starting deployment process..."
    
    check_prerequisites
    setup_repository
    setup_environment
    start_services
    show_status
    
    echo ""
    log_info "🎉 Deployment complete!"
    log_info "System is running at: http://localhost:8080"
    log_info "Use 'docker-compose logs -f' to view logs"
    log_info "Use 'docker-compose exec app python monitor.py watch' for live monitoring"
}

# Handle command line arguments
case "${1:-deploy}" in
    "deploy")
        main
        ;;
    "update")
        setup_repository
        start_services
        show_status
        ;;
    "status")
        show_status
        ;;
    "stop")
        log_info "Stopping services..."
        docker-compose down
        log_info "✅ Services stopped"
        ;;
    "logs")
        docker-compose logs -f
        ;;
    *)
        echo "Usage: $0 [deploy|update|status|stop|logs]"
        echo ""
        echo "Commands:"
        echo "  deploy  - Full deployment (default)"
        echo "  update  - Update code and restart services"
        echo "  status  - Show current status"
        echo "  stop    - Stop all services"
        echo "  logs    - Follow logs"
        exit 1
        ;;
esac
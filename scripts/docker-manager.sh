#!/bin/bash

# ============================================================================
# DOCKER MANAGER - Complete CLI Tool for Managing A.R.C.H.I.E. Containers
# Location: /mnt/archie_brain/scripts/docker-manager.sh
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Directories
ARCHIE_ROOT="/mnt/archie_brain"
PROD_COMPOSE="$ARCHIE_ROOT/docker-compose.yml"
TEST_COMPOSE="$ARCHIE_ROOT/docker-compose.test.yml"

# Helper functions
error() {
    echo -e "${RED}❌ Error: $1${NC}"
    exit 1
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check if docker-compose exists
check_dependencies() {
    if ! command -v docker-compose &> /dev/null; then
        error "docker-compose not found. Please install it."
    fi
    
    if ! command -v docker &> /dev/null; then
        error "docker not found. Please install it."
    fi
}

# Show usage
show_usage() {
    cat << EOF
🐳 A.R.C.H.I.E. Docker Manager

Usage: $0 [COMMAND] [OPTIONS]

COMMANDS:
  status              Show status of all containers
  start [ENV]         Start containers (prod/test)
  stop [ENV]          Stop containers (prod/test)
  restart [ENV]       Restart containers (prod/test)
  logs [SERVICE]      Show logs for service
  rebuild [SERVICE]   Rebuild service container
  clean               Remove all stopped containers
  prune               Clean up unused Docker resources
  ps                  List all running containers
  health              Check health of all services
  update              Pull latest images
  backup              Backup all containers (volumes + configs)
  
ENVIRONMENTS:
  prod                Production (port 3000)
  test                Test (port 6969)
  all                 Both environments

EXAMPLES:
  $0 status                    # Show all container status
  $0 start prod                # Start production
  $0 stop test                 # Stop test environment
  $0 logs archie_platform_v2   # Show platform logs
  $0 rebuild platform          # Rebuild platform container
  $0 health                    # Check service health

EOF
}

# Get compose file based on environment
get_compose_file() {
    local env=$1
    case $env in
        prod|production)
            echo "$PROD_COMPOSE"
            ;;
        test|testing)
            echo "$TEST_COMPOSE"
            ;;
        *)
            echo "$PROD_COMPOSE"
            ;;
    esac
}

# Status command
cmd_status() {
    info "Checking container status..."
    echo ""
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "PRODUCTION (Port 3000)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ -f "$PROD_COMPOSE" ]; then
        docker-compose -f "$PROD_COMPOSE" ps
    else
        warning "docker-compose.yml not found"
    fi
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "TEST (Port 6969)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ -f "$TEST_COMPOSE" ]; then
        docker-compose -f "$TEST_COMPOSE" ps
    else
        warning "docker-compose.test.yml not found"
    fi
}

# Start command
cmd_start() {
    local env=${1:-prod}
    local compose_file=$(get_compose_file "$env")
    
    info "Starting $env environment..."
    
    if [ ! -f "$compose_file" ]; then
        error "Compose file not found: $compose_file"
    fi
    
    cd "$ARCHIE_ROOT"
    docker-compose -f "$compose_file" up -d
    
    success "$env environment started!"
    info "Waiting for services to be ready..."
    sleep 5
    
    docker-compose -f "$compose_file" ps
}

# Stop command
cmd_stop() {
    local env=${1:-prod}
    local compose_file=$(get_compose_file "$env")
    
    info "Stopping $env environment..."
    
    if [ ! -f "$compose_file" ]; then
        error "Compose file not found: $compose_file"
    fi
    
    cd "$ARCHIE_ROOT"
    docker-compose -f "$compose_file" stop
    
    success "$env environment stopped!"
}

# Restart command
cmd_restart() {
    local env=${1:-prod}
    local compose_file=$(get_compose_file "$env")
    
    info "Restarting $env environment..."
    
    cd "$ARCHIE_ROOT"
    docker-compose -f "$compose_file" restart
    
    success "$env environment restarted!"
}

# Logs command
cmd_logs() {
    local service=${1:-}
    
    if [ -z "$service" ]; then
        info "Showing logs for all services (press Ctrl+C to exit)..."
        docker-compose -f "$PROD_COMPOSE" logs -f
    else
        info "Showing logs for $service (press Ctrl+C to exit)..."
        docker logs -f "$service"
    fi
}

# Rebuild command
cmd_rebuild() {
    local service=${1:-}
    local env=${2:-prod}
    local compose_file=$(get_compose_file "$env")
    
    if [ -z "$service" ]; then
        error "Please specify a service to rebuild"
    fi
    
    info "Rebuilding $service in $env environment..."
    
    cd "$ARCHIE_ROOT"
    
    # Stop service
    docker-compose -f "$compose_file" stop "$service"
    
    # Remove container
    docker rm "${service}" 2>/dev/null || true
    
    # Remove image
    docker rmi "archie_brain-${service}" 2>/dev/null || true
    
    # Rebuild
    docker-compose -f "$compose_file" build --no-cache "$service"
    
    # Start
    docker-compose -f "$compose_file" up -d "$service"
    
    success "$service rebuilt and started!"
}

# Clean command
cmd_clean() {
    info "Cleaning stopped containers..."
    
    docker container prune -f
    
    success "Stopped containers removed!"
}

# Prune command
cmd_prune() {
    warning "This will remove:"
    echo "  - All stopped containers"
    echo "  - All networks not used by at least one container"
    echo "  - All dangling images"
    echo "  - All build cache"
    echo ""
    read -p "Continue? (y/N) " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Pruning Docker system..."
        docker system prune -a -f
        success "Docker system pruned!"
    else
        info "Cancelled"
    fi
}

# PS command
cmd_ps() {
    info "All running containers:"
    echo ""
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
}

# Health command
cmd_health() {
    info "Checking service health..."
    echo ""
    
    # Platform
    echo -n "Platform (3000): "
    if curl -s http://localhost:3000/health > /dev/null 2>&1; then
        success "HEALTHY"
    else
        error "UNHEALTHY"
    fi
    
    # Test Platform
    echo -n "Test Platform (6969): "
    if curl -s http://localhost:6969/health > /dev/null 2>&1; then
        success "HEALTHY"
    else
        warning "NOT RUNNING"
    fi
    
    # Database
    echo -n "Database (5432): "
    if docker exec archie_database_v2 pg_isready -U archie > /dev/null 2>&1; then
        success "HEALTHY"
    else
        error "UNHEALTHY"
    fi
    
    # AI Bridge
    echo -n "AI Bridge (5500): "
    if curl -s http://localhost:5500/health > /dev/null 2>&1; then
        success "HEALTHY"
    else
        warning "NOT RUNNING"
    fi
    
    # Code Server
    echo -n "Code Server (8080): "
    if curl -s http://localhost:8080 > /dev/null 2>&1; then
        success "HEALTHY"
    else
        warning "NOT RUNNING"
    fi
}

# Update command
cmd_update() {
    info "Pulling latest images..."
    
    cd "$ARCHIE_ROOT"
    docker-compose -f "$PROD_COMPOSE" pull
    
    if [ -f "$TEST_COMPOSE" ]; then
        docker-compose -f "$TEST_COMPOSE" pull
    fi
    
    success "Images updated! Run 'restart' to use new images."
}

# Backup command
cmd_backup() {
    info "Creating container backup..."
    
    BACKUP_DIR="$ARCHIE_ROOT/backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # Backup volumes
    docker run --rm \
        -v archie_v2_db:/data \
        -v "$BACKUP_DIR":/backup \
        alpine tar czf /backup/database_volume.tar.gz -C /data .
    
    success "Backup created: $BACKUP_DIR"
}

# Main command dispatcher
main() {
    check_dependencies
    
    local command=${1:-}
    
    case $command in
        status)
            cmd_status
            ;;
        start)
            cmd_start "${2:-prod}"
            ;;
        stop)
            cmd_stop "${2:-prod}"
            ;;
        restart)
            cmd_restart "${2:-prod}"
            ;;
        logs)
            cmd_logs "$2"
            ;;
        rebuild)
            cmd_rebuild "$2" "${3:-prod}"
            ;;
        clean)
            cmd_clean
            ;;
        prune)
            cmd_prune
            ;;
        ps)
            cmd_ps
            ;;
        health)
            cmd_health
            ;;
        update)
            cmd_update
            ;;
        backup)
            cmd_backup
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            if [ -z "$command" ]; then
                show_usage
            else
                error "Unknown command: $command"
            fi
            ;;
    esac
}

# Run main
main "$@"

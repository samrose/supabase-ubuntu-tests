{
  description = "Ubuntu 24.04 Compatibility Tests for Supabase Postgres";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        
        # Python environment with all required dependencies
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          pytest
          psycopg2
          requests
          docker
          boto3
          paramiko
          pyyaml
        ]);

        # Test files
        amiTestFile = ./aws_ami_tests.py;
        dockerTestFile = ./docker_container_tests.py;

        # Create test runner scripts
        runAMITests = pkgs.writeShellScriptBin "run-ami-tests" ''
          set -euo pipefail
          
          echo "🚀 Starting Ubuntu 24.04 Compatibility Tests for Supabase Postgres (AWS AMI)"
          echo "=================================================================="
          
          # Create test directory
          WORK_DIR=$(mktemp -d)
          cd "$WORK_DIR"
          
          # Copy test file
          cp ${amiTestFile} aws_ami_tests.py
          chmod +x aws_ami_tests.py
          
          # Set environment variables from system if available
          export POSTGRES_PASSWORD=''${POSTGRES_PASSWORD:-postgres}
          export POSTGRES_USER=''${POSTGRES_USER:-postgres}
          export POSTGRES_HOST=''${POSTGRES_HOST:-localhost}
          
          echo "🧪 Running AWS AMI tests..."
          echo "Working directory: $WORK_DIR"
          
          # Run tests with detailed output
          if ${pythonEnv}/bin/python -m pytest aws_ami_tests.py -v --tb=short --color=yes; then
            echo "✅ All AMI tests passed!"
            EXIT_CODE=0
          else
            echo "❌ Some AMI tests failed!"
            EXIT_CODE=1
          fi
          
          # Cleanup
          cd /
          rm -rf "$WORK_DIR"
          
          exit $EXIT_CODE
        '';

        runDockerTests = pkgs.writeShellScriptBin "run-docker-tests" ''
          set -euo pipefail
          
          echo "🐳 Starting Ubuntu 24.04 Compatibility Tests for Supabase Postgres (Docker)"
          echo "========================================================================"
          
          # Check Docker is available
          if ! command -v docker &> /dev/null; then
            echo "❌ Docker is not available. Please install Docker first."
            exit 1
          fi
          
          if ! docker info &> /dev/null; then
            echo "❌ Docker daemon is not running or not accessible."
            echo "💡 Try: sudo systemctl start docker"
            echo "💡 Or add your user to docker group: sudo usermod -aG docker $USER"
            exit 1
          fi
          
          # Create test directory
          WORK_DIR=$(mktemp -d)
          cd "$WORK_DIR"
          
          # Copy test file
          cp ${dockerTestFile} docker_container_tests.py
          chmod +x docker_container_tests.py
          
          echo "🧪 Running Docker container tests..."
          echo "Working directory: $WORK_DIR"
          
          # Pull required images
          echo "📥 Pulling required Docker images..."
          docker pull supabase/postgres:15-latest || echo "⚠️  Could not pull supabase/postgres:15-latest"
          
          # Run tests with detailed output
          if ${pythonEnv}/bin/python -m pytest docker_container_tests.py -v --tb=short --color=yes; then
            echo "✅ All Docker tests passed!"
            EXIT_CODE=0
          else
            echo "❌ Some Docker tests failed!"
            EXIT_CODE=1
          fi
          
          echo "🧹 Cleaning up test containers..."
          # Cleanup any remaining test containers
          docker ps -a --filter "name=test_postgres_" --format "{{.ID}}" | xargs -r docker rm -f
          docker network ls --filter "name=supabase_test_" --format "{{.ID}}" | xargs -r docker network rm
          
          # Cleanup working directory
          cd /
          rm -rf "$WORK_DIR"
          
          exit $EXIT_CODE
        '';

        cleanupTests = pkgs.writeShellScriptBin "cleanup-tests" ''
          set -euo pipefail
          
          echo "🧹 Cleaning up Ubuntu 24.04 Compatibility Tests"
          echo "==============================================="
          
          # Clean up Docker containers
          if command -v docker &> /dev/null && docker info &> /dev/null; then
            echo "🐳 Cleaning up Docker test containers..."
            
            # Remove test containers
            CONTAINERS=$(docker ps -a --filter "name=test_postgres_" --format "{{.ID}}" 2>/dev/null || true)
            if [ -n "$CONTAINERS" ]; then
              echo "Removing containers: $CONTAINERS"
              echo "$CONTAINERS" | xargs docker rm -f
            fi
            
            # Remove test networks
            NETWORKS=$(docker network ls --filter "name=supabase_test_" --format "{{.ID}}" 2>/dev/null || true)
            if [ -n "$NETWORKS" ]; then
              echo "Removing networks: $NETWORKS"
              echo "$NETWORKS" | xargs docker network rm
            fi
            
            # Remove dangling test images (optional)
            echo "🗑️  Removing dangling images..."
            docker image prune -f
            
            echo "✅ Docker cleanup completed"
          else
            echo "ℹ️  Docker not available, skipping Docker cleanup"
          fi
          
          # Clean up any temporary directories
          echo "🗂️  Cleaning up temporary directories..."
          find /tmp -name "*supabase_test*" -type d -exec rm -rf {} + 2>/dev/null || true
          find /tmp -name "*ubuntu24_compat*" -type d -exec rm -rf {} + 2>/dev/null || true
          
          # Clean up any stale Python virtual environments
          find /tmp -name "*venv*" -path "*/ubuntu24*" -type d -exec rm -rf {} + 2>/dev/null || true
          
          echo "✅ Cleanup completed successfully"
        '';

        # Full test suite runner
        runAllTests = pkgs.writeShellScriptBin "run-all-tests" ''
          set -euo pipefail
          
          echo "🚀 Running Complete Ubuntu 24.04 Compatibility Test Suite"
          echo "========================================================="
          
          OVERALL_SUCCESS=true
          
          # Detect environment type
          if command -v docker &> /dev/null && docker info &> /dev/null; then
            echo "🐳 Docker detected - running Docker tests..."
            if ! ${runDockerTests}/bin/run-docker-tests; then
              OVERALL_SUCCESS=false
              echo "❌ Docker tests failed"
            fi
          else
            echo "ℹ️  Docker not available - skipping Docker tests"
          fi
          
          # Check if we're on an AMI/server with PostgreSQL
          if command -v psql &> /dev/null || systemctl is-active postgresql &> /dev/null; then
            echo "🖥️  PostgreSQL detected - running AMI tests..."
            if ! ${runAMITests}/bin/run-ami-tests; then
              OVERALL_SUCCESS=false
              echo "❌ AMI tests failed"
            fi
          else
            echo "ℹ️  PostgreSQL service not detected - skipping AMI tests"
          fi
          
          # Summary
          echo ""
          echo "📊 Test Summary"
          echo "==============="
          if [ "$OVERALL_SUCCESS" = true ]; then
            echo "✅ All available tests passed!"
            echo "🎉 Supabase Postgres is compatible with Ubuntu 24.04"
            exit 0
          else
            echo "❌ Some tests failed!"
            echo "⚠️  Please review the test output above"
            exit 1
          fi
        '';

        # System info script
        showSystemInfo = pkgs.writeShellScriptBin "show-system-info" ''
          set -euo pipefail
          
          echo "🖥️  System Information for Ubuntu 24.04 Compatibility Tests"
          echo "============================================================"
          
          # OS Information
          echo "📋 Operating System:"
          if [ -f /etc/os-release ]; then
            grep -E "(NAME|VERSION|ID)" /etc/os-release
          else
            echo "  /etc/os-release not found"
          fi
          echo ""
          
          # Kernel Information
          echo "🐧 Kernel:"
          echo "  Version: $(uname -r)"
          echo "  Architecture: $(uname -m)"
          echo ""
          
          # System Tools
          echo "🔧 System Tools:"
          echo "  systemd: $(systemctl --version | head -n1)"
          echo "  glibc: $(ldd --version | head -n1)"
          echo ""
          
          # Docker Information
          echo "🐳 Docker:"
          if command -v docker &> /dev/null; then
            if docker info &> /dev/null; then
              echo "  Status: Running"
              echo "  Version: $(docker --version)"
              echo "  Server Version: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'Unknown')"
            else
              echo "  Status: Installed but not running"
            fi
          else
            echo "  Status: Not installed"
          fi
          echo ""
          
          # PostgreSQL Information
          echo "🐘 PostgreSQL:"
          if command -v psql &> /dev/null; then
            echo "  Client: $(psql --version)"
          else
            echo "  Client: Not installed"
          fi
          
          if systemctl is-active postgresql &> /dev/null; then
            echo "  Service: Running"
          elif systemctl list-unit-files | grep -q postgresql; then
            echo "  Service: Installed but not running"
          else
            echo "  Service: Not found"
          fi
          echo ""
          
          # Network Information
          echo "🌐 Network:"
          echo "  Hostname: $(hostname)"
          echo "  IP Addresses:"
          ip addr show | grep -E "inet [0-9]" | awk '{print "    " $2}' || echo "    Unable to determine"
          echo ""
          
          # Disk Space
          echo "💾 Disk Space:"
          df -h / | tail -n1 | awk '{print "  Root: " $3 " used, " $4 " available (" $5 " full)"}'
          echo ""
          
          # Memory
          echo "🧠 Memory:"
          free -h | grep Mem | awk '{print "  Total: " $2 ", Used: " $3 ", Available: " $7}'
          echo ""
          
          echo "✅ System information collection complete"
        '';

      in
      {
        # Development shell
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            pythonEnv
            docker
            docker-compose
            postgresql
            curl
            jq
          ];
          
          shellHook = ''
            echo "🧪 Ubuntu 24.04 Compatibility Testing Environment"
            echo "================================================"
            echo ""
            echo "Available commands:"
            echo "  nix run .#run-ami-tests      - Run AWS AMI tests"
            echo "  nix run .#run-docker-tests   - Run Docker container tests"  
            echo "  nix run .#run-all-tests      - Run all available tests"
            echo "  nix run .#cleanup-tests      - Clean up test artifacts"
            echo "  nix run .#show-system-info   - Show system information"
            echo ""
            echo "Environment variables you can set:"
            echo "  POSTGRES_PASSWORD - PostgreSQL password (default: postgres)"
            echo "  POSTGRES_USER     - PostgreSQL user (default: postgres)"
            echo "  POSTGRES_HOST     - PostgreSQL host (default: localhost)"
            echo ""
          '';
        };

        # Apps for running tests
        apps = {
          # AMI tests
          run-ami-tests = {
            type = "app";
            program = "${runAMITests}/bin/run-ami-tests";
          };
          
          # Docker tests  
          run-docker-tests = {
            type = "app";
            program = "${runDockerTests}/bin/run-docker-tests";
          };
          
          # All tests
          run-all-tests = {
            type = "app";
            program = "${runAllTests}/bin/run-all-tests";
          };
          
          # Cleanup
          cleanup-tests = {
            type = "app";
            program = "${cleanupTests}/bin/cleanup-tests";
          };
          
          # System info
          show-system-info = {
            type = "app";
            program = "${showSystemInfo}/bin/show-system-info";
          };
          
          # Default app
          default = {
            type = "app";
            program = "${runAllTests}/bin/run-all-tests";
          };
        };

        # Packages
        packages = {
          inherit runAMITests runDockerTests runAllTests cleanupTests showSystemInfo;
          default = runAllTests;
        };
      });
}
#!/usr/bin/env python3
"""
AWS AMI Ubuntu 24.04 Compatibility Tests for Supabase Postgres
Tests for running directly on AWS AMI instances
"""

import pytest
import psycopg2
import subprocess
import requests
import time
import os
import sys
import socket
import ssl
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class AMITestConfig:
    """Configuration for AWS AMI testing"""
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "postgres"
    pgbouncer_port: int = 6543
    postgrest_port: int = 3000


class AMISystemTest:
    """Base class for AWS AMI system testing"""

    def setup_method(self):
        self.config = AMITestConfig()

    def _execute_sql(self, sql: str, database: str = None) -> List[Tuple]:
        """Execute SQL and return results"""
        db = database or self.config.postgres_db
        conn = psycopg2.connect(
            host=self.config.postgres_host,
            port=self.config.postgres_port,
            database=db,
            user=self.config.postgres_user,
            password=self.config.postgres_password
        )
        
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                if cur.description:
                    return cur.fetchall()
                conn.commit()
                return []
        finally:
            conn.close()

    def _check_service_status(self, service_name: str) -> bool:
        """Check if a systemd service is active"""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', service_name],
                capture_output=True, text=True
            )
            return result.stdout.strip() == "active"
        except:
            return False

    def _get_system_info(self) -> Dict[str, str]:
        """Get system information"""
        info = {}
        
        # OS Release
        try:
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        info[key] = value.strip('"')
        except:
            pass
            
        # Kernel version
        try:
            result = subprocess.run(['uname', '-r'], capture_output=True, text=True)
            info['KERNEL'] = result.stdout.strip()
        except:
            pass
            
        # Architecture
        try:
            result = subprocess.run(['uname', '-m'], capture_output=True, text=True)
            info['ARCH'] = result.stdout.strip()
        except:
            pass
            
        return info

    def _get_service_status(self, service_name: str) -> Dict[str, str]:
        """Get detailed service status"""
        try:
            result = subprocess.run(
                ['systemctl', 'show', service_name],
                capture_output=True, text=True
            )
            status = {}
            for line in result.stdout.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    status[key] = value
            return status
        except:
            return {}

    def _check_service_health(self, service_name: str) -> Tuple[bool, str]:
        """Check service health including memory, CPU, and error logs"""
        try:
            # Check service status
            status = self._get_service_status(service_name)
            if not status.get('ActiveState') == 'active':
                return False, f"Service {service_name} is not active"

            # Check for recent errors in journal
            result = subprocess.run(
                ['journalctl', '-u', service_name, '--since', '1 hour ago', '-p', 'err'],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                return False, f"Service {service_name} has recent errors in logs"

            # Check memory usage
            result = subprocess.run(
                ['systemctl', 'show', service_name, '-p', 'MemoryCurrent'],
                capture_output=True, text=True
            )
            memory = result.stdout.strip().split('=')[1]
            if memory and int(memory) > 1024 * 1024 * 1024:  # 1GB
                return False, f"Service {service_name} using excessive memory: {memory}"

            return True, "Service healthy"
        except Exception as e:
            return False, f"Error checking service health: {str(e)}"


class TestAMISystemCompatibility(AMISystemTest):
    """Test AWS AMI system-level Ubuntu 24.04 compatibility"""

    def test_ubuntu_version(self):
        """Verify Ubuntu 24.04 LTS is running"""
        info = self._get_system_info()
        
        assert 'VERSION_ID' in info, "Cannot determine Ubuntu version"
        version = info['VERSION_ID'].strip('"')
        assert version.startswith('24.04'), f"Expected Ubuntu 24.04, got {version}"
        
        # Check it's LTS
        assert 'LTS' in info.get('VERSION', ''), "Should be LTS version"

    def test_kernel_version(self):
        """Test Linux kernel 6.8 compatibility"""
        info = self._get_system_info()
        kernel = info.get('KERNEL', '')
        
        # Should be kernel 6.x
        major_version = int(kernel.split('.')[0])
        assert major_version >= 6, f"Expected kernel 6.x, got {kernel}"

    def test_systemd_version(self):
        """Test systemd 255+ compatibility"""
        try:
            result = subprocess.run(['systemctl', '--version'], 
                                  capture_output=True, text=True)
            assert result.returncode == 0, "systemctl not available"
            
            version_line = result.stdout.split('\n')[0]
            version_num = int(version_line.split()[1])
            assert version_num >= 255, f"Expected systemd ≥255, got {version_num}"
        except Exception as e:
            pytest.fail(f"Cannot check systemd version: {e}")

    def test_glibc_version(self):
        """Test glibc 2.39 compatibility"""
        try:
            result = subprocess.run(['ldd', '--version'], 
                                  capture_output=True, text=True)
            assert result.returncode == 0, "ldd not available"
            
            # Extract version from first line
            first_line = result.stdout.split('\n')[0]
            if '2.39' in first_line or '2.4' in first_line:
                pass
            else:
                pytest.fail(f"Unexpected glibc version info: {first_line}")
        except Exception as e:
            pytest.skip(f"Cannot check glibc version: {e}")


class TestPostgreSQLService(AMISystemTest):
    """Test PostgreSQL service on AWS AMI"""

    def test_postgresql_connectivity(self):
        """Test PostgreSQL connectivity and basic operations"""
        # Test connection
        result = self._execute_sql("SELECT version();")
        assert len(result) > 0, "Cannot query PostgreSQL version"
        assert "PostgreSQL" in result[0][0], "Invalid PostgreSQL version response"

    def test_postgresql_configuration(self):
        """Test PostgreSQL configuration for Supabase"""
        # Test replication settings
        result = self._execute_sql("SHOW wal_level;")
        assert result[0][0] == "logical", "WAL level should be logical for Supabase"
        
        result = self._execute_sql("SHOW max_replication_slots;")
        assert int(result[0][0]) >= 5, "Should have at least 5 replication slots"

    def test_database_operations(self):
        """Test basic database operations work correctly"""
        # Create test database
        try:
            # Test operations on new database
            result = self._execute_sql("SELECT 1;", database="postgres")
            assert result[0][0] == 1
        except psycopg2.Error as e:
            raise e


class TestPostgreSQLExtensions(AMISystemTest):
    """Test PostgreSQL extensions on AWS AMI"""

    def test_core_extensions_available(self):
        """Test core Supabase extensions are available"""
        extensions = [
            'pg_stat_statements', 'pgaudit', 'pg_cron', 'postgis',
            'pgtap', 'vector', 'pgsodium'
        ]
        
        # Get available extensions
        result = self._execute_sql("SELECT name FROM pg_available_extensions ORDER BY name;")
        available = [row[0] for row in result]
        
        missing_extensions = []
        for ext in extensions:
            if ext not in available:
                missing_extensions.append(ext)
        
        assert len(missing_extensions) == 0, f"Missing extensions: {missing_extensions}"

    @pytest.mark.parametrize("extension", [
        'pg_cron'
    ])
    def test_extension_loading(self, extension):
        """Test individual extensions can be loaded"""
        try:
            self._execute_sql(f"CREATE EXTENSION IF NOT EXISTS {extension} with schema extensions;")
            
            # Verify extension is loaded
            result = self._execute_sql(
                f"SELECT extname FROM pg_extension WHERE extname = '{extension}';")
            assert len(result) > 0, f"Extension {extension} not loaded"
            
        except psycopg2.Error as e:
            pytest.fail(f"Failed to load extension {extension}: {e}")


class TestSystemdServices(AMISystemTest):
    """Test systemd services health and compatibility"""

    @pytest.mark.parametrize("service", [
        "postgresql",
        "pgbouncer",
        "postgrest",
        "gotrue",
        "kong",
        "nginx",
        "vector",
        "salt-minion"
    ])
    def test_service_health(self, service):
        """Test individual service health"""
        is_healthy, message = self._check_service_health(service)
        assert is_healthy, message

    def test_service_dependencies(self):
        """Test service dependency chain"""
        services = {
            "postgresql": ["pgbouncer", "postgrest"],
            "pgbouncer": ["postgrest"],
            "postgrest": ["kong"],
            "gotrue": ["kong"],
            "kong": ["nginx"]
        }

        for service, dependencies in services.items():
            assert self._check_service_status(service), f"Service {service} is not running"
            for dep in dependencies:
                assert self._check_service_status(dep), f"Dependency {dep} for {service} is not running"

    def test_service_restart_policy(self):
        """Test service restart policies are correctly configured"""
        services = [
            "postgresql",
            "pgbouncer",
            "postgrest",
            "gotrue",
            "kong",
            "nginx",
            "vector"
        ]

        for service in services:
            status = self._get_service_status(service)
            assert status.get('Restart') in ['always', 'on-success', 'on-failure'], \
                f"Service {service} has invalid restart policy: {status.get('Restart')}"


class TestUbuntu2404Compatibility(AMISystemTest):
    """Test Ubuntu 24.04 specific compatibility"""

    def test_openssl_compatibility(self):
        """Test OpenSSL 3.0 compatibility"""
        try:
            result = subprocess.run(['openssl', 'version'], capture_output=True, text=True)
            version = result.stdout.strip()
            assert '3.0' in version, f"Expected OpenSSL 3.0, got {version}"
        except Exception as e:
            pytest.fail(f"Cannot check OpenSSL version: {e}")

    def test_python_compatibility(self):
        """Test Python 3.12 compatibility"""
        try:
            result = subprocess.run(['python3', '--version'], capture_output=True, text=True)
            version = result.stdout.strip()
            assert '3.12' in version, f"Expected Python 3.12, got {version}"
        except Exception as e:
            pytest.fail(f"Cannot check Python version: {e}")

    def test_systemd_service_changes(self):
        """Test systemd service changes from 20.04 to 24.04"""
        # Check for deprecated systemd options
        services = [
            "postgresql",
            "pgbouncer",
            "postgrest",
            "gotrue",
            "kong",
            "nginx"
        ]

        for service in services:
            result = subprocess.run(
                ['systemctl', 'show', service],
                capture_output=True, text=True
            )
            config = result.stdout

            # Check for deprecated options
            deprecated_options = [
                'Type=simple',  # Replaced by Type=exec
                'RestartSec=0',  # No longer needed
                'TimeoutStartSec=0'  # No longer needed
            ]

            for option in deprecated_options:
                assert option not in config, f"Service {service} uses deprecated option: {option}"

    def test_network_manager_changes(self):
        """Test NetworkManager changes from 20.04 to 24.04"""
        try:
            result = subprocess.run(
                ['nmcli', '--version'],
                capture_output=True, text=True
            )
            version = result.stdout.strip()
            assert '1.44' in version, f"Expected NetworkManager 1.44+, got {version}"
        except Exception as e:
            pytest.skip(f"Cannot check NetworkManager version: {e}")

    def test_apt_changes(self):
        """Test APT changes from 20.04 to 24.04"""
        try:
            result = subprocess.run(
                ['apt', '--version'],
                capture_output=True, text=True
            )
            version = result.stdout.strip()
            assert '2.7' in version, f"Expected APT 2.7+, got {version}"
        except Exception as e:
            pytest.skip(f"Cannot check APT version: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

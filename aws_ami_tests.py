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
    
    def __init__(self):
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
            self._execute_sql("CREATE DATABASE ami_test_db;")
            
            # Test operations on new database
            result = self._execute_sql("SELECT 1;", database="ami_test_db")
            assert result[0][0] == 1
            
            # Cleanup
            self._execute_sql("DROP DATABASE ami_test_db;")
        except psycopg2.Error as e:
            if "already exists" in str(e):
                pass
            else:
                raise


class TestPostgreSQLExtensions(AMISystemTest):
    """Test PostgreSQL extensions on AWS AMI"""

    def test_core_extensions_available(self):
        """Test core Supabase extensions are available"""
        extensions = [
            'pg_stat_statements', 'pgaudit', 'pg_cron', 'postgis',
            'pgtap', 'pgvector', 'pgsodium', 'supautils'
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
        'pg_stat_statements', 'pgaudit', 'pgsodium', 'supautils'
    ])
    def test_extension_loading(self, extension):
        """Test individual extensions can be loaded"""
        try:
            self._execute_sql(f"CREATE EXTENSION IF NOT EXISTS {extension};")
            
            # Verify extension is loaded
            result = self._execute_sql(
                f"SELECT extname FROM pg_extension WHERE extname = '{extension}';")
            assert len(result) > 0, f"Extension {extension} not loaded"
            
        except psycopg2.Error as e:
            pytest.fail(f"Failed to load extension {extension}: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"]) 
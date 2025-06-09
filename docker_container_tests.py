#!/usr/bin/env python3
"""
Docker Container Ubuntu 24.04 Compatibility Tests for Supabase Postgres
Tests for running against Docker containers on Ubuntu 24.04 hosts
"""

import pytest
import docker
import psycopg2
import subprocess
import requests
import time
import os
import sys
import socket
import ssl
import tempfile
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class DockerTestConfig:
    """Configuration for Docker container testing"""
    postgres_user: str = "postgres"
    postgres_password: str = "your-super-secret-and-long-postgres-password"
    postgres_db: str = "postgres"
    

class DockerCompatibilityTest:
    """Base class for Docker container compatibility testing"""
    
    def __init__(self):
        self.docker_client = docker.from_env()
        self.test_containers = []
        self.test_networks = []
        self.config = DockerTestConfig()
        
    def cleanup(self):
        """Clean up test containers and networks"""
        for container in self.test_containers:
            try:
                if container.status == "running":
                    container.stop(timeout=10)
                container.remove(force=True)
            except Exception as e:
                print(f"Cleanup warning: {e}")
                
        for network in self.test_networks:
            try:
                network.remove()
            except Exception as e:
                print(f"Network cleanup warning: {e}")

    @contextmanager
    def postgres_container(self, postgres_version="15", custom_env=None):
        """Create a PostgreSQL container"""
        container_name = f"test_postgres_{postgres_version}_{int(time.time())}"
        
        env = {
            "POSTGRES_DB": self.config.postgres_db,
            "POSTGRES_USER": self.config.postgres_user,
            "POSTGRES_PASSWORD": self.config.postgres_password,
            "POSTGRES_HOST_AUTH_METHOD": "md5"
        }
        
        if custom_env:
            env.update(custom_env)
        
        container = self.docker_client.containers.run(
            f"supabase/postgres:{postgres_version}-latest",
            name=container_name,
            environment=env,
            ports={"5432/tcp": None},
            detach=True,
            remove=False
        )
        
        self.test_containers.append(container)
        
        try:
            port = self._get_container_port(container, 5432)
            self._wait_for_postgres(port)
            yield container, port
        finally:
            pass

    @contextmanager
    def supabase_stack(self, postgres_version="15"):
        """Create full Supabase stack with networking"""
        network_name = f"supabase_test_{int(time.time())}"
        network = self.docker_client.networks.create(network_name)
        self.test_networks.append(network)
        
        try:
            # PostgreSQL container
            postgres = self._create_postgres_container(network, postgres_version)
            self.test_containers.append(postgres)
            postgres_port = self._get_container_port(postgres, 5432)
            self._wait_for_postgres(postgres_port)
            
            # pgBouncer container
            pgbouncer = self._create_pgbouncer_container(network, postgres)
            self.test_containers.append(pgbouncer)
            pgbouncer_port = self._get_container_port(pgbouncer, 6543)
            
            # PostgREST container
            postgrest = self._create_postgrest_container(network, postgres)
            self.test_containers.append(postgrest)
            postgrest_port = self._get_container_port(postgrest, 3000)
            
            # Wait for all services
            self._wait_for_pgbouncer(pgbouncer_port)
            self._wait_for_postgrest(postgrest_port)
            
            yield {
                'postgres': {'container': postgres, 'port': postgres_port},
                'pgbouncer': {'container': pgbouncer, 'port': pgbouncer_port},
                'postgrest': {'container': postgrest, 'port': postgrest_port},
                'network': network
            }
        finally:
            pass

    def _create_postgres_container(self, network, version):
        """Create PostgreSQL container on network"""
        return self.docker_client.containers.run(
            f"supabase/postgres:{version}-latest",
            network=network.name,
            environment={
                "POSTGRES_DB": self.config.postgres_db,
                "POSTGRES_USER": self.config.postgres_user,
                "POSTGRES_PASSWORD": self.config.postgres_password,
                "POSTGRES_HOST_AUTH_METHOD": "md5"
            },
            ports={"5432/tcp": None},
            detach=True
        )

    def _create_pgbouncer_container(self, network, postgres):
        """Create pgBouncer container"""
        return self.docker_client.containers.run(
            "pgbouncer/pgbouncer:latest",
            network=network.name,
            environment={
                "DATABASES_HOST": postgres.name,
                "DATABASES_PORT": "5432",
                "DATABASES_USER": self.config.postgres_user,
                "DATABASES_PASSWORD": self.config.postgres_password,
                "DATABASES_DBNAME": self.config.postgres_db,
                "POOL_MODE": "transaction",
                "LISTEN_PORT": "6543"
            },
            ports={"6543/tcp": None},
            detach=True
        )

    def _create_postgrest_container(self, network, postgres):
        """Create PostgREST container"""
        db_uri = f"postgres://{self.config.postgres_user}:{self.config.postgres_password}@{postgres.name}:5432/{self.config.postgres_db}"
        
        return self.docker_client.containers.run(
            "postgrest/postgrest:v12.2.3",
            network=network.name,
            environment={
                "PGRST_DB_URI": db_uri,
                "PGRST_DB_SCHEMAS": "public",
                "PGRST_DB_ANON_ROLE": "anon",
                "PGRST_JWT_SECRET": "test-secret-key",
                "PGRST_SERVER_PORT": "3000"
            },
            ports={"3000/tcp": None},
            detach=True
        )

    def _get_container_port(self, container, internal_port):
        """Get external port mapping"""
        container.reload()
        port_bindings = container.attrs['NetworkSettings']['Ports']
        return int(port_bindings[f'{internal_port}/tcp'][0]['HostPort'])

    def _wait_for_postgres(self, port, timeout=60):
        """Wait for PostgreSQL to be ready"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                conn = psycopg2.connect(
                    host="localhost", port=port, database=self.config.postgres_db,
                    user=self.config.postgres_user, password=self.config.postgres_password,
                    connect_timeout=5
                )
                conn.close()
                return True
            except:
                time.sleep(2)
        return False

    def _wait_for_pgbouncer(self, port, timeout=30):
        """Wait for pgBouncer to be ready"""
        return self._wait_for_postgres(port, timeout)

    def _wait_for_postgrest(self, port, timeout=30):
        """Wait for PostgREST to be ready"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"http://localhost:{port}/", timeout=5)
                if response.status_code == 200:
                    return True
            except:
                time.sleep(2)
        return False

    def _execute_sql(self, port, sql):
        """Execute SQL and return results"""
        conn = psycopg2.connect(
            host="localhost", port=port, database=self.config.postgres_db,
            user=self.config.postgres_user, password=self.config.postgres_password
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

# ... (rest of the test classes as in your original flake.nix) ... 
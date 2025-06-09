# Ubuntu 24.04 Compatibility Tests for Supabase Postgres

This project contains compatibility tests for running Supabase Postgres on Ubuntu 24.04, both on AWS AMI instances and in Docker containers.

## Prerequisites

- Nix package manager installed
- Docker (for Docker tests)
- PostgreSQL (for AMI tests)

## Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Enter the development shell:
   ```bash
   nix develop
   ```

## Running Tests

### AWS AMI Tests

To run the AWS AMI compatibility tests, use the following command:
```bash
nix run .#run-ami-tests
```

### Docker Tests

To run the Docker container compatibility tests, use the following command:
```bash
nix run .#run-docker-tests
```

### Run All Tests

To run all available tests, use the following command:
```bash
nix run .#run-all-tests
```

### Cleanup

To clean up any test artifacts, use the following command:
```bash
nix run .#cleanup-tests
```

### Show System Information

To display system information relevant to the tests, use the following command:
```bash
nix run .#show-system-info
```

## Environment Variables

You can set the following environment variables to customize the tests:
- `POSTGRES_PASSWORD`: PostgreSQL password (default: postgres)
- `POSTGRES_USER`: PostgreSQL user (default: postgres)
- `POSTGRES_HOST`: PostgreSQL host (default: localhost)

## Available Commands

- `nix run .#run-ami-tests`: Run AWS AMI tests
- `nix run .#run-docker-tests`: Run Docker container tests
- `nix run .#run-all-tests`: Run all available tests
- `nix run .#cleanup-tests`: Clean up test artifacts
- `nix run .#show-system-info`: Show system information

## Contributing

Feel free to contribute to this project by submitting issues or pull requests.

## License

This project is licensed under the MIT License. 
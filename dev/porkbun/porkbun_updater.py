#!/usr/bin/env python3
"""
Porkbun Dynamic DNS Updater
Automatically updates DNS records on Porkbun to point to your public IP.
"""

import requests
import json
import time
import logging
import os
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

try:
    import yaml
    from dotenv import load_dotenv
except ImportError:
    print("ERROR: Required packages not installed. Install with: pip install pyyaml python-dotenv")
    sys.exit(1)


class PorkbunDDNS:
    """Porkbun Dynamic DNS updater."""

    API_BASE = "https://porkbun.com/api/json/v3"

    def __init__(self, config_file: str = "config.yaml", env_file: str = ".env"):
        """Initialize the updater with config file."""
        # Load .env file first
        load_dotenv(env_file)
        
        self.config = self._load_config(config_file)
        self._setup_logging()
        self.logger = logging.getLogger(__name__)
        self.last_ip = None

    def _load_config(self, config_file: str) -> dict:
        """Load and expand environment variables in config."""
        config_path = Path(config_file)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")

        with open(config_path) as f:
            content = f.read()

        # Expand environment variables
        for key, value in os.environ.items():
            content = content.replace(f"${{{key}}}", value)

        config = yaml.safe_load(content)
        return config

    def _setup_logging(self):
        """Configure logging."""
        log_level = self.config.get("logging", {}).get("level", "INFO")
        log_file = self.config.get("logging", {}).get("file", None)

        # Create handlers
        handlers = [logging.StreamHandler()]
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file))

        # Configure root logger
        logging.basicConfig(
            level=getattr(logging, log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )

    def get_public_ip(self) -> str:
        """Get current public IP address."""
        # Check if static IP is configured
        static_ip = self.config.get("ip", {}).get("static")
        if static_ip:
            self.logger.info(f"Using static IP: {static_ip}")
            return static_ip

        # Auto-detect public IP
        service = self.config.get("ip", {}).get("auto_detect_service", "ifconfig.me")
        services = {
            "ifconfig.me": "https://ifconfig.me",
            "icanhazip.com": "https://icanhazip.com",
            "checkip.amazonaws.com": "https://checkip.amazonaws.com",
        }

        url = services.get(service, "https://ifconfig.me")

        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            ip = response.text.strip()
            self.logger.debug(f"Auto-detected public IP: {ip}")
            return ip
        except Exception as e:
            self.logger.error(f"Failed to auto-detect public IP: {e}")
            raise

    def _make_request(self, endpoint: str, params: dict) -> dict:
        """Make authenticated request to Porkbun API."""
        api_key = self.config["porkbun"]["api_key"]
        api_secret = self.config["porkbun"]["api_secret"]

        if not api_key or not api_secret:
            raise ValueError("porkbun.api_key and porkbun.api_secret are required")

        # Debug: Log credential format
        self.logger.debug(f"API Key format: ...{api_key[-10:] if len(api_key) > 10 else api_key}")
        self.logger.debug(f"API Secret format: ...{api_secret[-10:] if len(api_secret) > 10 else api_secret}")

        params["apikey"] = api_key
        params["secretapikey"] = api_secret

        url = f"{self.API_BASE}/{endpoint}"
        self.logger.debug(f"Request URL: {url}")
        self.logger.debug(f"Request params keys: {list(params.keys())}")

        try:
            response = requests.post(url, json=params, timeout=10)
            self.logger.debug(f"Response status: {response.status_code}")
            response.raise_for_status()
            result = response.json()

            if result.get("status") != "success":
                raise Exception(f"API error: {result.get('message', 'Unknown error')}")

            return result
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP Error {e.response.status_code}: {e.response.text}")
            raise
        except Exception as e:
            self.logger.error(f"API request failed: {e}")
            raise

    def get_dns_records(self, domain: str) -> dict:
        """Get all DNS records for a domain."""
        try:
            result = self._make_request("dns/retrieve", {"domain": domain})
            return result.get("records", {})
        except Exception as e:
            self.logger.error(f"Failed to retrieve DNS records: {e}")
            raise

    def health_check(self) -> bool:
        """Test API connectivity and credentials."""
        try:
            self.logger.info("Running API health check...")
            result = self._make_request("account/login", {})
            self.logger.info(f"✓ API health check passed: {result.get('message', 'OK')}")
            return True
        except Exception as e:
            self.logger.error(f"✗ API health check failed: {e}")
            return False

    def update_dns_record(
        self, domain: str, subdomain: str, ip: str, record_id: Optional[str] = None
    ) -> bool:
        """Update or create a DNS A record."""
        params = {
            "domain": domain,
            "name": subdomain if subdomain != "@" else "",
            "type": "A",
            "content": ip,
            "ttl": "600",
        }

        if record_id:
            params["id"] = record_id

        try:
            self._make_request("dns/updateRecord", params)
            display_name = subdomain if subdomain != "@" else domain
            self.logger.info(f"Updated {display_name} → {ip}")
            return True
        except Exception as e:
            self.logger.error(
                f"Failed to update {subdomain}.{domain} record: {e}"
            )
            return False

    def update_all_records(self, ip: str) -> bool:
        """Update all configured DNS records."""
        domain = self.config["domain"]["name"]
        records_to_update = self.config["domain"].get("records", [{"name": "@"}])

        self.logger.info(f"Updating DNS records for {domain} to {ip}")

        # Get existing records
        try:
            existing_records = self.get_dns_records(domain)
        except Exception:
            self.logger.error("Failed to retrieve existing DNS records")
            return False

        # Build a map of subdomain names to record IDs (only for A records)
        record_map = {}
        for record in existing_records:
            if record.get("type") == "A":
                name = record.get("name", "@")
                record_map[name] = record.get("id")

        # Update each configured record
        success = True
        for record_config in records_to_update:
            subdomain = record_config.get("name", "@")
            record_id = record_map.get(subdomain)

            if not self.update_dns_record(domain, subdomain, ip, record_id):
                success = False

        return success

    def run_once(self) -> bool:
        """Run one update cycle."""
        try:
            current_ip = self.get_public_ip()

            # Only update if IP changed
            if current_ip == self.last_ip:
                self.logger.debug(f"IP unchanged ({current_ip}), skipping update")
                return True

            self.last_ip = current_ip
            return self.update_all_records(current_ip)

        except Exception as e:
            self.logger.error(f"Update cycle failed: {e}")
            return False

    def run_daemon(self):
        """Run as a daemon, updating periodically."""
        interval = self.config.get("update_interval_seconds", 600)
        
        # Run health check first
        if not self.health_check():
            self.logger.error("API health check failed. Fix credentials and try again.")
            sys.exit(1)
        
        self.logger.info(
            f"Starting Porkbun DDNS updater (interval: {interval}s)"
        )

        try:
            while True:
                self.run_once()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            sys.exit(0)
        except Exception as e:
            self.logger.error(f"Fatal error: {e}")
            sys.exit(1)


def main():
    """Main entry point."""
    config_file = os.environ.get("PORKBUN_CONFIG", "config.yaml")
    
    # Check for --health-check flag
    if "--health-check" in sys.argv:
        updater = PorkbunDDNS(config_file)
        exit_code = 0 if updater.health_check() else 1
        sys.exit(exit_code)
    
    # Check for --once flag (run single update without daemon mode)
    if "--once" in sys.argv:
        updater = PorkbunDDNS(config_file)
        if updater.health_check():
            updater.run_once()
        sys.exit(0)

    updater = PorkbunDDNS(config_file)
    updater.run_daemon()


if __name__ == "__main__":
    main()

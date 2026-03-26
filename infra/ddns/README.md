# Porkbun Dynamic DNS Updater

Automatically updates DNS records on Porkbun to point to your current public IP address.

## Setup

### 1. Get Your API Credentials

- Go to https://porkbun.com/account/api
- Enable API access
- Generate and copy your API Key and Secret

### 2. Configure

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Edit `.env` and add your Porkbun API credentials:

```
PORKBUN_API_KEY=your_key_here
PORKBUN_API_SECRET=your_secret_here
```

### 3. Edit config.yaml

Update `config.yaml` with your domain and any subdomains you want to update:

```yaml
domain:
  name: slakxs.de
  records:
    - name: "@"      # Root domain
    - name: "www"    # www.slakxs.de
    - name: "git"    # git.slakxs.de

ip:
  static: "91.13.180.167"  # Your public IP
```

### 4. Run with Docker Compose

```bash
docker-compose up -d
```

## Features

- ✅ Updates DNS A records on Porkbun
- ✅ Static IP or auto-detection
- ✅ Periodic updates (configurable interval)
- ✅ Logging with rotation
- ✅ Only updates when IP changes
- ✅ Docker container support

## Configuration

### Static IP vs Auto-Detection

In `config.yaml`, set the IP:

```yaml
ip:
  # Option 1: Static IP (recommended for stable connections)
  static: "91.13.180.167"
  
  # Option 2: Auto-detect from external service
  # static: ""
  # auto_detect_service: "ifconfig.me"
```

### Update Interval

Change how often the updater checks for IP changes:

```yaml
update_interval_seconds: 600  # 10 minutes
```

### Logging

```yaml
logging:
  level: INFO              # DEBUG, INFO, WARNING, ERROR
  file: /var/log/porkbun-ddns/updater.log
```

## Testing

Run a single update cycle:

```bash
python porkbun_updater.py
```

Or inside Docker:

```bash
docker-compose run porkbun-ddns python porkbun_updater.py
```

## Troubleshooting

### API Key Invalid

Check that `PORKBUN_API_KEY` and `PORKBUN_API_SECRET` are correctly set in `.env`

### DNS Records Not Updating

1. Check logs: `docker-compose logs -f porkbun-ddns`
2. Verify domain name in `config.yaml`
3. Ensure API access is enabled on Porkbun

### Wrong IP Being Set

If using auto-detection, verify the service is accessible:

```bash
curl https://ifconfig.me
```

## API Reference

See [Porkbun API Documentation](https://porkbun.com/api/json/v3/documentation) for more details.

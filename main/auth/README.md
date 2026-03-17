# Authentication Service

Simple session-based authentication for private pages on slakxs.de.

## How It Works

1. User visits `/cookie` with their browser
2. User enters their access token (set via `AUTH_TOKEN` environment variable)
3. Server validates the token and returns a long-lived session cookie (httpOnly, Secure)
4. User stays authenticated until they manually clear cookies or you rotate the token
5. Private pages check for the session cookie before serving content
6. Non-authenticated requests to private pages receive 404 (page doesn't exist)

## Setup

### 1. Set Your Token

Create a `.env` file in `reverse-proxy/` with a strong token:

```bash
openssl rand -hex 32 > /tmp/token.txt
cat /tmp/token.txt  # Copy this value
```

Then in `reverse-proxy/.env`:
```
AUTH_TOKEN=your_64_character_hex_string_here
```

### 2. Configure Private Pages

Add entries to `reverse-proxy/Caddyfile` under the `slakxs.de` block:

```caddy
handle /my-private-page* {
    @isLocal {
        remote_ip 127.0.0.1 ::1
    }
    @hasAuth {
        cookie auth_session
    }
    
    handle @isLocal {
        reverse_proxy my-service:port
    }
    handle @hasAuth {
        reverse_proxy my-service:port
    }
    
    handle {
        error 404
    }
}
```

### 3. Access from a Device

1. Visit `https://slakxs.de/cookie`
2. Enter your token
3. You're authenticated - navigate to your private pages
4. Session lasts until cookie expiration (~10 years) or manual revocation

### 4. Revoke All Access

If a device is compromised:

1. SSH into the server
2. Update `AUTH_TOKEN` in `reverse-proxy/.env`
3. Restart the reverse-proxy: `docker-compose restart`
4. All existing sessions are invalidated
5. All users must re-authenticate with the new token

## Security Notes

- **Localhost access:** Private pages are always accessible from `127.0.0.1` for testing/maintenance
- **HTTPS only:** Cookies use Secure flag - only sent over HTTPS
- **httpOnly:** Cookies cannot be accessed by JavaScript (protects against XSS)
- **SameSite:** Set to Lax to prevent CSRF attacks
- **Token masking:** Failed auth attempts don't reveal if token was wrong or endpoint nonexistent
- **Long-lived cookies:** No expiration means no awkward re-logins on personal devices, but token rotation is your only revocation method

## For Phone/New Devices

The session cookie persists across browser restarts and syncs with password managers. Just:

1. Visit `/cookie`
2. Paste token from password manager
3. Done - stays logged in indefinitely

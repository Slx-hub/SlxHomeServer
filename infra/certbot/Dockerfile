FROM certbot/certbot:latest

# Create renewal hooks directory
RUN mkdir -p /etc/letsencrypt/renewal-hooks/post

# Copy and use the renewal loop entrypoint
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

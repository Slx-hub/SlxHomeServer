FROM certbot/certbot:latest

# Install the Porkbun DNS plugin for automated ACME challenges
RUN pip install certbot-dns-porkbun

# Create renewal hooks directory
RUN mkdir -p /etc/letsencrypt/renewal-hooks/post

ENTRYPOINT ["certbot"]
CMD ["--help"]

FROM alpine:3.21

RUN apk add --no-cache rsync tar bash findutils

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

ENTRYPOINT ["/usr/local/bin/backup.sh"]

# gdnsd authoritative GeoDNS server for the Watch-edge routing layer (#4319).
# Alpine community ships gdnsd 3.x. Config + zones + geoip mounted at /etc/gdnsd.
FROM alpine:3.20

RUN apk add --no-cache gdnsd

# Config root: /etc/gdnsd/{config, zones/, geoip/<mmdb>}  (bind-mounted, read-only)
EXPOSE 53/udp 53/tcp

# gdnsd 3.x `start` runs in the FOREGROUND (no daemonization, no -f flag).
ENTRYPOINT ["gdnsd", "-c", "/etc/gdnsd"]
CMD ["start"]

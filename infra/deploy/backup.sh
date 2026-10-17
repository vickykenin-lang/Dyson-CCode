#!/bin/bash
# Runs on dyson-server (systemd timer, nightly). Dumps the Dyson database and uploads it to the
# Object-Locked backup bucket. The server role can write backups but never delete them.
set -euo pipefail
export PATH=$PATH:/snap/bin
STAMP=$(date -u +%Y-%m-%dT%H%M%SZ)
FILE=/var/tmp/dyson-$STAMP.dump
docker exec dyson-postgres-1 pg_dump -U postgres -Fc dyson > "$FILE"
SIZE=$(stat -c %s "$FILE")
[ "$SIZE" -gt 1024 ] || { echo "backup too small: $SIZE bytes"; exit 1; }
aws s3 cp --region ap-southeast-2 --quiet --sse AES256 "$FILE" "s3://dyson-backups-501430758577/db/dyson-$STAMP.dump"
rm -f "$FILE"
echo "backup ok: db/dyson-$STAMP.dump ($SIZE bytes)"
# Layer A's /data (secret store, passkeys, model rollout state): without it a restored database
# cannot be used. Encrypted with /dyson/backup_key before it leaves the server.
KEY=$(mktemp /run/dyson-backup-key.XXXXXX)
trap 'rm -f "$KEY"' EXIT
aws ssm get-parameter --region ap-southeast-2 --name /dyson/backup_key --with-decryption \
  --query Parameter.Value --output text | tr -d '\n' > "$KEY"
DATA=/var/tmp/dyson-data-$STAMP.tar.enc
docker exec dyson-layer-a-1 tar -C /data -czf - . \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:$KEY" > "$DATA"
aws s3 cp --region ap-southeast-2 --quiet --sse AES256 "$DATA" "s3://dyson-backups-501430758577/data/dyson-data-$STAMP.tar.enc"
echo "backup ok: data/dyson-data-$STAMP.tar.enc ($(stat -c %s "$DATA") bytes)"
rm -f "$DATA"

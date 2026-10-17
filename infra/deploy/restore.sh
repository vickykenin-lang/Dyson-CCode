#!/bin/bash
# Disaster recovery on a new server, after deploy.sh has started Layer A once: replaces its fresh
# database and /data with the newest backups. Run through Systems Manager: restore.sh
set -euo pipefail
export PATH=$PATH:/snap/bin
R=ap-southeast-2; B=s3://dyson-backups-501430758577
cd /opt/dyson/current
DB=$(aws s3 ls --region $R "$B/db/" | sort | tail -1 | awk '{print $4}')
DATA=$(aws s3 ls --region $R "$B/data/" | sort | tail -1 | awk '{print $4}')
aws s3 cp --region $R --quiet "$B/db/$DB" /var/tmp/restore.dump
KEY=$(mktemp /run/dyson-backup-key.XXXXXX)
trap 'rm -f "$KEY" /var/tmp/restore.dump' EXIT
aws ssm get-parameter --region $R --name /dyson/backup_key --with-decryption \
  --query Parameter.Value --output text | tr -d '\n' > "$KEY"
docker compose -p dyson stop layer-a
docker exec dyson-postgres-1 dropdb -U postgres dyson
docker exec dyson-postgres-1 createdb -U postgres -O dyson_owner dyson
docker cp /var/tmp/restore.dump dyson-postgres-1:/tmp/r.dump
docker exec dyson-postgres-1 pg_restore -U postgres -d dyson /tmp/r.dump 2>&1 | tail -5 || true
docker exec dyson-postgres-1 rm -f /tmp/r.dump
aws s3 cp --region $R --quiet "$B/data/$DATA" - \
  | openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:$KEY" | docker cp -a - dyson-layer-a-1:/data
docker compose -p dyson start layer-a
TASKS=$(docker exec dyson-postgres-1 psql -U postgres -d dyson -tAc "select count(*) from orchestrator.tasks")
echo "restored $DB and $DATA: $TASKS tasks"

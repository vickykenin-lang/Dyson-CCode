#!/bin/bash
# Restore test: fetch the newest backup, restore it into a throwaway Postgres container, and
# check that the tasks and evidence are there. Never touches the live database.
set -euo pipefail
export PATH=$PATH:/snap/bin
B=s3://dyson-backups-501430758577/db/
KEY=$(aws s3 ls --region ap-southeast-2 "$B" | sort | tail -1 | awk '{print $4}')
aws s3 cp --region ap-southeast-2 --quiet "$B$KEY" /var/tmp/restore.dump
docker rm -f dyson-restore-test >/dev/null 2>&1 || true
docker run -d --name dyson-restore-test -e POSTGRES_PASSWORD=restoretest postgres:16 >/dev/null
for i in $(seq 1 30); do docker exec dyson-restore-test pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
docker exec dyson-restore-test createdb -U postgres dyson
docker cp /var/tmp/restore.dump dyson-restore-test:/tmp/r.dump
docker exec dyson-restore-test pg_restore -U postgres -d dyson --no-owner --no-privileges /tmp/r.dump 2>/dev/null || true
LIVE=$(docker exec dyson-postgres-1 psql -U postgres -d dyson -tAc "select count(*) from orchestrator.tasks")
REST=$(docker exec dyson-restore-test psql -U postgres -d dyson -tAc "select count(*) from orchestrator.tasks")
EVID=$(docker exec dyson-restore-test psql -U postgres -d dyson -tAc "select count(*) from memory.evidence")
docker rm -f dyson-restore-test >/dev/null; rm -f /var/tmp/restore.dump
echo "restore test of $KEY: tasks live=$LIVE restored=$REST evidence=$EVID"
[ "$REST" = "$LIVE" ] && [ "$EVID" -gt 0 ] && echo RESTORE_OK || { echo RESTORE_MISMATCH; exit 1; }

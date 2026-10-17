#!/bin/bash
# Runs on dyson-server through Systems Manager: deploy.sh <release-name>
# Fetches the release bundle from S3 and the secrets from Parameter Store (never printed),
# then starts Layer A with docker compose. Ports stay on 127.0.0.1.
set -euo pipefail
REL="$1"; R=ap-southeast-2; BUCKET=dyson-releases-501430758577
command -v aws >/dev/null || snap install aws-cli --classic
export PATH=$PATH:/snap/bin
mkdir -p /opt/dyson/releases && cd /opt/dyson/releases
if [ ! -d "$REL" ]; then
  aws s3 cp --region $R --quiet "s3://$BUCKET/$REL.tgz" "/tmp/$REL.tgz"
  mkdir "$REL" && tar -xzf "/tmp/$REL.tgz" -C "$REL" && rm "/tmp/$REL.tgz"
fi
cd "$REL"
install -d -m 700 local-secrets
for n in postgres_password db_password founder_password; do
  aws ssm get-parameter --region $R --name "/dyson/$n" --with-decryption \
    --query Parameter.Value --output text | tr -d '\n' > "local-secrets/$n"
  chmod 644 "local-secrets/$n"
done
DYSON_SECURE_COOKIES=1 DYSON_PASSKEY_RP_ID=control.designinfra.in \
  DYSON_PASSKEY_ORIGIN=https://control.designinfra.in \
  DYSON_ENVIRONMENT=aws-ap-southeast-2 DYSON_RELEASE="$REL" \
  DYSON_BEDROCK=1 DYSON_AWS_DIR=/opt/dyson/aws docker compose -p dyson up -d --build
ln -sfn "/opt/dyson/releases/$REL" /opt/dyson/current
docker compose -p dyson ps --format '{{.Service}} {{.State}} {{.Status}}'

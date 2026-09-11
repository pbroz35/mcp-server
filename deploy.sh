#!/usr/bin/env bash
# Deploy the MCP server to Cloud Run.
#
#   PROJECT_ID=my-project ./deploy.sh
#
# First run also creates the MCP_AUTH_TOKEN secret and grants the runtime
# service account read access to it. Re-runs are idempotent.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-mcp-server}"
SECRET_NAME="${SECRET_NAME:-mcp-auth-token}"

if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" ]]; then
  echo "PROJECT_ID is not set. Run: gcloud config set project <id>" >&2
  exit 1
fi

echo "==> project=${PROJECT_ID} region=${REGION} service=${SERVICE}"

# Project IDs are globally unique, so a plausible-looking name may well be
# someone else's project. Fail here with something readable rather than letting
# every later call return AUTH_PERMISSION_DENIED.
if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Cannot access project '${PROJECT_ID}' — it either does not exist or belongs" >&2
  echo "to someone else. Projects you can see:" >&2
  gcloud projects list --format='value(projectId)' | sed 's/^/  /' >&2
  echo "Create one with: gcloud projects create <globally-unique-id>" >&2
  exit 1
fi

# compute.googleapis.com is in the list because enabling it provisions the
# default compute service account, which is the Cloud Run runtime identity the
# secret binding below is granted to. On a brand-new project that account does
# not exist yet, and the binding fails.
echo "==> Ensuring required APIs are enabled"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  compute.googleapis.com \
  --project="${PROJECT_ID}"

if ! gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "==> Creating secret ${SECRET_NAME} with a fresh random token"
  gcloud secrets create "${SECRET_NAME}" --replication-policy=automatic --project="${PROJECT_ID}"
  # tr -d '\n': a trailing newline in the payload survives into the
  # container's env var but is stripped by any client using $(...).
  openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add "${SECRET_NAME}" \
    --data-file=- --project="${PROJECT_ID}"
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUNTIME_SA="${RUNTIME_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"

echo "==> Granting ${RUNTIME_SA} access to ${SECRET_NAME}"
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="${PROJECT_ID}" >/dev/null

echo "==> Deploying"
# --allow-unauthenticated is deliberate: MCP clients can't mint Google ID
# tokens, so access is gated by the bearer token instead (see auth.py).
gcloud run deploy "${SERVICE}" \
  --source . \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --platform=managed \
  --allow-unauthenticated \
  --set-secrets="MCP_AUTH_TOKEN=${SECRET_NAME}:latest" \
  --set-env-vars="MCP_SERVER_NAME=${SERVICE},MCP_LOG_LEVEL=info" \
  --cpu=1 \
  --memory=512Mi \
  --min-instances=0 \
  --max-instances=10 \
  --timeout=300

URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" \
  --project="${PROJECT_ID}" --format='value(status.url)')"

echo
echo "Deployed: ${URL}/mcp"
echo "Token:    gcloud secrets versions access latest --secret=${SECRET_NAME} --project=${PROJECT_ID}"

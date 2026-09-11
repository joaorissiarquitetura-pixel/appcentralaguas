$ErrorActionPreference = "Stop"

$ProjectId = "central-aguas-app"
$Region = "us-central1"
$ServiceId = "central-aguas-app"

gcloud config set project $ProjectId

Write-Host "Deploy do backend FastAPI no Cloud Run..."
gcloud run deploy $ServiceId `
  --source . `
  --region $Region `
  --allow-unauthenticated `
  --port 8000

Write-Host "Deploy do Firebase Hosting apontando para o Cloud Run..."
firebase deploy --only hosting --project $ProjectId

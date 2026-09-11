$ErrorActionPreference = "Stop"

$ProjectId = "central-aguas-app"
$PackageName = "com.centralaguas.app"
$DisplayName = "Central Aguas Android"

firebase use $ProjectId

$ExistingApps = firebase apps:list ANDROID --project $ProjectId
if ($ExistingApps -notmatch $PackageName) {
  firebase apps:create ANDROID $DisplayName --package-name $PackageName --project $ProjectId
}

firebase apps:list ANDROID --project $ProjectId

Write-Host ""
Write-Host "Copie o App ID Android exibido acima e rode:"
Write-Host "firebase apps:sdkconfig ANDROID SEU_FIREBASE_APP_ID --project $ProjectId > android/app/google-services.json"

# Snapshot post-deploy sandbox (U4-RC). No secrets printed beyond env keys we need.
param([Parameter(Mandatory=$true)][string]$Label)

$ErrorActionPreference = "Stop"
$base = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
$outDir = "D:\CMC\HBI_Capital\_work\u4_rc"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

[xml]$pub = Get-Content -Raw "D:\CMC\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings"
$p = $pub.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" } | Select-Object -First 1
$scm = $p.publishUrl.Split(":")[0]
$user = $p.userName
$pass = $p.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${user}:${pass}"))
$jh = @{ Authorization = "Basic $basic"; "Content-Type" = "application/json" }

function Kudu([string]$cmd) {
  $payload = '{"command":' + ($cmd | ConvertTo-Json) + ',"dir":"/home/site/wwwroot"}'
  $r = Invoke-RestMethod -Uri "https://$scm/api/command" -Method POST -Headers $jh -Body $payload -TimeoutSec 90
  return (@($r.Output) + @($r.Error)) -join ""
}

# Wait for UI
$appCode = 0
$spa = "missing"
$boot = $null
for ($i = 0; $i -lt 24; $i++) {
  try {
    $htmlResp = Invoke-WebRequest "$base/app/" -UseBasicParsing -TimeoutSec 30
    $appCode = [int]$htmlResp.StatusCode
    if ($htmlResp.Content -match 'index-[A-Za-z0-9_-]+\.js') { $spa = $Matches[0] }
    $boot = Invoke-RestMethod "$base/api/ui/v1/bootstrap" -TimeoutSec 30
    if ($appCode -eq 200 -and $boot.ui_enabled -eq $true) { break }
  } catch {
    $appCode = 0
  }
  Start-Sleep -Seconds 5
}

$envText = Kudu "grep ACTIVE_ENVIRONMENT /home/site/wwwroot/.env"
$envText += "`n" + (Kudu "grep GRAPH_CLIENTS_BASE_PATH /home/site/wwwroot/.env")
$envText += "`n" + (Kudu "grep GRAPH_ACCOUNTING_SITE_HOSTNAME /home/site/wwwroot/.env")
$envText += "`n" + (Kudu "grep UI_ENABLED /home/site/wwwroot/.env")
$envText += "`n" + (Kudu "grep UI_WRITE_ENABLED /home/site/wwwroot/.env")
$envText += "`n" + (Kudu "grep UI_NOTIFY_ENABLED /home/site/wwwroot/.env")
$envText += "`n" + (Kudu "grep UI_MERGE_ENABLED /home/site/wwwroot/.env")
$envText += "`n" + (Kudu "grep UI_AMORTIZATION_ENABLED /home/site/wwwroot/.env")
$envText += "`n" + (Kudu "grep UI_NOTIFY_SANDBOX_TO /home/site/wwwroot/.env")
$envBytes = (Kudu "wc -c /home/site/wwwroot/.env").Trim()

# paths-probe read-only if API key available
$probe = $null
$keyLine = Get-Content "D:\CMC\HBI_Capital\api-hbi-powerAutomate.env" | Where-Object { $_ -match '^API_HTTP_KEY=(.+)$' } | Select-Object -First 1
if ($keyLine -match '^API_HTTP_KEY=(.+)$') {
  $apiKey = $Matches[1].Trim()
  try {
    $probe = Invoke-RestMethod "$base/graph/diagnostics/paths-probe" -Headers @{ "X-API-Key" = $apiKey } -TimeoutSec 120
  } catch {
    $probe = @{ error = $_.Exception.Message }
  }
}

$snap = [ordered]@{
  label = $Label
  at = (Get-Date).ToString("o")
  env_bytes = $envBytes
  env_text = $envText
  app_status = $appCode
  spa = $spa
  bootstrap = $boot
  paths_probe_summary = $probe
}

$path = Join-Path $outDir ("deploy_env_{0}.json" -f $Label)
($snap | ConvertTo-Json -Depth 8) | Set-Content -Path $path -Encoding UTF8
Write-Host "WROTE $path"
Write-Host "env_text:"
Write-Host $envText
Write-Host "app=$appCode spa=$spa ui_enabled=$($boot.ui_enabled) active=$($boot.active_environment)"

if ($envText -match 'ACTIVE_ENVIRONMENT=production') { throw "PRODUCTION ENV DETECTED" }
if ($envText -notmatch 'ACTIVE_ENVIRONMENT=sandbox') { throw "SANDBOX NOT CONFIRMED" }
if ($envText -match '02 COMWARE AUTOMATIZACION' -and $envText -notmatch 'PRUEBAS') { throw "PRODUCTIVE CLIENTS PATH" }
if ($appCode -ne 200) { throw ("UI app not 200: {0}" -f $appCode) }
if ($boot.active_environment -ne 'sandbox') { throw ("bootstrap env not sandbox: {0}" -f $boot.active_environment) }
Write-Host ("OK {0}" -f $Label)

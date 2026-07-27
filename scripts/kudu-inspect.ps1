# Inspecciona el proceso en ejecucion y el contenido de wwwroot en el App Service.
param(
    [string]$PublishSettingsPath = (Join-Path $PSScriptRoot "..\..\..\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings"),
    [Parameter(Mandatory = $true)][string[]]$Commands,
    [int]$TimeoutSec = 300
)
$ErrorActionPreference = "Stop"

[xml]$pub = Get-Content -Raw (Resolve-Path $PublishSettingsPath)
$p = $pub.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" } | Select-Object -First 1
$scm = $p.publishUrl.Split(":")[0]
$pair = "{0}:{1}" -f $p.userName, $p.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$jh = @{ Authorization = "Basic $basic"; "Content-Type" = "application/json" }
$base = "https://$scm"

foreach ($c in $Commands) {
    $b = @{ command = $c; dir = "/home/site/wwwroot" } | ConvertTo-Json
    Write-Host "`n>>> $c"
    try {
        $r = Invoke-RestMethod -Uri "$base/api/command" -Method POST -Headers $jh -Body $b -TimeoutSec $TimeoutSec
        if ($r.Output) { Write-Host $r.Output }
        if ($r.Error -and $r.Error -notlike "*backslashes*") { Write-Host "ERR: $($r.Error)" }
    } catch {
        Write-Host "FALLO: $($_.Exception.Message)"
    }
}

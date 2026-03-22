# setup_export.ps1 — Add or remove the ThreatWarnerExport.lua dofile line
# in each DCS variant's Export.lua.  Called by the MSI installer.
param([string]$Action)

$line = "local twlfs=require('lfs');dofile(twlfs.writedir()..[[Scripts\ThreatWarnerExport.lua]])"

foreach ($v in 'DCS','DCS.openbeta') {
    $d  = Join-Path $env:USERPROFILE "Saved Games\$v\Scripts"
    $el = Join-Path $d 'Export.lua'
    $tw = Join-Path $d 'ThreatWarnerExport.lua'

    if ($Action -eq 'install') {
        if (!(Test-Path $tw)) { continue }
        $c = ''
        if (Test-Path $el) { $c = Get-Content $el -Raw -ErrorAction SilentlyContinue }
        if ($c -and $c.Contains('ThreatWarnerExport')) { continue }
        Add-Content -Path $el -Value $line -ErrorAction SilentlyContinue
    }
    elseif ($Action -eq 'uninstall') {
        if (!(Test-Path $el)) { continue }
        $lines = @(Get-Content $el -ErrorAction SilentlyContinue)
        $keep  = @($lines | Where-Object { $_ -notmatch 'ThreatWarnerExport' })
        Set-Content -Path $el -Value $keep -ErrorAction SilentlyContinue
    }
}

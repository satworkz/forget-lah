param([ValidateSet('doctor','setup','up','down','logs','test','status','model-check')][string]$Action = 'doctor')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Find-Docker {
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerCommand) { return $dockerCommand.Source }
    foreach ($candidatePath in @("$env:ProgramFiles/Docker/Docker/resources/bin/docker.exe", "$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe")) {
        if (Test-Path -LiteralPath $candidatePath) { return $candidatePath }
    }
    throw 'Docker CLI not found. Open Docker Desktop, then restart your VS Code terminal.'
}

function Invoke-Docker {
    & (Find-Docker) @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed with exit code $LASTEXITCODE. Read the error above." }
}

function New-LocalSecret {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}

function Ensure-SimulatorSecrets {
    $settingsPath = Join-Path $projectRoot '.env'
    $settingsText = [IO.File]::ReadAllText($settingsPath)
    foreach ($secretName in @('POSTGRES_MOCK_PASSWORD', 'MOCK_CLINIC_ADMIN_KEY', 'MOCK_CLINIC_FOLLOWUP_KEY')) {
        if ($settingsText -notmatch "(?m)^$secretName=") {
            $settingsText = $settingsText.TrimEnd() + "`n$secretName=$(New-LocalSecret)`n"
        }
    }
    [IO.File]::WriteAllText($settingsPath, $settingsText, (New-Object System.Text.UTF8Encoding $false))
}

switch ($Action) {
    'doctor' {
        git --version
        if ($LASTEXITCODE -ne 0) { throw 'Git is required.' }
        Invoke-Docker version
        Invoke-Docker compose version
        $dockerOs = & (Find-Docker) info --format '{{.OSType}}'
        if ($LASTEXITCODE -ne 0 -or $dockerOs -ne 'linux') { throw 'Docker Desktop must be running Linux containers.' }
        Write-Host 'Prerequisites passed. Next: ./scripts/dev.ps1 setup'
    }
    'setup' {
        if (Test-Path -LiteralPath '.env') { Ensure-SimulatorSecrets; Write-Host '.env already exists; existing credentials were preserved and missing simulator secrets were added.'; break }
        $content = @("POSTGRES_OWNER_PASSWORD=$(New-LocalSecret)", "POSTGRES_APP_PASSWORD=$(New-LocalSecret)", 'DEMO_STAFF_EMAIL=staff@forget-lah.example', "DEMO_STAFF_PASSWORD=$(New-LocalSecret)", 'WEB_PORT=8080') -join "`n"
        [IO.File]::WriteAllText((Join-Path $projectRoot '.env'), "$content`n", (New-Object System.Text.UTF8Encoding $false))
        Ensure-SimulatorSecrets
        Write-Host 'Created private local configuration. Open .env locally for your demo login; do not share it.'
        Write-Host 'Next: ./scripts/dev.ps1 up'
    }
    'up' {
        if (!(Test-Path -LiteralPath '.env')) { throw 'Run ./scripts/dev.ps1 setup first.' }
        Ensure-SimulatorSecrets
        Invoke-Docker compose up --build -d
        Write-Host 'Open http://localhost:8080 after services are healthy. Credentials are in your local .env.'
    }
    'test' { Invoke-Docker compose --profile test build tests; Invoke-Docker compose --profile test run --rm tests }
    'down' { Invoke-Docker compose down; Write-Host 'Stopped services. Database volume preserved.' }
    'logs' { Invoke-Docker compose logs --tail 100 api worker bootstrap }
    'status' { Invoke-Docker compose ps -a }
    'model-check' { Invoke-Docker compose run --rm --no-deps worker python -m forget_lah.runtime.check_model }
}

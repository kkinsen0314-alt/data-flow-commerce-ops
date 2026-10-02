[CmdletBinding()]
param(
    [string]$MiniClawBaseUrl = "http://127.0.0.1:3017",
    [string]$MiniClawEntry = "",
    [string]$WorkspaceJid = "",
    [int]$ApiPort = 3022
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or later is required. Run this script with pwsh.exe."
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$platformEntryCandidates = @()
if (-not [string]::IsNullOrWhiteSpace($MiniClawEntry)) {
    $platformEntryCandidates += $MiniClawEntry
}
if (-not [string]::IsNullOrWhiteSpace($env:MINICLAW_ENTRY)) {
    $platformEntryCandidates += $env:MINICLAW_ENTRY
}
$platformEntryCandidates += Join-Path `
    (Split-Path $projectRoot -Parent) `
    "project014-miniclaw-deployment\upstream\miniclaw\dist\index.js"
$platformEntry = $platformEntryCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($platformEntry)) {
    throw "MiniClaw entry not found. Pass -MiniClawEntry or set MINICLAW_ENTRY."
}
$platformEntry = (Resolve-Path -LiteralPath $platformEntry).Path
$runtimeRoot = Join-Path $projectRoot "runtime"
$logRoot = Join-Path $runtimeRoot "logs"
$platformRoot = Split-Path (Split-Path $platformEntry -Parent) -Parent
$dataFlowBuildScript = Join-Path $projectRoot "scripts\build-data-flow-web.mjs"
$profileTemplate = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $projectRoot "config\agent-profile-create.template.json") | ConvertFrom-Json
$profileName = $profileTemplate.name
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Test-DeepSubset {
    param(
        [AllowNull()][object]$Actual,
        [AllowNull()][object]$Expected
    )

    if ($null -eq $Expected) {
        return $null -eq $Actual
    }
    if ($Expected -is [System.Management.Automation.PSCustomObject]) {
        if ($null -eq $Actual) {
            return $false
        }
        foreach ($property in $Expected.PSObject.Properties) {
            $actualProperty = $Actual.PSObject.Properties[$property.Name]
            if ($null -eq $actualProperty -or -not (Test-DeepSubset -Actual $actualProperty.Value -Expected $property.Value)) {
                return $false
            }
        }
        return $true
    }
    if ($Expected -is [System.Collections.IEnumerable] -and $Expected -isnot [string]) {
        $actualItems = @($Actual)
        $expectedItems = @($Expected)
        if ($actualItems.Count -ne $expectedItems.Count) {
            return $false
        }
        for ($index = 0; $index -lt $expectedItems.Count; $index++) {
            if (-not (Test-DeepSubset -Actual $actualItems[$index] -Expected $expectedItems[$index])) {
                return $false
            }
        }
        return $true
    }
    return $Actual -ceq $Expected
}

function Get-ProfileDifferences {
    param(
        [object]$Existing,
        [object]$Expected
    )

    $differences = [System.Collections.Generic.List[string]]::new()
    foreach ($field in @("identity_prompt", "soul_prompt", "agents_prompt", "tools_prompt", "prompt_mode", "model_config_id")) {
        if ($Existing.$field -cne $Expected.$field) {
            $differences.Add($field)
        }
    }
    if (-not (Test-DeepSubset -Actual $Existing.runtime_policy -Expected $Expected.runtime_policy)) {
        $differences.Add("runtime_policy")
    }
    return @($differences)
}

function Get-TextSha256 {
    param([AllowNull()][string]$Value)

    $bytes = [Text.Encoding]::UTF8.GetBytes(($Value ?? ""))
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

if (-not (Test-Path -LiteralPath $platformEntry -PathType Leaf)) {
    throw "The pinned MiniClaw platform entry does not exist."
}
if (-not (Test-Path -LiteralPath $dataFlowBuildScript -PathType Leaf)) {
    throw "The Data Flow web build script does not exist."
}
& node.exe $dataFlowBuildScript --platform-root $platformRoot --api-port $ApiPort
if ($LASTEXITCODE -ne 0) {
    throw "The Data Flow web build failed."
}
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

try {
    $null = Invoke-RestMethod -Uri "$MiniClawBaseUrl/api/auth/status" -TimeoutSec 3
}
catch {
    $hostOut = Join-Path $logRoot "miniclaw-native-$stamp.stdout.log"
    $hostErr = Join-Path $logRoot "miniclaw-native-$stamp.stderr.log"
    $env:WEB_PORT = ([uri]$MiniClawBaseUrl).Port.ToString()
    $env:TZ = "Asia/Shanghai"
    Start-Process -FilePath "node.exe" `
        -ArgumentList @($platformEntry) `
        -WorkingDirectory $runtimeRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $hostOut `
        -RedirectStandardError $hostErr | Out-Null

    $hostReady = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $status = Invoke-RestMethod -Uri "$MiniClawBaseUrl/api/auth/status" -TimeoutSec 2
            if ($status.initialized -eq $true) {
                $hostReady = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 750
        }
    }
    if (-not $hostReady) {
        throw "MiniClaw Host did not become ready in time."
    }
}

$username = Read-Host "MiniClaw local username"
$securePassword = Read-Host "MiniClaw local password" -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    $loginBody = @{
        username = $username
        password = $plainPassword
    } | ConvertTo-Json -Compress
    $null = Invoke-RestMethod `
        -Method Post `
        -Uri "$MiniClawBaseUrl/api/auth/login" `
        -ContentType "application/json" `
        -Body $loginBody `
        -SessionVariable miniclawSession `
        -TimeoutSec 10
}
finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    $plainPassword = $null
    $loginBody = $null
}

$profilesPayload = Invoke-RestMethod `
    -Uri "$MiniClawBaseUrl/api/agent-profiles" `
    -WebSession $miniclawSession `
    -TimeoutSec 10
$profileMatches = @($profilesPayload.profiles | Where-Object { $_.name -ceq $profileName })
if ($profileMatches.Count -ne 1) {
    throw "Exactly one project017 AgentProfile must already exist; found $($profileMatches.Count)."
}
$runtimeProfile = $profileMatches[0]
$selectedModelId = if ($runtimeProfile.model_config_id) {
    [string]$runtimeProfile.model_config_id
}
else {
    [string]$profilesPayload.default_model_config_id
}
$selectedModels = @($profilesPayload.model_configs | Where-Object { $_.id -ceq $selectedModelId })
if ($selectedModels.Count -ne 1) {
    throw "The project017 AgentProfile does not resolve to exactly one Provider."
}
$selectedModel = $selectedModels[0]
if ($selectedModel.anthropic_model -cne "qwen3.7-plus-2026-05-26") {
    throw "The project017 AgentProfile is not bound to the authorized model."
}

$expectedProfile = $profileTemplate | ConvertTo-Json -Depth 100 | ConvertFrom-Json
$expectedProfile.model_config_id = $selectedModelId
$profileDifferences = @(Get-ProfileDifferences -Existing $runtimeProfile -Expected $expectedProfile)
$profileAction = "reused"
if ($profileDifferences.Count -gt 0) {
    $patchBody = $expectedProfile | ConvertTo-Json -Depth 100 -Compress
    try {
        $updatedPayload = Invoke-RestMethod `
            -Method Patch `
            -Uri "$MiniClawBaseUrl/api/agent-profiles/$($runtimeProfile.id)" `
            -ContentType "application/json" `
            -Body $patchBody `
            -WebSession $miniclawSession `
            -TimeoutSec 30
        if (-not $updatedPayload.profile) {
            throw "MiniClaw PATCH did not return the updated AgentProfile."
        }
        $runtimeProfile = $updatedPayload.profile
        $profileAction = "updated"
    }
    finally {
        $patchBody = $null
    }
}

$verifiedProfilesPayload = Invoke-RestMethod `
    -Uri "$MiniClawBaseUrl/api/agent-profiles" `
    -WebSession $miniclawSession `
    -TimeoutSec 10
$verifiedProfileMatches = @($verifiedProfilesPayload.profiles | Where-Object { $_.id -ceq $runtimeProfile.id })
if ($verifiedProfileMatches.Count -ne 1) {
    throw "The synchronized project017 AgentProfile could not be read back exactly once."
}
$runtimeProfile = $verifiedProfileMatches[0]
$remainingProfileDifferences = @(Get-ProfileDifferences -Existing $runtimeProfile -Expected $expectedProfile)
if ($remainingProfileDifferences.Count -gt 0) {
    throw "The synchronized project017 AgentProfile failed read-back verification."
}

$groupsPayload = Invoke-RestMethod `
    -Uri "$MiniClawBaseUrl/api/groups" `
    -WebSession $miniclawSession `
    -TimeoutSec 10
$visibleWorkspaces = @($groupsPayload.groups.PSObject.Properties)
if ($WorkspaceJid) {
    $workspaceMatches = @(
        $visibleWorkspaces | Where-Object { $_.Name -eq $WorkspaceJid }
    )
}
else {
    $workspaceMatches = @(
        $visibleWorkspaces |
            Where-Object {
                $_.Value.execution_mode -eq "host" -and
                $_.Value.agent_profile_name -eq $profileName -and
                $_.Value.custom_cwd -and
                [IO.Path]::GetFullPath([string]$_.Value.custom_cwd) -eq $projectRoot
            }
    )
}
if ($workspaceMatches.Count -ne 1) {
    Write-Host "Visible Workspace count: $($visibleWorkspaces.Count)"
    throw "Exactly one target project017 Workspace was not found or visible."
}
$workspace = $workspaceMatches[0].Value
$workspaceJid = $workspaceMatches[0].Name
if ($workspace.execution_mode -ne "host") {
    throw "The target Workspace is not using host execution mode."
}
if ($workspace.agent_profile_name -ne $profileName) {
    Write-Host "Expected AgentProfile: $profileName"
    Write-Host "Current AgentProfile: $($workspace.agent_profile_name)"
    throw "The target Workspace is not bound to the project017 AgentProfile."
}
if ($workspace.agent_profile_id -cne $runtimeProfile.id) {
    throw "The target Workspace is not bound to the synchronized project017 AgentProfile ID."
}
if (-not $workspace.custom_cwd) {
    throw "The login cannot read the target Workspace custom_cwd; use an authorized administrator account."
}
if ([IO.Path]::GetFullPath([string]$workspace.custom_cwd) -ne $projectRoot) {
    throw "The target Workspace custom_cwd does not point to project017."
}

$promptHashes = [ordered]@{}
foreach ($field in @("identity_prompt", "soul_prompt", "agents_prompt", "tools_prompt")) {
    $promptHashes[$field] = Get-TextSha256 -Value ([string]$runtimeProfile.$field)
}
$profileSyncAssessment = [ordered]@{
    schema_version = "1.0"
    validation_kind = "project017_native_profile_sync"
    status = "pass"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    profile_name = $profileName
    profile_action = $profileAction
    profile_version = $runtimeProfile.version
    selected_model = $selectedModel.anthropic_model
    prompt_sha256 = $promptHashes
    checks = [ordered]@{
        exactly_one_named_profile = $true
        provider_binding_preserved = $true
        authored_fields_match = $true
        runtime_policy_authored_subset_matches = $true
        workspace_binding_matches = $true
        workspace_execution_mode_host = $true
        workspace_interaction_mode_assistant = ($workspace.interaction_mode -ceq "assistant")
        workspace_custom_cwd_matches = $true
        session_created = $false
        model_called = $false
    }
    redaction = [ordered]@{
        credentials_included = $false
        cookie_included = $false
        provider_key_included = $false
        database_ids_included = $false
    }
}
$profileSyncArtifact = Join-Path $projectRoot "artifacts\runtime\native-profile-sync-assessment.json"
$profileSyncAssessment | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $profileSyncArtifact -Encoding utf8
$cookies = $miniclawSession.Cookies.GetCookies([uri]$MiniClawBaseUrl)
$cookieHeader = ($cookies | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join "; "
if (-not $cookieHeader) {
    throw "MiniClaw login did not return a usable session cookie."
}

try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/v1/native/configuration" -TimeoutSec 2
    throw "Port $ApiPort already has a service. Stop the old project017 API and retry."
}
catch {
    if ($_.Exception.Message -like "Port *") {
        throw
    }
}

$apiOut = Join-Path $logRoot "project017-native-api-$stamp.stdout.log"
$apiErr = Join-Path $logRoot "project017-native-api-$stamp.stderr.log"
$env:MINICLAW_BASE_URL = $MiniClawBaseUrl
$env:MINICLAW_WORKSPACE_JID = $workspaceJid
$env:MINICLAW_COOKIE = $cookieHeader
Remove-Item Env:MINICLAW_USERNAME,Env:MINICLAW_PASSWORD -ErrorAction SilentlyContinue
$apiProcess = Start-Process -FilePath "python.exe" `
    -ArgumentList @(
        "-m", "uvicorn", "commerce_ops.app:app",
        "--host", "127.0.0.1", "--port", $ApiPort.ToString()
    ) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $apiOut `
    -RedirectStandardError $apiErr `
    -PassThru

$nativeReady = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $configuration = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$ApiPort/v1/native/configuration" `
            -TimeoutSec 2
        if ($configuration.ready -eq $true) {
            $nativeReady = $true
            break
        }
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $nativeReady) {
    Stop-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue
    throw "The project017 native API did not become ready."
}

$cookieHeader = $null
$env:MINICLAW_COOKIE = $null

Write-Host "The project017 native runtime is ready."
Write-Host "API: http://127.0.0.1:$ApiPort"
Write-Host "Workspace: $workspaceJid"
Write-Host "AgentProfile: $profileAction, version $($runtimeProfile.version)"
Write-Host "No Session was created and no model message was submitted."

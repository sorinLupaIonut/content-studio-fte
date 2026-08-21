#Requires -Version 5.1
<#
.SYNOPSIS
    Build the image in Azure Container Registry and deploy both Container Apps.

.DESCRIPTION
    The declarative half lives in main.bicep. This script owns only the parts that
    cannot be declared: the resource group, the registry that has to exist before
    an image can be pushed into it, the build itself, and reading the secrets out
    of .env so they never appear in a template or in the command line.

    Safe to re-run. Every step either creates or updates.

    Secrets go into a parameters file written to the user's temp directory and
    deleted in the finally block, so they never reach the shell history, the
    process list, or the deployment record (the Bicep parameters are @secure()).

.EXAMPLE
    powershell -File infra/deploy.ps1

    The allowlist comes from AUTH_ALLOWED_EMAILS in .env. -AllowedEmails overrides
    it, but putting real addresses on a command line writes them to the shell
    history and the process list, so prefer .env.

.EXAMPLE
    powershell -File infra/deploy.ps1 -LocalBuild

    Same result, built on this machine. Use it when `az acr build` returns
    TasksOperationsNotAllowed: the serverless builder is refused to the
    subscription, while pushing to the same registry still works.

.EXAMPLE
    powershell -File infra/deploy.ps1 -SkipBuild

    Push a changed allowlist without rebuilding: edit AUTH_ALLOWED_EMAILS in .env,
    run this, and a new revision starts on the image already in the registry. This
    is how a tester is granted or revoked. Omitting -Tag is deliberate here - the
    tag is read back from the running app.
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = 'studio-viorela',
    [string]$Location      = 'eastus',
    [string]$NamePrefix    = 'studio',

    # Registry names are globally unique. Left empty, one is derived from the
    # subscription id, which keeps it stable across re-runs.
    [string]$AcrName       = '',

    [string]$Tag           = (Get-Date -Format 'yyyyMMdd-HHmm'),
    [string]$EnvFile       = '',

    # The harness refuses every address outside this list. Normally read from
    # AUTH_ALLOWED_EMAILS in .env; this parameter is the override.
    [string]$AllowedEmails = '',

    [string]$Model         = 'gpt-5-mini',

    # Deploy an image that is already in the registry instead of building again.
    [switch]$SkipBuild,

    # Build here with Docker and push, instead of building in Azure. Needed when
    # the subscription is refused ACR Tasks (TasksOperationsNotAllowed), which is
    # an Azure-side restriction on the registry, not a fault in this repository.
    [switch]$LocalBuild
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $EnvFile) { $EnvFile = Join-Path $repoRoot '.env' }

function Invoke-Az {
    param([string[]]$Arguments, [switch]$AsJson)

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "az $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    if ($AsJson) {
        if (-not $output) { return $null }
        return ($output | Out-String | ConvertFrom-Json)
    }
    return $output
}

function Read-DotEnv {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "No .env at $Path. The secrets have to come from somewhere."
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed) { continue }
        if ($trimmed.StartsWith('#')) { continue }
        $split = $trimmed.IndexOf('=')
        if ($split -lt 1) { continue }
        $key = $trimmed.Substring(0, $split).Trim()
        $value = $trimmed.Substring($split + 1).Trim()
        # Quoted values are common in .env files and the quotes are not part of
        # the value; a quoted connection string would fail to parse in asyncpg.
        if ($value.Length -ge 2) {
            $quoted = ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                      ($value.StartsWith("'") -and $value.EndsWith("'"))
            if ($quoted) { $value = $value.Substring(1, $value.Length - 2) }
        }
        $values[$key] = $value
    }
    return $values
}

Write-Host "== Studio Viorela - deploy to Azure Container Apps ==" -ForegroundColor Cyan

# --- 1. Who are we, and is anyone signed in -------------------------------
$account = Invoke-Az -AsJson -Arguments @('account', 'show', '--output', 'json')
Write-Host ("Subscription : {0} ({1})" -f $account.name, $account.id)
Write-Host ("Signed in as : {0}" -f $account.user.name)

if (-not $AcrName) {
    $suffix = ($account.id -replace '[^0-9a-zA-Z]', '').Substring(0, 8).ToLower()
    $AcrName = (($NamePrefix -replace '[^0-9a-zA-Z]', '') + $suffix).ToLower()
}
# Adding or removing a tester is an edit to AUTH_ALLOWED_EMAILS in .env followed
# by a re-run with -SkipBuild. That only works if -SkipBuild finds the image that
# is already running: left alone, -Tag defaults to the current timestamp and
# would deploy a tag that was never built, failing minutes later with an obscure
# pull error. Resolve the running tag instead, and refuse early if there is none.
if ($SkipBuild -and -not $PSBoundParameters.ContainsKey('Tag')) {
    $running = ''
    if ((& az group exists --name $ResourceGroup) -eq 'true') {
        $query = "[?name=='$NamePrefix-harness'].properties.template.containers[0].image | [0]"
        $running = (& az containerapp list --resource-group $ResourceGroup --query $query --output tsv | Out-String).Trim()
    }
    if (-not $running -or $running -eq 'None') {
        throw "-SkipBuild has nothing to reuse: $NamePrefix-harness is not deployed in $ResourceGroup. Run without -SkipBuild the first time, or pass -Tag."
    }
    $Tag = ($running -split ':')[-1]
    Write-Host ("Reusing      : the running image, tag {0}" -f $Tag)
}

$image = "content-studio:$Tag"
Write-Host ("Registry     : {0}" -f $AcrName)
Write-Host ("Image        : {0}" -f $image)

# --- 2. The secrets, read once, never printed -----------------------------
$dotenv = Read-DotEnv -Path $EnvFile
foreach ($required in @('DATABASE_URL', 'DATABASE_URL_DIRECT', 'OPENAI_API_KEY', 'E2B_API_KEY')) {
    if (-not $dotenv.ContainsKey($required) -or -not $dotenv[$required]) {
        throw "$required is missing from $EnvFile"
    }
}
# The same rule config.py enforces at runtime, checked before anything is built:
# a pooled endpoint used for migrations fails intermittently, long after it looked fine.
if ($dotenv['DATABASE_URL_DIRECT'] -like '*-pooler*') {
    throw "DATABASE_URL_DIRECT points at the pooled endpoint. Migrations must use the direct one."
}
Write-Host ("Secrets      : {0} read from .env, none printed" -f 4)

# The allowlist is deployment configuration, not source. It lives in .env beside
# the secrets so the client's address never reaches a command line, the shell
# history or a tracked file. The parameter still wins when it is given.
if (-not $AllowedEmails) { $AllowedEmails = $dotenv['AUTH_ALLOWED_EMAILS'] }
if (-not $AllowedEmails) {
    $AllowedEmails = $account.user.name
    Write-Warning "No AUTH_ALLOWED_EMAILS in $EnvFile and no -AllowedEmails; falling back to the signed-in account. Viorela will not get in."
}
$allowedCount = @($AllowedEmails -split ',' | Where-Object { $_.Trim() }).Count

# Easy Auth keeps the Google client secret as a container app secret, added by
# enable-auth.ps1. Bicep declares the secrets list, and a declared list is the
# whole truth to ARM - so deploying without this value here deletes the secret,
# the auth sidecar then fails to start, and the whole replica is marked
# unhealthy. Sign-in does not merely stop working; the application stops
# answering. Passing it through keeps the two scripts from undoing each other.
$googleClientSecret = $dotenv['GOOGLE_CLIENT_SECRET']
if ($googleClientSecret) {
    Write-Host "Sign-in      : Google client secret carried through, not printed"
} else {
    Write-Host "Sign-in      : no GOOGLE_CLIENT_SECRET in .env; Easy Auth not configured yet"
}
Write-Host ("Allowlist    : {0} address(es), not printed" -f $allowedCount)

# --- 3. Resource group ----------------------------------------------------
Write-Host "`n-- resource group --" -ForegroundColor Cyan
Invoke-Az -Arguments @(
    'group', 'create',
    '--name', $ResourceGroup,
    '--location', $Location,
    '--output', 'none'
) | Out-Null
Write-Host "$ResourceGroup in $Location"

# --- 4. Registry ----------------------------------------------------------
# It has to exist before an image can be pushed, so Bicep cannot own it.
Write-Host "`n-- container registry --" -ForegroundColor Cyan
$existing = Invoke-Az -AsJson -Arguments @(
    'acr', 'list',
    '--resource-group', $ResourceGroup,
    '--query', "[?name=='$AcrName']",
    '--output', 'json'
)
if (-not $existing -or @($existing).Count -eq 0) {
    # Admin user stays off: the apps pull with a managed identity instead.
    Invoke-Az -Arguments @(
        'acr', 'create',
        '--resource-group', $ResourceGroup,
        '--name', $AcrName,
        '--sku', 'Basic',
        '--admin-enabled', 'false',
        '--output', 'none'
    ) | Out-Null
    Write-Host "$AcrName created (Basic, admin disabled)"
} else {
    Write-Host "$AcrName already exists"
}

# --- 5. Build the image ---------------------------------------------------
if ($SkipBuild) {
    Write-Host "`n-- build skipped, using $image --" -ForegroundColor Yellow
} elseif ($LocalBuild) {
    Write-Host "`n-- docker build (ACR Tasks refused; building here) --" -ForegroundColor Cyan
    $reference = "$AcrName.azurecr.io/$image"
    Push-Location $repoRoot
    try {
        # Container Apps run linux/amd64. Docker would pick the host platform,
        # which is the same thing today and silently the wrong thing the day
        # this is run from an arm64 machine.
        & docker build --platform linux/amd64 --file Dockerfile --tag $reference .
        if ($LASTEXITCODE -ne 0) { throw "docker build failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
    # Admin user is off, so this is a token from the signed-in principal. It
    # needs AcrPush on the registry; an owner already has it.
    Invoke-Az -Arguments @('acr', 'login', '--name', $AcrName, '--output', 'none') | Out-Null
    & docker push $reference
    if ($LASTEXITCODE -ne 0) { throw "docker push failed with exit code $LASTEXITCODE" }
    Write-Host "built here and pushed: $reference"
} else {
    Write-Host "`n-- az acr build (this takes a few minutes) --" -ForegroundColor Cyan
    Push-Location $repoRoot
    try {
        # `.` is the build context and .dockerignore applies, so content/ and .env
        # never leave this machine.
        Invoke-Az -Arguments @(
            'acr', 'build',
            '--registry', $AcrName,
            '--image', $image,
            '--file', 'Dockerfile',
            '.'
        ) | Out-Null
    } finally {
        Pop-Location
    }
    Write-Host "built and pushed: $AcrName.azurecr.io/$image"
}

# --- 6. Everything declarative -------------------------------------------
Write-Host "`n-- deploying main.bicep --" -ForegroundColor Cyan
$parameters = @{
    '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'
    parameters     = @{
        location          = @{ value = $Location }
        namePrefix        = @{ value = $NamePrefix }
        acrName           = @{ value = $AcrName }
        image             = @{ value = $image }
        allowedEmails     = @{ value = $AllowedEmails }
        model             = @{ value = $Model }
        databaseUrl       = @{ value = $dotenv['DATABASE_URL'] }
        databaseUrlDirect = @{ value = $dotenv['DATABASE_URL_DIRECT'] }
        openaiApiKey      = @{ value = $dotenv['OPENAI_API_KEY'] }
        e2bApiKey         = @{ value = $dotenv['E2B_API_KEY'] }
        googleClientSecret = @{ value = $googleClientSecret }
    }
}

$parameterFile = Join-Path ([System.IO.Path]::GetTempPath()) ("studio-params-{0}.json" -f ([guid]::NewGuid().ToString('N')))
try {
    $json = $parameters | ConvertTo-Json -Depth 6
    # No BOM: az parses this with Python's json, which refuses one.
    [System.IO.File]::WriteAllText($parameterFile, $json, (New-Object System.Text.UTF8Encoding($false)))

    $deployment = Invoke-Az -AsJson -Arguments @(
        'deployment', 'group', 'create',
        '--resource-group', $ResourceGroup,
        '--name', "studio-$Tag",
        '--template-file', (Join-Path $PSScriptRoot 'main.bicep'),
        '--parameters', "@$parameterFile",
        '--output', 'json'
    )
} finally {
    if (Test-Path -LiteralPath $parameterFile) {
        Remove-Item -LiteralPath $parameterFile -Force
    }
}

$outputs = $deployment.properties.outputs

# --- 7. Does the thing we just shipped actually answer ---------------------
# Container Apps reports the deployment as succeeded once ARM is satisfied,
# which is before the new revision has served anything. Without this check a
# container that crashes on startup is discovered by whoever opens the page
# next; with it, the deploy that broke it says so.
$harnessUrl = $outputs.harnessUrl.value
Write-Host "`n-- health check --" -ForegroundColor Cyan
$healthy = $false
foreach ($attempt in 1..10) {
    try {
        $probe = Invoke-WebRequest -Uri "$harnessUrl/health" -UseBasicParsing -TimeoutSec 20
        if ($probe.StatusCode -eq 200) {
            $healthy = $true
            # /health answers 200 even while it reports `degraded`, so read the
            # body: a cold Neon compute is not a failed deploy, and a missing
            # key is.
            $body = $probe.Content | ConvertFrom-Json
            Write-Host ("status: {0}" -f $body.status)
            foreach ($name in $body.backends.PSObject.Properties.Name) {
                $backend = $body.backends.$name
                $mark = if ($backend.active) { 'ok  ' } else { 'down' }
                Write-Host ("  {0} {1}" -f $mark, $name)
            }
            break
        }
    } catch {
        Write-Host ("  attempt {0}/10 ..." -f $attempt)
        Start-Sleep -Seconds 6
    }
}
if (-not $healthy) {
    Write-Warning "The new revision did not answer /health. Roll back with:"
    Write-Warning ("  az containerapp revision list -n {0}-harness -g {1} -o table" -f $NamePrefix, $ResourceGroup)
    Write-Warning ("  az containerapp ingress traffic set -n {0}-harness -g {1} --revision-weight <previous>=100" -f $NamePrefix, $ResourceGroup)
    throw "Deployed, but the harness is not answering. See docs/RUNBOOK.md."
}

Write-Host "`n== deployed ==" -ForegroundColor Green
Write-Host ("Harness  : {0}" -f $outputs.harnessUrl.value)
Write-Host ("MCP      : {0}  (internal only)" -f $outputs.mcpUrl.value)
Write-Host ("Allowlist: {0} address(es) from {1}" -f $allowedCount, $EnvFile)

Write-Host "`nThe harness answers 401 to everything until sign-in is configured." -ForegroundColor Yellow
Write-Host "That is the safe state, not a fault. Next:" -ForegroundColor Yellow
Write-Host ("  powershell -File infra/enable-auth.ps1 -ResourceGroup {0} -NamePrefix {1}" -f $ResourceGroup, $NamePrefix)

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

    # ONE moving tag, not one per deploy. A timestamped tag left a local image and
    # a registry manifest behind every single time: 26 images and 1.5 GB locally,
    # 30 tags and 90 manifests in a Basic registry, for nothing anybody reads.
    #
    # The revision still changes, because what is deployed is the DIGEST this tag
    # resolves to, not the tag. Deploying `:current` twice would leave the Bicep
    # template byte-identical and Container Apps would create no new revision —
    # the deploy would appear to succeed and change nothing.
    [string]$Tag           = 'current',
    [string]$EnvFile       = '',

    # Untagged manifests kept in the registry after a deploy. They are what the
    # older revisions point at, so this is the rollback depth: 0 would make
    # `az containerapp revision restart` on anything but the newest fail to pull.
    [int]$KeepImages       = 3,

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
    # The whole reference, not a tag split off the end. What is running is now a
    # digest — `content-studio@sha256:abc…` — and splitting that on ':' yields
    # the hex, which is not a tag and would deploy nothing that exists.
    $reused = $running -replace "^$([regex]::Escape($AcrName)).azurecr.io/", ''
    Write-Host ("Reusing      : the running image, {0}" -f $reused)
}

$image = if ($reused) { $reused } else { "content-studio:$Tag" }
Write-Host ("Registry     : {0}" -f $AcrName)
Write-Host ("Image        : {0}" -f $image)

# --- 2. The secrets, read once, never printed -----------------------------
$dotenv = Read-DotEnv -Path $EnvFile
# E2B_API_KEY joined this list on 2026-08-31, four days late. The sandbox came
# back on the 27th and nothing here was told, so every deploy since produced a
# harness that could not generate anything - and said `ready` while doing it.
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
Write-Host ("Secrets      : {0} read from .env, none printed" -f 5)

# The allowlist is deployment configuration, not source. It lives in .env beside
# the secrets so the client's address never reaches a command line, the shell
# history or a tracked file. The parameter still wins when it is given.
if (-not $AllowedEmails) { $AllowedEmails = $dotenv['AUTH_ALLOWED_EMAILS'] }
if (-not $AllowedEmails) {
    $AllowedEmails = $account.user.name
    Write-Warning "No AUTH_ALLOWED_EMAILS in $EnvFile and no -AllowedEmails; falling back to the signed-in account. Viorela will not get in."
}
$allowedCount = @($AllowedEmails -split ',' | Where-Object { $_.Trim() }).Count

# Which of those addresses owns the original client. Being on the allowlist is
# permission to enter the studio; without this, it is also permission to land on
# her account, because an unprovisioned principal falls through to CLIENT_SLUG.
$clientOwnerEmail = $dotenv['CLIENT_OWNER_EMAIL']
if ($clientOwnerEmail) {
    Write-Host "Owner        : 1 address, not printed"
} else {
    Write-Warning "No CLIENT_OWNER_EMAIL in $EnvFile. Anyone allowed but not provisioned will land on the default client."
}

# Providers that carry their own allowlist - the external Entra tenant only
# Sorin can add people to. A principal arriving from one of these is let in
# without being named in AUTH_ALLOWED_EMAILS, and gets a studio written on its
# first request. Empty is the safe default and leaves every door as it was.
$selfProvisionProviders = $dotenv['AUTH_SELF_PROVISION_PROVIDERS']
# Carried through for the same reason as the Google one: bicep declares the
# secrets list, and a declared list is the whole truth to ARM. Left out here,
# this deployment would delete the secret that Easy Auth's studio-account
# provider references, and the auth sidecar would fail to start.
$entraClientSecret = $dotenv['ENTRA_CLIENT_SECRET']

# Decision 7, surface 4. All three are optional and empty is a supported state -
# the harness reports the surface as off and everything else runs unchanged. Read
# here rather than defaulted in bicep so that removing them from .env actually
# turns Phoenix off, instead of leaving a stale secret behind on the revision.
$phoenixEndpoint = $dotenv['PHOENIX_COLLECTOR_ENDPOINT']
$phoenixApiKey   = $dotenv['PHOENIX_API_KEY']
$phoenixProject  = $dotenv['PHOENIX_PROJECT_NAME']
if (-not $phoenixEndpoint) { $phoenixEndpoint = '' }
if (-not $phoenixApiKey)   { $phoenixApiKey = '' }
if (-not $phoenixProject)  { $phoenixProject = 'studio-viorela' }
if ($phoenixApiKey) {
    Write-Host ("Phoenix      : {0}, key read from .env, not printed" -f $phoenixProject)
} else {
    Write-Host "Phoenix      : no PHOENIX_API_KEY in .env; the fourth surface stays off"
}
if ($selfProvisionProviders) {
    Write-Host ("Self-signup  : {0}" -f $selfProvisionProviders)
} else {
    Write-Host "Self-signup  : none; only the allowlisted addresses get in"
}

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

    # Deploy the digest, not the tag. `:current` is the same string on every run,
    # so Bicep would produce an identical template and Container Apps would make
    # no revision — a deploy that reports success and ships nothing.
    $repoDigest = (& docker inspect --format '{{index .RepoDigests 0}}' $reference | Out-String).Trim()
    if ($repoDigest -match '@(sha256:[0-9a-f]{64})$') {
        $image = "content-studio@$($Matches[1])"
        Write-Host ("Deploying    : {0}" -f $image)
    } else {
        Write-Warning "No digest on $reference; deploying by tag, which may not create a new revision."
    }

    # The previous build held this same tag, so retagging left it dangling. This
    # is the whole cleanup locally: one prune, and only ever untagged layers.
    & docker image prune -f | Out-Null
    # The build cache is the real hog — 5.4 GB against 1.5 GB of images when this
    # was written. Bounded, not emptied: an empty cache makes the next build slow.
    & docker builder prune -f --max-used-space 2GB 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { & docker builder prune -f --keep-storage 2GB 2>$null | Out-Null }
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
        clientOwnerEmail  = @{ value = $clientOwnerEmail }
        selfProvisionProviders = @{ value = $selfProvisionProviders }
        model             = @{ value = $Model }
        databaseUrl       = @{ value = $dotenv['DATABASE_URL'] }
        databaseUrlDirect = @{ value = $dotenv['DATABASE_URL_DIRECT'] }
        openaiApiKey      = @{ value = $dotenv['OPENAI_API_KEY'] }
        e2bApiKey         = @{ value = $dotenv['E2B_API_KEY'] }
        googleClientSecret = @{ value = $googleClientSecret }
        entraClientSecret  = @{ value = $entraClientSecret }
        phoenixCollectorEndpoint = @{ value = $phoenixEndpoint }
        phoenixApiKey            = @{ value = $phoenixApiKey }
        phoenixProjectName       = @{ value = $phoenixProject }
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
# --- Registry housekeeping ------------------------------------------------
# Retagging `:current` orphans the manifest the previous deploy pushed, and an
# orphan is invisible but still billed: this registry reached 30 tags and 90
# manifests before anyone looked. Basic SKU includes 10 GB, and each of these is
# ~440 MB.
#
# DELETE BY TAG, NEVER BY "untagged". buildx pushes an OCI image INDEX under the
# tag, and that index references two manifests that carry no tag of their own:
# the linux/amd64 image and an attestation. So "untagged" here does not mean
# "orphaned" - it means "a child of a tag that is very much in use", and a
# cleanup that walks `[?tags==null]` deletes the running image out from under
# production. This registry had 30 tags and exactly 60 untagged manifests, which
# is what that arithmetic looks like from the outside.
#
# The children are collected from each index BEFORE its tag goes, then deleted
# after. Anything still referenced by a surviving tag is never in that list.
if (-not $SkipBuild -and $KeepImages -ge 1) {
    Write-Host "`n-- registry housekeeping --" -ForegroundColor Cyan
    # `az acr manifest` is a preview command and prints a WARNING to stderr on
    # every call. Under $ErrorActionPreference = 'Stop' that warning becomes a
    # terminating NativeCommandError, which on 2026-08-24 killed the deploy AFTER
    # the app was already updated - the health check never ran. Housekeeping must
    # never be able to fail a deployment that has otherwise succeeded.
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $tags = @(& az acr repository show-tags --name $AcrName `
            --repository content-studio --orderby time_desc --output tsv 2>$null)
        $stale = @($tags | Select-Object -Skip $KeepImages)
        $orphans = [System.Collections.Generic.List[string]]::new()
        foreach ($tag in $stale) {
            $index = & az acr manifest show --registry $AcrName `
                --name "content-studio:$tag" --output json 2>$null | ConvertFrom-Json
            foreach ($child in @($index.manifests)) { $orphans.Add($child.digest) }
            & az acr repository delete --name $AcrName `
                --image "content-studio:$tag" --yes --output none 2>$null
        }
        # A child is only really an orphan once nothing tagged points at it: the same
        # base layers get re-referenced across builds, and an index that survived
        # this round may well name a digest an index that did not also named.
        $kept = @(& az acr repository show-tags --name $AcrName `
            --repository content-studio --output tsv 2>$null)
        $alive = [System.Collections.Generic.HashSet[string]]::new()
        foreach ($tag in $kept) {
            $index = & az acr manifest show --registry $AcrName `
                --name "content-studio:$tag" --output json 2>$null | ConvertFrom-Json
            foreach ($child in @($index.manifests)) { [void]$alive.Add($child.digest) }
        }
        $removed = 0
        foreach ($digest in ($orphans | Select-Object -Unique)) {
            if ($alive.Contains($digest)) { continue }
            & az acr manifest delete --registry $AcrName `
                --name "content-studio@$digest" --yes --output none 2>$null
            if ($LASTEXITCODE -eq 0) { $removed++ }
        }
        Write-Host ("taguri: {0} pastrate, {1} sterse; manifeste-copil sterse: {2}" -f `
            [Math]::Min($tags.Count, $KeepImages), $stale.Count, $removed)
    } catch {
        Write-Warning "curatenia registrului a esuat, deploy-ul e neatins: $_"
    } finally {
        $ErrorActionPreference = $previousEap
    }
}

$harnessUrl = $outputs.harnessUrl.value
Write-Host "`n-- health check --" -ForegroundColor Cyan
$healthy = $false
$body = $null
# Answering at all is not the same as being ready. The two apps roll
# independently, so the first 200 often arrives while studio-mcp is still coming
# up - which used to print a `down mcp` that meant nothing but looked alarming.
# Keep asking until it says ready, then stop.
foreach ($attempt in 1..12) {
    try {
        $probe = Invoke-WebRequest -Uri "$harnessUrl/health" -UseBasicParsing -TimeoutSec 20
        if ($probe.StatusCode -eq 200) {
            $healthy = $true
            # /health answers 200 even while it reports `degraded`, so read the
            # body: a cold Neon compute is not a failed deploy, and a missing
            # key is.
            $body = $probe.Content | ConvertFrom-Json
            if ($body.status -eq 'ready') { break }
            Write-Host ("  not ready yet ({0}/12) ..." -f $attempt)
        }
    } catch {
        Write-Host ("  no answer yet ({0}/12) ..." -f $attempt)
    }
    Start-Sleep -Seconds 8
}
if ($body) {
    Write-Host ("status: {0}" -f $body.status)
    foreach ($name in $body.backends.PSObject.Properties.Name) {
        $backend = $body.backends.$name
        $mark = if ($backend.active) { 'ok  ' } else { 'down' }
        Write-Host ("  {0} {1}" -f $mark, $name)
    }
    if ($body.status -ne 'ready') {
        # Still not a failed deploy: the container answers, so a person can look.
        # `artifacts` is inactive on purpose and never counts against readiness.
        Write-Warning "The harness answers but reports 'degraded'. See docs/RUNBOOK.md."
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

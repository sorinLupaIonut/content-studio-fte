#Requires -Version 5.1
<#
.SYNOPSIS
    Put Google sign-in in front of the harness (Container Apps Easy Auth).

.DESCRIPTION
    Runs after deploy.ps1, because the redirect URI contains the FQDN that does
    not exist until the app does.

    Until this has run, the harness is reachable but answers 401 to every request:
    auth.py resolves identity only from the `x-ms-client-principal-*` headers the
    platform injects, and refuses when they are absent. That is a closed door, not
    an open one - deploying before this step is safe.

    Two layers end up guarding the app, and both matter. Easy Auth decides who may
    reach the container at all; AUTH_ALLOWED_EMAILS inside the harness decides who
    is Viorela. Google will let any Google account through the first door - the
    second one is what keeps the workspace to two people.

    Google, not Entra, because the two identities the client actually uses are
    Google accounts. Azure cannot mint those credentials, so this runs in two
    passes: the first prints the redirect URI to register in Google Cloud Console,
    the second configures Easy Auth once GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
    are in .env.

.EXAMPLE
    powershell -File infra/enable-auth.ps1 -ResourceGroup studio-viorela
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = 'studio-viorela',
    [string]$NamePrefix    = 'studio',
    [string]$EnvFile       = ''
)

$ErrorActionPreference = 'Stop'
$appName = "$NamePrefix-harness"

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

# Same parser as deploy.ps1. Kept local so either script runs on its own.
function Read-DotEnv {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) { return @{} }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed) { continue }
        if ($trimmed.StartsWith('#')) { continue }
        $split = $trimmed.IndexOf('=')
        if ($split -lt 1) { continue }
        $key = $trimmed.Substring(0, $split).Trim()
        $value = $trimmed.Substring($split + 1).Trim()
        if ($value.Length -ge 2) {
            $quoted = ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                      ($value.StartsWith("'") -and $value.EndsWith("'"))
            if ($quoted) { $value = $value.Substring(1, $value.Length - 2) }
        }
        $values[$key] = $value
    }
    return $values
}

Write-Host "== Google sign-in for $appName ==" -ForegroundColor Cyan

# Read through the generic resource provider so this step does not depend on the
# containerapp extension any earlier than it has to.
$app = Invoke-Az -AsJson -Arguments @(
    'resource', 'show',
    '--resource-group', $ResourceGroup,
    '--name', $appName,
    '--resource-type', 'Microsoft.App/containerApps',
    '--output', 'json'
)
$fqdn = $app.properties.configuration.ingress.fqdn
if (-not $fqdn) { throw "$appName has no ingress FQDN. Has deploy.ps1 run?" }

# Easy Auth fixes this path; Google rejects the sign-in if the registered URI
# differs by even a trailing slash.
$redirectUri = "https://$fqdn/.auth/login/google/callback"

# --- 1. The Google credentials --------------------------------------------
$dotenv = Read-DotEnv -Path $EnvFile
$clientId     = $dotenv['GOOGLE_CLIENT_ID']
$clientSecret = $dotenv['GOOGLE_CLIENT_SECRET']

if (-not $clientId -or -not $clientSecret) {
    Write-Host "`n-- first pass: register the OAuth client --" -ForegroundColor Yellow
    Write-Host @"

Azure cannot create Google credentials. Do this once, in Google Cloud Console:

  1. console.cloud.google.com -> APIs & Services -> Credentials
  2. Create credentials -> OAuth client ID -> Web application
  3. Authorised redirect URI - exactly this, no trailing slash:

       $redirectUri

  4. Copy the client ID and client secret into $EnvFile

       GOOGLE_CLIENT_ID=...
       GOOGLE_CLIENT_SECRET=...

  5. Run this script again.

.env is git-ignored and never enters the image, which is where those two
belong - not on a command line, not in the template.
"@
    Write-Host "Nothing was changed. The harness still answers 401 to everything." -ForegroundColor Yellow
    return
}

Write-Host "Redirect URI : $redirectUri"
Write-Host "Client ID    : $($clientId.Substring(0, [Math]::Min(12, $clientId.Length)))..."

# --- 2. Easy Auth on the container app ------------------------------------
# `az containerapp` is an extension. Azure installs it on first use.
Write-Host "`n-- configuring Easy Auth --" -ForegroundColor Cyan
Invoke-Az -Arguments @(
    'containerapp', 'auth', 'google', 'update',
    '--resource-group', $ResourceGroup,
    '--name', $appName,
    '--client-id', $clientId,
    '--client-secret', $clientSecret,
    '--yes',
    '--output', 'none'
) | Out-Null

# No --excluded-paths: the liveness probe reaches port 8000 directly, inside the
# environment, so it never passes through Easy Auth and cannot be locked out.
Invoke-Az -Arguments @(
    'containerapp', 'auth', 'update',
    '--resource-group', $ResourceGroup,
    '--name', $appName,
    '--enabled', 'true',
    '--action', 'RedirectToLoginPage',
    '--redirect-provider', 'google',
    # No --token-store. Enabling it demands a blob storage account with a SAS
    # URL, because Container Apps has nowhere else to keep the tokens, and the
    # command fails outright without one. Nothing here needs a stored token:
    # auth.py reads identity from the x-ms-client-principal-* headers the
    # platform injects on every request and never calls a Google API on the
    # user's behalf. A token store would be a second copy of a credential kept
    # for no reader.
    '--require-https', 'true',
    '--output', 'none'
) | Out-Null

Remove-Variable clientSecret

Write-Host "`n== sign-in is on ==" -ForegroundColor Green
Write-Host "https://$fqdn"
Write-Host "`nAn unauthenticated visitor is now sent to the Google login page."
Write-Host "Any Google account gets past that door. AUTH_ALLOWED_EMAILS is the one"
Write-Host "that decides who is Viorela - confirm it holds both addresses:"
Write-Host ("  az containerapp show -g {0} -n {1} --query ""properties.template.containers[0].env[?name=='AUTH_ALLOWED_EMAILS']""" -f $ResourceGroup, $appName)
Write-Host "`nAfter both identities have signed in once, move the allowlist to stable"
Write-Host "principal IDs (AUTH_ALLOWED_PRINCIPAL_IDS); an email can be re-pointed,"
Write-Host "a Google subject id cannot."

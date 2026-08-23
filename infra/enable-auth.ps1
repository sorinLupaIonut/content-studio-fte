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
        # Redact the value after any secret-bearing flag before echoing the
        # command. Without this a single failed call prints the client secret
        # to the console, into the shell's scrollback and into whatever is
        # capturing the run - which is how a secret quietly stops being one.
        $safe = @()
        for ($i = 0; $i -lt $Arguments.Count; $i++) {
            $safe += $Arguments[$i]
            if ($Arguments[$i] -in @('--client-secret', '--password', '--secrets')) {
                $i++
                $safe += '<redacted>'
            }
        }
        throw "az $($safe -join ' ') failed with exit code $LASTEXITCODE"
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
    # AllowAnonymous, not RedirectToLoginPage: the application has its own
    # sign-in page. The static shell is public either way; every /api/* route
    # demands the injected identity headers and answers 401 without them, so
    # the data stays behind the platform's door. The UI turns that 401 into
    # the sign-in screen and sends the browser to /.auth/login/google itself.
    '--action', 'AllowAnonymous',
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

# --- 3. The studio account provider (Entra External ID) -------------------
# A second door, alongside Google rather than instead of it. Google identifies
# people who already have an account somewhere; this one identifies people Sorin
# created himself, in a directory nobody can enrol into. That difference is why
# the harness may skip its allowlist for this provider and write a studio on
# first sign-in - see AUTH_SELF_PROVISION_PROVIDERS in config.py.
#
# The provider NAME is the contract between three places: the /.auth/login path
# the interface links to, the value in AUTH_SELF_PROVISION_PROVIDERS, and this
# registration. Change it in one and the button leads nowhere.
$entraProvider = 'entra'
$entraRedirect = "https://$fqdn/.auth/login/$entraProvider/callback"

$entraTenant   = $dotenv['ENTRA_TENANT_SUBDOMAIN']
$entraClientId = $dotenv['ENTRA_CLIENT_ID']
$entraSecret   = $dotenv['ENTRA_CLIENT_SECRET']

if (-not $entraTenant -or -not $entraClientId -or -not $entraSecret) {
    Write-Host "`n-- studio accounts: not configured, skipped --" -ForegroundColor Yellow
    Write-Host @"

Google sign-in above is unaffected. To add username-and-password accounts you
create yourself, do this once in the Azure portal, then run this script again:

  1. Create a Microsoft Entra External ID tenant (external, not workforce).
  2. In it: User flows -> new sign-up and sign-in flow.
  3. App registrations -> new registration. Redirect URI, Web, exactly this:

       $entraRedirect

     Then Certificates & secrets -> new client secret.
  4. Associate the application with the user flow.
  5. Turn OFF self-service sign-up. There is no button for it; one Graph call,
     signed in as an administrator of the new tenant:

       PATCH https://graph.microsoft.com/beta/identity/authenticationEventsFlows/{id}
       { "onInteractiveAuthFlowStart": { "isSignUpAllowed": false } }

     Until this runs, anybody who finds the sign-in page can enrol themselves -
     and would be given a studio automatically. It is not optional.
  6. Put these into ${EnvFile}:

       ENTRA_TENANT_SUBDOMAIN=...        # the bit before .ciamlogin.com
       ENTRA_CLIENT_ID=...
       ENTRA_CLIENT_SECRET=...
       AUTH_SELF_PROVISION_PROVIDERS=$entraProvider

  7. Run infra/deploy.ps1 -SkipBuild FIRST - it carries the secret and the
     AUTH_SELF_PROVISION_PROVIDERS value into the running app - and only then
     run this script, which points Easy Auth at the secret by name.
"@
} else {
    Write-Host "`n-- studio accounts: configuring $entraProvider --" -ForegroundColor Cyan
    Write-Host "Redirect URI : $entraRedirect"

    # The external tenant's OpenID metadata. `ciamlogin.com` is the external-tenant
    # host; a workforce tenant would be `login.microsoftonline.com` and is
    # deliberately not what this is for.
    $entraConfig = "https://$entraTenant.ciamlogin.com/$entraTenant.onmicrosoft.com/v2.0/.well-known/openid-configuration"

    # `add` fails on a provider that already exists and `update` fails on one that
    # does not, so ask first. Re-running this script has to stay safe.
    #
    # Asked through `auth show` rather than `openid-connect show`: the latter
    # writes to stderr when the provider is absent, and under
    # $ErrorActionPreference = 'Stop' PowerShell turns a native command's stderr
    # into a terminating error - so the check for "does it exist" would abort
    # the script precisely when the answer is no.
    $existing = az containerapp auth show `
        --resource-group $ResourceGroup --name $appName `
        --query "identityProviders.customOpenIdConnectProviders.$entraProvider.registration.clientId" `
        --output tsv
    $verb = if ($existing) { 'update' } else { 'add' }

    # By NAME, not by value. Two reasons: the secret then never reaches a command
    # line or a process list, and `openid-connect add` refuses a literal secret
    # anyway - unlike the Google command it will not create the container app
    # secret for you, it only references one that already exists. main.bicep
    # writes it, from .env, through a parameters file.
    $secretName = 'entra-authentication-secret'
    $known = az containerapp secret list `
        --resource-group $ResourceGroup --name $appName `
        --query "[?name=='$secretName'].name" --output tsv
    if (-not $known) {
        throw "The container app has no secret named '$secretName'. Run infra/deploy.ps1 -SkipBuild first: it carries ENTRA_CLIENT_SECRET from .env into the app, and this command can only point at a secret that is already there."
    }

    $arguments = @(
        'containerapp', 'auth', 'openid-connect', $verb,
        '--resource-group', $ResourceGroup,
        '--name', $appName,
        '--provider-name', $entraProvider,
        '--client-id', $entraClientId,
        '--client-secret-name', $secretName,
        '--yes',
        '--output', 'none'
    )
    # Only `add` takes the metadata endpoint; `update` carries the client
    # credentials and nothing else.
    # Three values, not one string: `--scopes 'openid profile email'` is stored as a
    # single scope named "openid profile email", which is not what any of them mean.
    if ($verb -eq 'add') { $arguments += @('--openid-configuration', $entraConfig, '--scopes', 'openid', 'profile', 'email') }

    Invoke-Az -Arguments $arguments | Out-Null
    Remove-Variable entraSecret

    Write-Host "Provider     : $entraProvider ($verb)"
    Write-Host "Metadata     : $entraConfig"
    # `--redirect-provider google` is left as it is on purpose: under
    # AllowAnonymous the platform never redirects on its own, so the value is
    # inert. The interface always names the provider in the /.auth/login path.
}

Write-Host "`n== sign-in is on ==" -ForegroundColor Green
Write-Host "https://$fqdn"
Write-Host "`nAn unauthenticated visitor gets the application's own sign-in page;"
Write-Host "the data routes keep answering 401 until Google confirms an identity."
Write-Host "Any Google account gets past that door. AUTH_ALLOWED_EMAILS is the one"
Write-Host "that decides who is Viorela - confirm it holds both addresses:"
Write-Host ("  az containerapp show -g {0} -n {1} --query ""properties.template.containers[0].env[?name=='AUTH_ALLOWED_EMAILS']""" -f $ResourceGroup, $appName)
Write-Host "`nAfter both identities have signed in once, move the allowlist to stable"
Write-Host "principal IDs (AUTH_ALLOWED_PRINCIPAL_IDS); an email can be re-pointed,"
Write-Host "a Google subject id cannot."

#Requires -Version 5.1
<#
.SYNOPSIS
    Delete everything this deployment created in Azure.

.DESCRIPTION
    Deletes the resource group, which takes the registry, the built images, the
    environment, both apps and the Log Analytics workspace with it.

    It does NOT touch Neon. The database, the posts and the audit log live outside
    Azure and survive this untouched - that is the point of the split.

    The Google OAuth client is not touched either, and cannot be from here: it is
    a Google Cloud Console object, not an Azure one. Re-deploying later reuses the
    same client - only the redirect URI changes, because the FQDN does.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$ResourceGroup = 'studio-viorela',
    [switch]$Wait
)

$ErrorActionPreference = 'Stop'

$account = & az account show --output json
if ($LASTEXITCODE -ne 0) { throw 'Not signed in. Run: az login --use-device-code' }
$account = $account | Out-String | ConvertFrom-Json

Write-Host ("Subscription : {0}" -f $account.name)
Write-Host ("Deleting     : resource group {0}" -f $ResourceGroup) -ForegroundColor Yellow

$resources = & az resource list --resource-group $ResourceGroup --query "[].{name:name,type:type}" --output table
if ($LASTEXITCODE -ne 0) {
    Write-Host "No such resource group. Nothing to do."
    return
}
$resources | Write-Host

if (-not $PSCmdlet.ShouldProcess($ResourceGroup, 'Delete resource group and everything in it')) {
    Write-Host 'Cancelled.'
    return
}

$deleteArgs = @('group', 'delete', '--name', $ResourceGroup, '--yes')
if (-not $Wait) { $deleteArgs += '--no-wait' }
& az @deleteArgs
if ($LASTEXITCODE -ne 0) { throw "az group delete failed with exit code $LASTEXITCODE" }

if ($Wait) {
    Write-Host 'Deleted.' -ForegroundColor Green
} else {
    Write-Host 'Deletion started; Azure finishes it in the background.' -ForegroundColor Green
}

Write-Host "`nNeon is untouched. The posts, the audit log and the runs are all still there."
Write-Host "So is the Google OAuth client: it lives in Google Cloud Console, outside Azure."
Write-Host "Delete it there if this is the end, or leave it - re-deploying only needs the"
Write-Host "new redirect URI added to the same client."

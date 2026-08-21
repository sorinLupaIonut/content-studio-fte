#Requires -Version 5.1
<#
.SYNOPSIS
    Put a monthly cost alert on the studio's resource group.

.DESCRIPTION
    Run once. Re-running is safe and updates the amount or the address.

    This warns; it does not stop anything. Azure budgets cannot stop spending,
    and the per-account gate inside the application is a different mechanism
    answering a different question - see docs/RUNBOOK.md §4.

.EXAMPLE
    powershell -File infra/cost-alert.ps1 -Email you@example.com -MonthlyBudget 25
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [int]$MonthlyBudget = 25,
    [string]$ResourceGroup = 'studio-viorela',
    [string]$NamePrefix    = 'studio'
)

$ErrorActionPreference = 'Stop'

# A budget's start date must be the first of a month, and Azure refuses one in
# the past beyond a year - so the current month is both correct and always valid.
$startDate = (Get-Date -Format 'yyyy-MM-01')

Write-Host "== cost alert ==" -ForegroundColor Cyan
Write-Host ("Resource group : {0}" -f $ResourceGroup)
Write-Host ("Monthly budget : {0}" -f $MonthlyBudget)
Write-Host ("Starts         : {0}" -f $startDate)
Write-Host  "Email          : not printed"

& az deployment group create `
    --resource-group $ResourceGroup `
    --name ("cost-alert-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmm')) `
    --template-file (Join-Path $PSScriptRoot 'cost-alert.bicep') `
    --parameters email=$Email monthlyBudget=$MonthlyBudget namePrefix=$NamePrefix startDate=$startDate `
    --output none

if ($LASTEXITCODE -ne 0) { throw "az deployment group create failed with exit code $LASTEXITCODE" }

Write-Host "`nDone. Warnings at 50%, 80% and 100% of the monthly amount." -ForegroundColor Green
Write-Host "Azure budgets warn; they never stop a resource." -ForegroundColor Yellow

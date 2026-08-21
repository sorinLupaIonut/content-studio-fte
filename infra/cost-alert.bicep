// A monthly cost alert on the resource group.
//
// This is not the budget gate. The gate in `accounts.py` bounds what one person
// may spend on models, and knows nothing about Azure; this bounds what the
// *infrastructure* costs, and knows nothing about people. A runaway container,
// a log workspace ingesting a loop, a registry filling with images - none of
// those touch the gate, and all of them show up here.
//
// Alerts only. Azure budgets do not stop anything, and a budget that claimed to
// would be worse than one that is honest about warning.

targetScope = 'resourceGroup'

@description('Where the warnings are sent.')
param email string

@description('Monthly ceiling, in the billing currency.')
param monthlyBudget int = 25

@description('Prefix every resource name starts with.')
param namePrefix string = 'studio'

@description('First day of the month the budget starts counting from, yyyy-MM-01.')
param startDate string

resource alerts 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${namePrefix}-cost-alerts'
  location: 'global'
  properties: {
    // Eight characters is the hard limit, and the portal truncates silently.
    groupShortName: 'studioCost'
    enabled: true
    emailReceivers: [
      {
        name: 'owner'
        emailAddress: email
        useCommonAlertSchema: true
      }
    ]
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: '${namePrefix}-monthly'
  properties: {
    category: 'Cost'
    amount: monthlyBudget
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    notifications: {
      // Half is early enough to look; four fifths is late enough to act. Both
      // on Actual rather than Forecasted: a forecast on a two-week-old resource
      // group is mostly noise.
      half: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: [email]
        contactGroups: [alerts.id]
      }
      most: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [email]
        contactGroups: [alerts.id]
      }
      over: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: [email]
        contactGroups: [alerts.id]
      }
    }
  }
}

output budgetName string = budget.name
output actionGroupName string = alerts.name

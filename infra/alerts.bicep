// Two alerts, and only two.
//
// The cost alert (cost-alert.bicep) answers "is this getting expensive". These
// answer "is it broken", which is the other question you cannot ask by looking.
// Everything else a monitoring product would offer - latency percentiles,
// dependency maps, availability tests from five continents - is measurement for
// a system with users to disappoint. This one has three accounts.
//
// Deliberately NOT here: an Application Insights availability test. A standard
// web test at five-minute intervals from three locations runs about 26,000
// times a month, which on this subscription would be a meaningful slice of the
// whole budget - to learn something the container's own health probe already
// knows and the restart alert below already reports.

targetScope = 'resourceGroup'

@description('Prefix every resource name starts with.')
param namePrefix string = 'studio'

@description('Where the warnings are sent. Reuses the cost alert action group.')
param actionGroupName string = '${namePrefix}-cost-alerts'

resource notify 'Microsoft.Insights/actionGroups@2023-01-01' existing = {
  name: actionGroupName
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: '${namePrefix}-logs'
}

// 1. The application is throwing.
//
// 5xx only. A 401 is also a "failed request" to Application Insights, and this
// application answers 401 to every unauthenticated probe on the open internet -
// alerting on those would mean an alert every few minutes forever, which is the
// same as no alerts at all, only louder.
resource serverErrors 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: '${namePrefix}-server-errors'
  location: resourceGroup().location
  properties: {
    displayName: 'Studio: the harness is returning 5xx or throwing'
    severity: 1
    enabled: true
    // The workspace, not the Application Insights component. This is a
    // workspace-based resource, so the telemetry lands in `AppRequests` and
    // `AppExceptions` there; a rule scoped to the component would be reading the
    // classic schema (`requests`, `exceptions`) and finds no such table.
    scopes: [logs.id]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: '''
union
  (AppRequests | where toint(ResultCode) >= 500),
  (AppExceptions)
| summarize Count = count()
'''
          timeAggregation: 'Total'
          metricMeasureColumn: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [notify.id]
    }
  }
}

// 2. A replica died and came back.
//
// A container that crashes on startup is restarted forever by the platform, and
// from the outside that looks like an application which is merely slow. The
// system log is where it says so.
resource restarts 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: '${namePrefix}-replica-restarts'
  location: resourceGroup().location
  properties: {
    displayName: 'Studio: a container replica is restarting'
    severity: 2
    enabled: true
    scopes: [logs.id]
    evaluationFrequency: 'PT30M'
    windowSize: 'PT30M'
    criteria: {
      allOf: [
        {
          query: '''
ContainerAppSystemLogs_CL
| where Reason_s in ("BackOff", "ContainerCrashed", "ProbeFailed", "Killing")
| summarize Count = count()
'''
          timeAggregation: 'Total'
          metricMeasureColumn: 'Count'
          operator: 'GreaterThan'
          // One restart is Container Apps recycling a scaled-to-zero replica,
          // which is normal. Three inside half an hour is a loop.
          threshold: 3
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [notify.id]
    }
  }
}

output serverErrorsRule string = serverErrors.name
output restartsRule string = restarts.name

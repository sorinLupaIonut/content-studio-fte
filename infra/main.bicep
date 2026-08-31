// Studio Viorela — Decision 3. One image, two Container Apps.
//
// Locked decision 6: a single multi-stage image runs both roles, and the role is
// chosen by the command. The harness keeps the image's own CMD (uvicorn); the
// content-data server overrides it with `content-studio-server`.
//
// Locked decision 5: only the harness is reachable from the internet. The MCP
// server gets internal ingress, so it does not exist outside the environment.
//
// The registry is never given a password. Both apps pull with a user-assigned
// managed identity holding AcrPull, so this deployment stores no registry
// credentials anywhere.

@description('Region for every resource. East US keeps the compute next to Neon (us-east-1).')
param location string = resourceGroup().location

@description('Prefix every resource name starts with.')
param namePrefix string = 'studio'

@description('The one signed-in address allowed to reach the default client without an account row. Empty keeps the old fall-through for everyone.')
param clientOwnerEmail string = ''

@description('Name of the existing Azure Container Registry that holds the image.')
param acrName string

@description('Repository and tag inside that registry, e.g. content-studio:20260819-2130.')
param image string

@description('Comma-separated e-mail allowlist. The harness refuses every address outside it.')
param allowedEmails string

@description('Easy Auth providers whose principals are let in without the allowlist and get a studio on first sign-in. Only for a directory nobody can enrol themselves into. Empty disables it.')
param selfProvisionProviders string = ''

@description('Bulk generation and chat model. Matches the default in config.py.')
param model string = 'gpt-5-mini'

@secure()
@description('Neon pooled endpoint — what the running app uses.')
param databaseUrl string

@secure()
@description('Neon direct endpoint — migrations only, never pooled.')
param databaseUrlDirect string

@secure()
param openaiApiKey string

// THE OUTAGE THIS PARAMETER EXISTS TO PREVENT: the sandbox came back on
// 2026-08-27 and this template was not told. From that day until 2026-08-31 the
// deployed harness had no E2B_API_KEY, every generation died in a third of a
// second, and /health reported four green backends because nothing checked the
// one door the method travels through. Required, not defaulted to empty: a
// harness without it cannot generate anything, so an empty deploy should fail
// here rather than in front of the client.
@secure()
@description('E2B key. The method is read from a container; without it no run can start.')
param e2bApiKey string

@description('Google OAuth client secret for Easy Auth. Empty leaves sign-in untouched.')
@secure()
param googleClientSecret string = ''

@description('Client secret of the Entra external tenant application, for the studio-account sign-in. Empty leaves that provider unconfigured.')
@secure()
param entraClientSecret string = ''

@description('Phoenix Cloud collector endpoint. Empty leaves the fourth surface off.')
param phoenixCollectorEndpoint string = ''

@secure()
@description('Phoenix Cloud API key. Empty leaves the fourth surface off.')
param phoenixApiKey string = ''

@description('Which Phoenix project the spans land in.')
param phoenixProjectName string = 'studio-viorela'

var harnessAppName = '${namePrefix}-harness'
var mcpAppName = '${namePrefix}-mcp'
var fullImage = '${acr.properties.loginServer}/${image}'

// AcrPull. The GUID is Azure's own and is identical in every subscription.
var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource pullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-pull'
  location: location
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, pullIdentity.id, acrPullRoleId)
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: pullIdentity.properties.principalId
    // Stated explicitly: without it the assignment can fail while the identity is
    // still replicating through Entra, and the error names nothing useful.
    principalType: 'ServicePrincipal'
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// Workspace-based Application Insights, attached to the workspace that already
// exists for the Container Apps environment. One place to look, not two: the
// container's stdout and the application's traces land in the same store, and a
// `run_id` joins them.
resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    IngestionMode: 'LogAnalytics'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var identityBlock = {
  type: 'UserAssigned'
  userAssignedIdentities: {
    '${pullIdentity.id}': {}
  }
}

var registryBlock = [
  {
    server: acr.properties.loginServer
    identity: pullIdentity.id
  }
]

// Internal ingress publishes `<app>.internal.<environment domain>`. Deriving it
// here means the harness is never told the address by hand.
var mcpUrl = 'http://${mcpAppName}.internal.${environment.properties.defaultDomain}/mcp'

resource mcp 'Microsoft.App/containerApps@2024-03-01' = {
  name: mcpAppName
  location: location
  identity: identityBlock
  dependsOn: [
    acrPull
  ]
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8765
        transport: 'http'
        // Traffic never leaves the environment and the server speaks plain HTTP.
        allowInsecure: true
      }
      registries: registryBlock
      secrets: [
        {
          name: 'database-url'
          value: databaseUrl
        }
        {
          name: 'database-url-direct'
          value: databaseUrlDirect
        }
        {
          name: 'openai-api-key'
          value: openaiApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'content-data'
          image: fullImage
          command: [
            'content-studio-server'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'MCP_HOST'
              value: '0.0.0.0'
            }
            {
              name: 'MCP_PORT'
              value: '8765'
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'DATABASE_URL_DIRECT'
              secretRef: 'database-url-direct'
            }
            {
              // Embeddings are written and searched from here — rule 3.
              name: 'OPENAI_API_KEY'
              secretRef: 'openai-api-key'
            }
          ]
        }
      ]
      scale: {
        // Sleeps when idle, which is the point of the whole topology. The server
        // runs stateless_http, so more than one replica stays safe.
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

resource harness 'Microsoft.App/containerApps@2024-03-01' = {
  name: harnessAppName
  location: location
  identity: identityBlock
  dependsOn: [
    acrPull
  ]
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: registryBlock
      // A declared secrets list is the whole truth to ARM: anything added out of
      // band is deleted on the next deployment. `az containerapp auth google
      // update` adds google-provider-authentication-secret that way, so leaving
      // it out here silently removed it and the Easy Auth sidecar then failed to
      // start - which fails the replica, not just sign-in. Carrying it through
      // the template keeps deploy.ps1 and enable-auth.ps1 from undoing each other.
      secrets: concat([
        {
          name: 'database-url'
          value: databaseUrl
        }
        {
          name: 'database-url-direct'
          value: databaseUrlDirect
        }
        {
          name: 'openai-api-key'
          value: openaiApiKey
        }
        {
          name: 'e2b-api-key'
          value: e2bApiKey
        }
        {
          // Empty is a supported state: `configure_phoenix` reads it, finds
          // nothing and reports the surface as off. See observability.py.
          name: 'phoenix-api-key'
          value: phoenixApiKey
        }
        {
          // Not an API key, but it does authorise ingestion into this
          // resource. Kept as a secret so it is redacted in the portal and in
          // `az containerapp show`, like everything else that grants anything.
          name: 'appinsights-connection-string'
          value: insights.properties.ConnectionString
        }
      ], empty(entraClientSecret) ? [] : [
        {
          // Named by Easy Auth's own convention: `auth openid-connect add
          // --client-secret-name` expects to find it here, already set. Unlike
          // the Google command, that one will not create it for you.
          name: 'entra-authentication-secret'
          value: entraClientSecret
        }
      ], empty(googleClientSecret) ? [] : [
        {
          name: 'google-provider-authentication-secret'
          value: googleClientSecret
        }
      ])
    }
    template: {
      containers: [
        {
          name: 'harness'
          image: fullImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              // Never 'development' here. auth.py already refuses it once it
              // detects Azure, but the value is set so nothing rests on detection.
              name: 'AUTH_MODE'
              value: 'azure'
            }
            {
              name: 'AUTH_ALLOWED_EMAILS'
              value: allowedEmails
            }
            {
              name: 'CLIENT_OWNER_EMAIL'
              value: clientOwnerEmail
            }
            {
              name: 'AUTH_SELF_PROVISION_PROVIDERS'
              value: selfProvisionProviders
            }
            {
              name: 'HARNESS_HOST'
              value: '0.0.0.0'
            }
            {
              name: 'MCP_URL'
              value: mcpUrl
            }
            {
              name: 'MODEL'
              value: model
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'DATABASE_URL_DIRECT'
              secretRef: 'database-url-direct'
            }
            {
              name: 'OPENAI_API_KEY'
              secretRef: 'openai-api-key'
            }
            {
              name: 'E2B_API_KEY'
              secretRef: 'e2b-api-key'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-connection-string'
            }
            {
              name: 'PHOENIX_COLLECTOR_ENDPOINT'
              value: phoenixCollectorEndpoint
            }
            {
              name: 'PHOENIX_PROJECT_NAME'
              value: phoenixProjectName
            }
            {
              name: 'PHOENIX_API_KEY'
              secretRef: 'phoenix-api-key'
            }
          ]
          probes: [
            {
              // /health answers 200 even when it reports `degraded`, so a cold
              // Neon compute cannot get the container restarted. Five failures
              // 30 s apart is two and a half minutes before that is believed.
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 20
              periodSeconds: 30
              timeoutSeconds: 10
              failureThreshold: 5
            }
          ]
        }
      ]
      scale: {
        // One replica, deliberately. A chat stream keeps its queue in the process
        // that started the run, and a second replica would answer the poll that
        // belongs to the first. One client, one process.
        minReplicas: 0
        maxReplicas: 1
        rules: [
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

output harnessUrl string = 'https://${harness.properties.configuration.ingress.fqdn}'
output harnessAppName string = harnessAppName
output mcpAppName string = mcpAppName
output mcpUrl string = mcpUrl
output environmentName string = environment.name
output insightsName string = insights.name

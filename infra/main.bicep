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

@description('Name of the existing Azure Container Registry that holds the image.')
param acrName string

@description('Repository and tag inside that registry, e.g. content-studio:20260819-2130.')
param image string

@description('Comma-separated e-mail allowlist. The harness refuses every address outside it.')
param allowedEmails string

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

@secure()
param e2bApiKey string

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
        {
          name: 'e2b-api-key'
          value: e2bApiKey
        }
      ]
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

targetScope = 'resourceGroup'

@description('Región de los recursos.')
param location string = resourceGroup().location

@description('Prefijo legible para los recursos.')
param baseName string = 'churn-radar'

@description('Crea o actualiza la aplicación después de publicar la imagen.')
param deployContainerApp bool = false

@description('Imagen OCI que ejecutará la API.')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Versión visible del modelo.')
param modelVersion string = 'bootstrap'

var suffix = uniqueString(resourceGroup().id)
var registryName = 'cr${suffix}'
var workspaceName = '${baseName}-logs'
var environmentName = '${baseName}-env'
var applicationName = '${baseName}-api'

resource workspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${baseName}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${baseName}-identity'
  location: location
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, workloadIdentity.id, 'acr-pull')
  scope: registry
  properties: {
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = if (deployContainerApp) {
  name: applicationName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workloadIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Multiple'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: workloadIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: containerImage
          env: [
            {
              name: 'MODEL_VERSION'
              value: modelVersion
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: applicationInsights.properties.ConnectionString
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 20
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '25'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [
    acrPull
  ]
}

output registryName string = registry.name
output registryLoginServer string = registry.properties.loginServer
output containerAppName string = applicationName
output containerAppUrl string = deployContainerApp
  ? 'https://${containerApp!.properties.configuration.ingress.fqdn}'
  : ''
output applicationInsightsName string = applicationInsights.name
output logAnalyticsWorkspaceName string = workspace.name

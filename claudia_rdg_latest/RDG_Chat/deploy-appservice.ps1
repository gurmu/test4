# ============================================================================
# Azure App Service (Linux) Multi-Container Deployment Script (GCC)
# ============================================================================
# Deploys teams-bot (public) + ivanti-api + nice-api (internal) to App Service
# via a docker-compose.yml compatible with Azure App Service.
# ============================================================================

$ErrorActionPreference = "Stop"

function Load-EnvFile {
    param([string]$Path = ".env")
    if (Test-Path $Path) {
        Write-Host "Loading environment variables from $Path..." -ForegroundColor Cyan
        Get-Content $Path | ForEach-Object {
            if ($_ -match '^([^#][^=]+)=(.*)$') {
                [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
            }
        }
    }
}

Load-EnvFile

# GCC cloud
az cloud set --name AzureUSGovernment
az login

if ($env:AZURE_SUBSCRIPTION_ID) {
    az account set --subscription $env:AZURE_SUBSCRIPTION_ID
}

$RESOURCE_GROUP = if ($env:RESOURCE_GROUP) { $env:RESOURCE_GROUP } else { "rg-itsm-multiagent" }
$LOCATION = if ($env:LOCATION) { $env:LOCATION } else { "usgovvirginia" }
$ACR_NAME = if ($env:ACR_NAME) { $env:ACR_NAME } else { "itsmacr$(Get-Date -Format 'yyyyMMddHHmmss')" }
$APP_SERVICE_PLAN = if ($env:APP_SERVICE_PLAN) { $env:APP_SERVICE_PLAN } else { "asp-itsm-multiagent" }
$WEBAPP_NAME = if ($env:WEBAPP_NAME) { $env:WEBAPP_NAME } else { "" }
$APP_SERVICE_SKU = if ($env:APP_SERVICE_SKU) { $env:APP_SERVICE_SKU } else { "B1" }
$TAG = Get-Date -Format "yyyyMMddHHmmss"

if (-not $WEBAPP_NAME) {
    Write-Host "Error: WEBAPP_NAME is required in .env" -ForegroundColor Red
    exit 1
}

Write-Host "============================================================================" -ForegroundColor Green
Write-Host "ITSM Multi-Agent App Service Deployment (GCC)" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Green
Write-Host "Resource Group: $RESOURCE_GROUP"
Write-Host "Location: $LOCATION"
Write-Host "ACR Name: $ACR_NAME"
Write-Host "App Service Plan: $APP_SERVICE_PLAN"
Write-Host "Web App Name: $WEBAPP_NAME"
Write-Host "Tag: $TAG"
Write-Host ""

# Resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

# ACR
$acrExists = az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP --query name -o tsv 2>$null
if (-not $acrExists) {
    az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic --location $LOCATION --admin-enabled true
}
$ACR_LOGIN_SERVER = az acr show --name $ACR_NAME --query loginServer -o tsv
$ACR_ID = az acr show --name $ACR_NAME --query id -o tsv

# Build and push
az acr login --name $ACR_NAME

docker build -t "${ACR_LOGIN_SERVER}/ivanti-api:${TAG}" -t "${ACR_LOGIN_SERVER}/ivanti-api:latest" -f src/api/ivanti/Dockerfile .
docker push "${ACR_LOGIN_SERVER}/ivanti-api:${TAG}"
docker push "${ACR_LOGIN_SERVER}/ivanti-api:latest"

docker build -t "${ACR_LOGIN_SERVER}/nice-api:${TAG}" -t "${ACR_LOGIN_SERVER}/nice-api:latest" -f src/api/nice_incontact/Dockerfile .
docker push "${ACR_LOGIN_SERVER}/nice-api:${TAG}"
docker push "${ACR_LOGIN_SERVER}/nice-api:latest"

docker build -t "${ACR_LOGIN_SERVER}/teams-bot:${TAG}" -t "${ACR_LOGIN_SERVER}/teams-bot:latest" -f Dockerfile .
docker push "${ACR_LOGIN_SERVER}/teams-bot:${TAG}"
docker push "${ACR_LOGIN_SERVER}/teams-bot:latest"

Write-Host "Images pushed:" -ForegroundColor Green
Write-Host "  ${ACR_LOGIN_SERVER}/teams-bot:${TAG}"
Write-Host "  ${ACR_LOGIN_SERVER}/ivanti-api:${TAG}"
Write-Host "  ${ACR_LOGIN_SERVER}/nice-api:${TAG}"

# App Service Plan
$planExists = az appservice plan show --name $APP_SERVICE_PLAN --resource-group $RESOURCE_GROUP --query name -o tsv 2>$null
if (-not $planExists) {
    az appservice plan create --name $APP_SERVICE_PLAN --resource-group $RESOURCE_GROUP --location $LOCATION --is-linux --sku $APP_SERVICE_SKU
}

# Web App
$webExists = az webapp show --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP --query name -o tsv 2>$null
if (-not $webExists) {
    az webapp create --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP --plan $APP_SERVICE_PLAN --deployment-container-image-name "mcr.microsoft.com/azure-app-service/samples/aspnethelloworld:latest"
}

# Managed Identity for ACR pull
$USE_ACR_ADMIN = $env:USE_ACR_ADMIN_CREDENTIALS
if ($USE_ACR_ADMIN -and $USE_ACR_ADMIN.ToLower() -eq "true") {
    Write-Host "WARNING: Using ACR admin credentials for image pull." -ForegroundColor Yellow
    $ACR_USERNAME = az acr credential show --name $ACR_NAME --query username -o tsv
    $ACR_PASSWORD = az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv
    az webapp config container set --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP `
        --docker-registry-server-url "https://${ACR_LOGIN_SERVER}" `
        --docker-registry-server-user $ACR_USERNAME `
        --docker-registry-server-password $ACR_PASSWORD
} else {
    $USER_ASSIGNED_IDENTITY_ID = $env:USER_ASSIGNED_IDENTITY_ID
    if ($USER_ASSIGNED_IDENTITY_ID) {
        az webapp identity assign --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP --identities $USER_ASSIGNED_IDENTITY_ID
        $principalId = az identity show --ids $USER_ASSIGNED_IDENTITY_ID --query principalId -o tsv
    } else {
        $principalId = az webapp identity assign --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP --query principalId -o tsv
    }
    az role assignment create --assignee-object-id $principalId --role AcrPull --scope $ACR_ID | Out-Null
}

# Compose file for App Service (replace ACR_LOGIN_SERVER and IMAGE_TAG)
$composeRaw = Get-Content docker-compose.yml -Raw
$composeRaw = $composeRaw -replace '\$\{ACR_LOGIN_SERVER\}', $ACR_LOGIN_SERVER
$composeRaw = $composeRaw -replace '\$\{IMAGE_TAG:-latest\}', $TAG
$composePath = "scripts/.compose.appservice.yml"
$composeRaw | Set-Content -Encoding UTF8 $composePath

az webapp config container set --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP `
    --multicontainer-config-type compose --multicontainer-config-file $composePath

# App settings
$settings = @(
    "WEBSITES_PORT=3978",
    "PORT=3978",
    "IVANTI_API_URL=http://ivanti-api:8000",
    "NICE_API_URL=http://nice-api:8001",
    "AZURE_AUTHORITY_HOST=$env:AZURE_AUTHORITY_HOST",
    "AZURE_OPENAI_ENDPOINT=$env:AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT=$env:AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION=$env:AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_API_KEY=$env:AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$env:AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_SEARCH_ENDPOINT=$env:AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_INDEX=$env:AZURE_SEARCH_INDEX",
    "AZURE_SEARCH_KEY=$env:AZURE_SEARCH_KEY",
    "KB_TOP_K=$env:KB_TOP_K",
    "KB_CONTENT_FIELD=$env:KB_CONTENT_FIELD",
    "KB_SEMANTIC_CONFIG=$env:KB_SEMANTIC_CONFIG",
    "COSMOSDB_ENDPOINT=$env:COSMOSDB_ENDPOINT",
    "COSMOSDB_KEY=$env:COSMOSDB_KEY",
    "COSMOSDB_DATABASE=$env:COSMOSDB_DATABASE",
    "COSMOSDB_CONTAINER=$env:COSMOSDB_CONTAINER",
    "MICROSOFT_APP_ID=$env:MICROSOFT_APP_ID",
    "MICROSOFT_APP_PASSWORD=$env:MICROSOFT_APP_PASSWORD",
    "BOT_TYPE=$env:BOT_TYPE",
    "APP_MSI_RESOURCE_ID=$env:APP_MSI_RESOURCE_ID",
    "BOT_FRAMEWORK_CHANNEL_SERVICE=$env:BOT_FRAMEWORK_CHANNEL_SERVICE",
    "BOT_FRAMEWORK_OAUTH_URL=$env:BOT_FRAMEWORK_OAUTH_URL"
)

az webapp config appsettings set --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP --settings $settings

az webapp restart --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP

Write-Host "============================================================================" -ForegroundColor Green
Write-Host "Deployment Complete" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Green
Write-Host "Messaging Endpoint:" -ForegroundColor Cyan
Write-Host "https://${WEBAPP_NAME}.azurewebsites.us/api/messages"
Write-Host "Health Endpoint:" -ForegroundColor Cyan
Write-Host "https://${WEBAPP_NAME}.azurewebsites.us/health"
Write-Host ""
Write-Host "Logs:" -ForegroundColor Green
Write-Host "az webapp log tail --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP"

Remove-Item $composePath -ErrorAction SilentlyContinue

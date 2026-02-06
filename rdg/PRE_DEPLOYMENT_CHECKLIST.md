# Pre-Deployment Checklist (Azure GCC)

## Required Configuration

- `AZURE_AUTHORITY_HOST` = `https://login.microsoftonline.us`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_SEARCH_ENDPOINT`
- `AZURE_SEARCH_INDEX`
- `MICROSOFT_APP_ID`
- `MICROSOFT_APP_PASSWORD` (leave empty for Managed Identity)
- `BOT_TYPE` = `User-Assigned Managed Identity`
- `APP_MSI_RESOURCE_ID`
- `BOT_FRAMEWORK_CHANNEL_SERVICE`
- `BOT_FRAMEWORK_OAUTH_URL`

## Managed Identity

- Managed identity enabled on the compute
- RBAC granted for Azure OpenAI and Azure AI Search

## Deployment

- `RESOURCE_GROUP`
- `LOCATION` (GCC region, e.g., `usgovvirginia`)
- `ACR_NAME` (if deploying to ACR)

## Quick Validation

1. Run `python src/main.py` with a known ITSM query.
2. Confirm the response cites KB content or returns `NO_KB_MATCH`.



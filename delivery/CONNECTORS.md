# Tenant connector setup

No connector credentials are accepted through the operator API. Inject `GROWTH_CONNECTOR_PROFILES` from Secrets Manager or an equivalent approved vault as JSON. Prefer one credential template per tenant; separately register each pseudonymous customer's provider IDs using `PUT /v2/identity-bindings` with a verified tenant admin token. The identity record is protected by RLS and an execution-time version check. Never use real customer identities in CI or development fixtures.

A template has `tenantId`, `region`, `salesforce`, `adobe`, `shopify`, and `allowSandboxTaskWrites` (false by default). The `salesforce` object needs sandbox `baseUrl` and `accessToken`; optional `apiVersion` defaults to v65.0. The `adobe` object needs `accessToken`, `apiKey`, `organizationId`, named non-production `sandbox`, `purposeEligibilityPaths`, and `advertisingConsentPath`. The `shopify` object needs `shop` (subdomain only), `accessToken`, and optionally `webhookSecret`; API version defaults to 2026-10.

Adobe purpose mappings are explicit client-approved boolean paths, for example `"purposeEligibilityPaths":{"lead_qualification":["_brand","leadPurposeAllowed"]}`. Missing, nonboolean or false values deny the purpose before Salesforce or Shopify context is read. Email also requires `consents.marketing.any.val` and `consents.marketing.email.val` equal `y`. Advertising requires a dedicated true CMP field at `advertisingConsentPath`; sharing consent never substitutes for it. Field mappings and lawful-purpose rules require tenant privacy approval.

An identity binding has `customerRef`, `region`, `salesforceContact` (15/18-character Contact ID), `adobeProfile`, `shopifyCustomer` (Customer GID), and `shopifyVariants` (ProductVariant GIDs). Provider credentials are deliberately absent. Update bindings through the API so customer guards, audit and execution-time version invalidation apply.

## Provider prerequisites

Salesforce: use an approved sandbox `*.sandbox.my.salesforce.com` with read access to Contact, Case and Task, including numeric `Growth_Fit_Score__c` and `Growth_Engagement_Score__c`. To permit internal tasks, explicitly set `allowSandboxTaskWrites:true` and create Task field `Growth_Action_Key__c` as a **unique external ID**. The adapter verifies its describe metadata before writing, uses fixed task fields and reconciles by that key. It cannot update opportunity stages or production orgs. Provision least-privilege OAuth credentials and rotate them through the vault; automatic token renewal is external to this adapter.

Adobe: provision Profile Access read permissions for the named sandbox and tenant-approved XDM purpose/consent fields. The adapter reads profiles; it does not claim that a profile read or audience request confirms delivery. Activation needs an independently approved bridge implementing the HTTP executor below and a delivery/experiment measurement contract before a live pilot.

Shopify: use a development store with approved customer/order/product/inventory scopes and protected customer-data permissions. The adapter uses GraphQL queries only. Configure an orders/create webhook at `/v2/webhooks/shopify/orders`; HMAC and shop/customer identity mapping are verified before storing pseudonymous order evidence. Order evidence suppresses recovery even if it precedes abandonment. No price, discount, customer-message or order mutation is supported.

## HTTP execution bridge

Set `GROWTH_SANDBOX_URL`, `GROWTH_SANDBOX_ALLOWED_HOSTS`, and secret `GROWTH_SANDBOX_BINDINGS` mapping a bearer token to `{tenantId,region}`. Regional enterprise mode requires HTTPS; redirects are disabled. The bridge supports tenant-scoped `POST /execute` and `POST /status` with the same stable action key, fixed tool/payload and full verified scope. Status must return authoritative accepted/not-found/unknown evidence. It must atomically deduplicate effects and never infer not-found from an unknown timeout. See `src/growth/enterprise/sandbox.py` for the runnable synthetic protocol and `tests/enterprise/` for adapter contract tests.

Without native task writes, effects route to the configured bridge or independent synthetic adapter. The console labels those capabilities; synthetic receipts are not evidence of real provider acceptance. Do not enable real messaging, spend or price mutation through a bridge without approved controls.

## Regional source and model configuration

`GROWTH_SOURCE_BINDINGS` binds each trusted producer subject to a tenant and region. Broker ACLs must prevent untrusted publishers from impersonating these source identities. Deploy an isolated regional topic/cluster and regional Temporal namespace per data boundary; a body field cannot override the verified JWT or broker binding. Provision tenant policy with a platform administrator and restrict allowed purposes/domains and action limits before ingestion.

Optional model advice requires `GROWTH_MODEL_PROVIDER=openai_compatible`, HTTPS allowlisted `GROWTH_MODEL_BASE_URL`, `GROWTH_MODEL_NAME`, a secret API key and `GROWTH_MODEL_REGION` equal to runtime region. The model receives bounded nonidentifying facts after eligibility checks. Malformed or unavailable advice falls back deterministically. Configure a provider with independently verified regional processing and retention; a configured region string is not proof of provider residency.

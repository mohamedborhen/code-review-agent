import { apiFetch } from "./client";
import type { JiraCredentialRequest, JiraCredentialResponse, JiraValidateResponse } from "../types/api";

// POST /api/v1/integrations/jira/validate — probe, never stores
// §2: tests the Basic header round-trip with Jira
export async function validateJira(
  body: JiraCredentialRequest,
): Promise<JiraValidateResponse> {
  return apiFetch<JiraValidateResponse>("/integrations/jira/validate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// POST /api/v1/integrations/jira — save encrypted server-side
// §2: credentials are Fernet-encrypted, write-only, never returned
export async function storeJiraCredentials(
  body: JiraCredentialRequest,
): Promise<JiraCredentialResponse> {
  return apiFetch<JiraCredentialResponse>("/integrations/jira", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

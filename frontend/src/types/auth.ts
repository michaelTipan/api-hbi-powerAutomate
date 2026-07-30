/** Tipos alineados al contrato UI + bootstrap auth. */

export type UiAuthMode = "mock" | "entra" | "local_session";

export interface UiBootstrapResponse {
  ui_enabled: boolean;
  writes_allowed: boolean;
  active_environment: string;
  display_label: string;
  auth_mode: UiAuthMode | string;
  login_required: boolean;
  entra_authority?: string;
  entra_spa_client_id?: string;
  entra_api_scope?: string;
}

export interface UiMeResponse {
  authenticated: boolean;
  username: string;
  role: string;
  auth_mode: string;
  expires_at: string;
}

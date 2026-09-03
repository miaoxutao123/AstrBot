export type AdapterField = {
  name: string;
  label: string;
  label_key?: string;
  type: 'text' | 'password' | 'url' | 'select';
  required?: boolean;
  secret?: boolean;
  default?: string;
};

export type AdapterType = { type: string; name: string; auth_mode: string; fields: AdapterField[] };

function key(): string { return sessionStorage.getItem('gateway-api-key') || ''; }

export async function gatewayApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/v1${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${key()}`, 'Content-Type': 'application/json', ...init.headers }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error?.message || `Gateway request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function setGatewayKey(value: string): void { sessionStorage.setItem('gateway-api-key', value); }

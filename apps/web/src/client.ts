export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function mutationHeaders() {
  return {
    "Idempotency-Key": crypto.randomUUID(),
    "X-CSRF-Token":
      document.cookie
        .split("; ")
        .find((c) => c.startsWith("forget_lah_csrf="))
        ?.split("=")[1] ?? "",
  };
}

export function modelLabel(mode: string) {
  return mode === "mock" ? "Simulation mode" : mode === "anthropic" ? "Direct Claude API mode" : "Organiser model mode";
}

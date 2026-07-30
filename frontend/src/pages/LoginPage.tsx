import { useState } from "react";
import type { FormEvent } from "react";
import { loginLocal } from "../api/client";

export function LoginPage({
  displayLabel,
  onSuccess,
}: {
  displayLabel: string;
  onSuccess: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await loginLocal(username, password);
      setPassword("");
      onSuccess();
    } catch (err) {
      setPassword("");
      setError(
        err instanceof Error
          ? err.message
          : "No se pudo iniciar sesión.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-panel">
      <p className="brand">HBI Capital</p>
      <h1>Acceso operativo</h1>
      <p className="muted">
        Sesión local segura · {displayLabel || "SANDBOX / PRUEBAS"}
      </p>
      <form className="login-form" onSubmit={onSubmit} autoComplete="off">
        <label>
          Usuario
          <input
            name="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Contraseña
          <input
            name="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error ? <p className="login-error">{error}</p> : null}
        <button type="submit" disabled={busy}>
          {busy ? "Validando…" : "Entrar"}
        </button>
      </form>
    </main>
  );
}

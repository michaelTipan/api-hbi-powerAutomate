import { useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { loginLocal } from "../api/client";
import { LoadingButton } from "../components/LoadingButton";

export function LoginPage({
  displayLabel,
  onSuccess,
}: {
  displayLabel: string;
  onSuccess: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLockOn, setCapsLockOn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function checkCapsLock(event: KeyboardEvent<HTMLInputElement>) {
    if (typeof event.getModifierState === "function") {
      setCapsLockOn(event.getModifierState("CapsLock"));
    }
  }

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
        <label htmlFor="login-username">
          Usuario
          <input
            id="login-username"
            name="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label htmlFor="login-password">
          Contraseña
          <span className="password-field">
            <input
              id="login-password"
              name="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={checkCapsLock}
              onKeyUp={checkCapsLock}
              autoComplete="current-password"
              required
            />
            <button
              type="button"
              className="password-toggle"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-pressed={showPassword}
              aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
            >
              {showPassword ? "Ocultar" : "Mostrar"}
            </button>
          </span>
        </label>
        {capsLockOn && (
          <p className="caps-lock-hint" role="status">
            Bloq Mayús está activado.
          </p>
        )}
        {error ? <p className="login-error">{error}</p> : null}
        <LoadingButton type="submit" busy={busy} busyLabel="Validando…">
          Entrar
        </LoadingButton>
      </form>
    </main>
  );
}

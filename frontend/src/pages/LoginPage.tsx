import { useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { loginLocal } from "../api/client";
import { LoadingButton } from "../components/LoadingButton";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function LoginPage({
  displayLabel,
  onSuccess,
}: {
  displayLabel: string;
  onSuccess: () => void | Promise<void>;
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
      await onSuccess();
      setPassword("");
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
    <main className="login-page">
      <Card className="login-card w-full max-w-md border-zinc-300 bg-white shadow-lg">
        <CardHeader className="text-center border-b border-zinc-100 pb-4">
          <p className="text-sm font-bold uppercase tracking-widest text-[#0e121b]">
            HBI Capital
          </p>
          <CardTitle className="text-2xl font-bold">Acceso operativo</CardTitle>
          <CardDescription>
            Sesión local segura · {displayLabel || "Entorno de validación"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="login-form space-y-4" onSubmit={onSubmit} autoComplete="off">
            <label className="block text-sm font-medium text-zinc-700" htmlFor="login-username">
              Usuario
              <input
                id="login-username"
                name="username"
                className="mt-1 w-full min-h-11 rounded-md border border-zinc-300 px-3 py-2"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="block text-sm font-medium text-zinc-700" htmlFor="login-password">
              Contraseña
              <span className="password-field mt-1 flex gap-2">
                <input
                  id="login-password"
                  name="password"
                  className="w-full min-h-11 rounded-md border border-zinc-300 px-3 py-2"
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
                  className="password-toggle min-h-11 rounded-md border border-zinc-200 px-3 text-sm"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-pressed={showPassword}
                  aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                >
                  {showPassword ? "Ocultar" : "Mostrar"}
                </button>
              </span>
            </label>
            {capsLockOn && (
              <p className="caps-lock-hint text-sm text-amber-700" role="status">
                Bloq Mayús está activado.
              </p>
            )}
            {error ? <p className="login-error text-sm text-red-600">{error}</p> : null}
            <LoadingButton type="submit" busy={busy} busyLabel="Validando…" className="w-full">
              Entrar
            </LoadingButton>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}

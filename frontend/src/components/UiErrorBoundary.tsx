import { Component, type ErrorInfo, type ReactNode } from "react";
import { Link } from "react-router-dom";

type Props = { children: ReactNode };
type State = { hasError: boolean; message: string };

/**
 * Evita pantalla en blanco si un render lanza (datos incompletos / keys inválidas).
 * El operador puede volver al dashboard y reintentar sin recargar el navegador.
 */
export class UiErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: "" };

  static getDerivedStateFromError(error: unknown): State {
    const message =
      error instanceof Error && error.message.trim()
        ? error.message
        : "La interfaz encontró un error inesperado al mostrar esta pantalla.";
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("UiErrorBoundary", error, info.componentStack);
  }

  private handleRetry = (): void => {
    this.setState({ hasError: false, message: "" });
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }
    return (
      <section className="panel">
        <Link className="back" to="/">
          ← Volver al dashboard
        </Link>
        <div className="error-box" role="alert">
          <strong>No se pudo mostrar esta vista</strong>
          <p style={{ margin: "0.35rem 0" }}>{this.state.message}</p>
          <p className="meta">
            Corrija el dato o la ruta e intente de nuevo. La API no se ve afectada.
          </p>
        </div>
        <div className="actions">
          <button className="btn primary" type="button" onClick={this.handleRetry}>
            Reintentar vista
          </button>
          <Link className="btn" to="/">
            Ir al dashboard
          </Link>
        </div>
      </section>
    );
  }
}

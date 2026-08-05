import type { Page } from "@playwright/test";

export class LoginPageObject {
  constructor(private readonly page: Page) {}

  async goto() {
    await this.page.goto("./");
  }

  async login(username: string, password: string) {
    await this.page.locator("#login-username").fill(username);
    await this.page.locator("#login-password").fill(password);
    await this.page.getByRole("button", { name: "Entrar" }).click();
  }

  heading() {
    return this.page.getByRole("heading", { name: "Acceso operativo" });
  }

  errorMessage() {
    return this.page.locator(".login-error");
  }
}

export class DashboardPageObject {
  constructor(private readonly page: Page) {}

  async goto() {
    await this.page.goto("./");
  }

  title() {
    return this.page.getByRole("heading", { name: "Panel" });
  }

  bankSelect() {
    return this.page.locator("#new-process-bank");
  }

  generateButton() {
    return this.page.getByRole("button", { name: "Iniciar validación" });
  }

  processCard(processKey: string) {
    return this.page.locator(`a[href*="${encodeURIComponent(processKey)}"]`).first();
  }

  sidebarLink(name: "Panel" | "Historial") {
    return this.page.getByRole("link", { name });
  }
}

export class ProcessDetailPageObject {
  constructor(private readonly page: Page) {}

  async goto(processKey: string, query = "") {
    const q = query ? `?${query}` : "";
    await this.page.goto(`./processes/${encodeURIComponent(processKey)}${q}`);
  }

  phaseHeading() {
    return this.page.locator("#current-phase-title");
  }

  actionButton(label: string) {
    return this.page.getByRole("button", { name: label, exact: true });
  }

  confirmDialog(title: string) {
    return this.page.getByRole("dialog").filter({ hasText: title });
  }

  confirmButton(label = "Confirmar") {
    return this.page.getByRole("button", { name: label });
  }

  banner(title: string) {
    return this.page.getByRole("alert").filter({ hasText: title });
  }
}

export class HistoryPageObject {
  constructor(private readonly page: Page) {}

  async goto() {
    await this.page.goto("./historial");
  }

  title() {
    return this.page.getByRole("heading", { name: "Historial" });
  }
}

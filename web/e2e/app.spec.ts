import { test, expect } from "@playwright/test";

const feed = {
  events: [{ task: "Called dentist", category: "phone", completed_at: "2026-06-09T00:00:00Z", sat_for_hours: 5, orchestrator: null }],
  active: [{ id: "t1", task: "Replace fan", category: "chore", sat_for_hours: 120, plan: null }]
};

test("read, capture, and complete against a mocked API", async ({ page }) => {
  // seed the token before the app loads
  await page.addInitScript(() => localStorage.setItem("sidekick.settings", JSON.stringify({ token: "test", apiBase: "" })));

  let created = false, completed = false;
  await page.route("**/api/feed", r => r.fulfill({ json: feed }));
  await page.route("**/api/me", r => r.fulfill({ json: { name: "dalton", role: "full" } }));
  await page.route("**/api/tasks", r => {
    if (r.request().method() !== "POST") { r.continue(); return; }
    created = true;
    r.fulfill({ status: 201, json: { id: "t2", task: "Buy milk", category: "errand", sat_for_hours: 0, plan: null } });
  });
  await page.route("**/api/tasks/*/complete", r => { completed = true; r.fulfill({ json: { id: "t1", status: "done", completed_at: "x", sat_for_hours: 1, already_done: false } }); });

  await page.goto("/");
  await expect(page.getByText("Replace fan")).toBeVisible();
  await expect(page.getByText("Called dentist")).toBeVisible();

  // capture
  await page.goto("/new");
  await page.getByLabel(/title/i).fill("Buy milk");
  await page.getByLabel(/category/i).selectOption("errand");
  await page.getByRole("button", { name: /capture/i }).click();
  await expect.poll(() => created).toBe(true);
  await expect(page).toHaveURL("/");   // wait for the post-capture navigation to land

  // complete
  await page.getByRole("button", { name: /done/i }).click();
  await expect.poll(() => completed).toBe(true);
});

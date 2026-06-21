import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// SvelteKit's $app/environment is not provided by Vitest — stub it so modules
// that import `browser` work in tests.
vi.mock("$app/environment", () => ({ browser: true, dev: true, building: false }));

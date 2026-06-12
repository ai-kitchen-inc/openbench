import { apiPath, API_BASE_URL } from "./api";

describe("apiPath", () => {
  it("keeps same-origin paths when no backend URL is configured", () => {
    expect(API_BASE_URL).toBe("");
    expect(apiPath("/persona")).toBe("/persona");
    expect(apiPath("skills")).toBe("/skills");
  });

  it("does not rewrite absolute URLs", () => {
    expect(apiPath("https://api.example.com/health")).toBe("https://api.example.com/health");
  });
});

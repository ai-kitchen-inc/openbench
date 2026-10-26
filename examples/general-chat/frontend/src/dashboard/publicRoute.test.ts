import { matchPublicDashboardRoute } from "./publicRoute";

describe("matchPublicDashboardRoute", () => {
  it("matches 12-hex ids with or without a trailing slash", () => {
    expect(matchPublicDashboardRoute({ pathname: "/d/abcdef123456" })).toEqual({
      dashboardId: "abcdef123456",
    });
    expect(matchPublicDashboardRoute({ pathname: "/d/abcdef123456/" })).toEqual({
      dashboardId: "abcdef123456",
    });
  });

  it("rejects other paths", () => {
    expect(matchPublicDashboardRoute({ pathname: "/" })).toBeNull();
    expect(matchPublicDashboardRoute({ pathname: "/d/abcdef123456/data" })).toBeNull();
    expect(matchPublicDashboardRoute({ pathname: "/d/ABCDEF123456" })).toBeNull();
    expect(matchPublicDashboardRoute({ pathname: "/d/short" })).toBeNull();
    expect(matchPublicDashboardRoute({ pathname: "/embed/agen" })).toBeNull();
  });
});

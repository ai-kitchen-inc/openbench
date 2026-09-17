import { matchEmbedRoute } from "./embedRoute";

describe("matchEmbedRoute", () => {
  it("matches /embed/<id> with key and theme", () => {
    expect(
      matchEmbedRoute({ pathname: "/embed/analis-keuangan", search: "?key=k-1&theme=dark" }),
    ).toEqual({ agentId: "analis-keuangan", embedKey: "k-1", theme: "dark" });
  });

  it("tolerates a trailing slash and missing params", () => {
    expect(matchEmbedRoute({ pathname: "/embed/hr/", search: "" })).toEqual({
      agentId: "hr",
      embedKey: "",
      theme: null,
    });
    expect(matchEmbedRoute({ pathname: "/embed/hr", search: "?theme=neon" })?.theme).toBeNull();
  });

  it("ignores every other path", () => {
    expect(matchEmbedRoute({ pathname: "/", search: "" })).toBeNull();
    expect(matchEmbedRoute({ pathname: "/embed/", search: "" })).toBeNull();
    expect(matchEmbedRoute({ pathname: "/embed/Bad_Id", search: "" })).toBeNull();
    expect(matchEmbedRoute({ pathname: "/embed/a/b", search: "" })).toBeNull();
  });
});

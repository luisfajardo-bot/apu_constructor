import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import SubApuBadge from "./SubApuBadge";

test("renderiza el chip APU", () => {
  render(<SubApuBadge />);
  expect(screen.getByText("APU")).toBeTruthy();
});

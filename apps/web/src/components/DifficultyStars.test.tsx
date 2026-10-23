import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DifficultyStars } from "./DifficultyStars";

describe("DifficultyStars", () => {
  it.each([1, 2, 3, 4, 5])("shows %i gold stars out of five filled stars", (difficulty) => {
    render(<DifficultyStars difficulty={difficulty} />);

    const rating = screen.getByRole("img", { name: `难度 ${difficulty} 星，共 5 星` });
    expect(rating).toHaveTextContent("★★★★★");
    expect(rating.querySelectorAll(".difficulty-stars__star")).toHaveLength(5);
    expect(rating.querySelectorAll(".difficulty-stars__star--active")).toHaveLength(difficulty);
  });

  it("does not invent a rating for invalid data", () => {
    render(<DifficultyStars difficulty={0} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

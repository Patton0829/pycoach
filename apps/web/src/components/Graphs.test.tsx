import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorGraph } from "./ErrorGraph";
import { PersonalKnowledgeGraph } from "./PersonalKnowledgeGraph";

describe("graph components", () => {
  it("renders student-visible graph labels and statuses", () => {
    render(
      <>
        <PersonalKnowledgeGraph
          nodes={[
            {
              id: "python.iterator.next",
              label: "next()",
              displayStatus: "正在学习",
            },
          ]}
        />
        <ErrorGraph
          nodes={[
            {
              id: "iter_vs_next",
              label: "iter 与 next 混淆",
              displayStatus: "需要巩固",
            },
          ]}
        />
      </>,
    );

    expect(screen.getByText("next()")).toBeInTheDocument();
    expect(screen.getByText("正在学习")).toBeInTheDocument();
    expect(screen.getByText("iter 与 next 混淆")).toBeInTheDocument();
    expect(screen.getByText("需要巩固")).toBeInTheDocument();
  });
});

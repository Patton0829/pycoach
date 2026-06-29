import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "./MarkdownContent";

describe("MarkdownContent", () => {
  it("renders markdown and highlights Python code", () => {
    const { container } = render(
      <MarkdownContent
        content={"**回答正确**\n\n```python\nnext(iterator)\n```"}
      />,
    );

    expect(screen.getByText("回答正确")).toHaveTextContent("回答正确");
    const code = container.querySelector("code");
    expect(code).toHaveClass("hljs", "language-python");
    expect(code).toHaveTextContent("next(iterator)");
  });
});

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

  it("converts escaped newlines in assistant prose", () => {
    const { container } = render(
      <MarkdownContent content={"回答错误。\\n\\n正确答案是 B。"} />,
    );

    expect(container.querySelectorAll("p")).toHaveLength(2);
    expect(screen.getByText("回答错误。")).toBeInTheDocument();
    expect(screen.getByText("正确答案是 B。")).toBeInTheDocument();
  });

  it("spreads compact multiple choice options into separate blocks", () => {
    const { container } = render(
      <MarkdownContent content={"表达式结果是什么？ A. 3.4 B. 3 C. 2 D. 4"} />,
    );

    expect(container.querySelectorAll("p")).toHaveLength(5);
    expect(screen.getByText("A. 3.4")).toBeInTheDocument();
    expect(screen.getByText("B. 3")).toBeInTheDocument();
    expect(screen.getByText("C. 2")).toBeInTheDocument();
    expect(screen.getByText("D. 4")).toBeInTheDocument();
  });

  it("keeps escaped newlines inside fenced code unchanged", () => {
    const { container } = render(
      <MarkdownContent content={"```python\nvalue = \"A\\nB\"\n```"} />,
    );

    expect(container.querySelector("code")).toHaveTextContent("A\\nB");
  });
});

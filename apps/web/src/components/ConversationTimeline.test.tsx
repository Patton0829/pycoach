import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConversationTimeline } from "./ConversationTimeline";
import { selectCurrentRoundMessages } from "../types/session";

describe("ConversationTimeline", () => {
  it("renders messages in conversation order", () => {
    render(
      <ConversationTimeline
        messages={[
          {
            id: "q1",
            role: "questioner",
            contentMarkdown: "第一道题",
          },
          {
            id: "s1",
            role: "student",
            contentMarkdown: "我的答案",
          },
          {
            id: "c1",
            role: "critic",
            contentMarkdown: "反馈内容",
          },
        ]}
      />,
    );

    const messages = screen.getAllByRole("article");
    expect(messages).toHaveLength(3);
    expect(messages[0]).toHaveTextContent("第一道题");
    expect(messages[1]).toHaveTextContent("我的答案");
    expect(messages[2]).toHaveTextContent("反馈内容");
  });

  it("selects only the latest learning round", () => {
    const messages = selectCurrentRoundMessages([
      {
        id: "q1",
        role: "questioner",
        contentMarkdown: "第一道题",
      },
      {
        id: "c1",
        role: "critic",
        contentMarkdown: "第一题反馈",
      },
      {
        id: "q2",
        role: "questioner",
        contentMarkdown: "第二道题",
      },
      {
        id: "s2",
        role: "student",
        contentMarkdown: "第二题答案",
      },
    ]);

    expect(messages.map((message) => message.id)).toEqual(["q2", "s2"]);
  });
});

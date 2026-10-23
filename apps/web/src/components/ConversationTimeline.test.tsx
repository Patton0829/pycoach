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

  it("shows only public question metadata on Questioner messages", () => {
    const metadata = {
      difficulty: 1,
      knowledge_points: [{ id: "python.iterator.next", name: "next()" }],
      source: {
        title: "Python 样题",
        document_type: "sample_exam" as const,
        exam_year: null,
        question_number: "3",
        pdf_pages: [1, 2],
      },
      critic_content: { reference_answer: "内部参考答案绝不能显示" },
    };
    render(
      <ConversationTimeline
        messages={[
          { id: "q", role: "questioner", contentMarkdown: "请作答", questionMetadata: metadata },
          { id: "s", role: "student", contentMarkdown: "我的回答", questionMetadata: metadata },
        ]}
      />,
    );

    expect(screen.getAllByRole("group", { name: "题目信息" })).toHaveLength(1);
    expect(screen.getByRole("img", { name: "难度 1 星，共 5 星" })).toBeInTheDocument();
    expect(screen.getByText("知识点：next()")).toBeInTheDocument();
    expect(screen.getByText(/来源：Python 样题.*第 3 题.*PDF 第 1、2 页/)).toBeInTheDocument();
    expect(screen.queryByText(/内部参考答案绝不能显示|reference_answer|python.iterator.next/)).not.toBeInTheDocument();
  });
});

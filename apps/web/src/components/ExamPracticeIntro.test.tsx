import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExamPracticeIntro } from "./ExamPracticeIntro";

const paper = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Python 样题及参考答案",
  document_type: "sample_exam",
  exam_year: null,
  available_question_count: 7,
  excluded_question_count: 2,
  question_types: ["multiple_choice", "programming"],
};

function renderIntro() {
  const onStart = vi.fn();
  const onContinue = vi.fn();
  render(
    <ExamPracticeIntro
      onStart={onStart}
      onContinue={onContinue}
      canContinue={false}
      disabled={false}
    />,
  );
  return { onStart, onContinue };
}

describe("ExamPracticeIntro", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads source counts and starts the selected actual paper", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([paper]), { status: 200 })));
    const { onStart } = renderIntro();

    expect(await screen.findByRole("heading", { name: paper.title })).toBeInTheDocument();
    expect(screen.getByText("年份未标注")).toBeInTheDocument();
    expect(screen.getByText("样题")).toBeInTheDocument();
    expect(screen.getByText("7 道已审核题目")).toBeInTheDocument();
    expect(screen.getByText(/另有 2 道题/)).toBeInTheDocument();
    expect(screen.getByText("选择题 · 编程题")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: `开始 ${paper.title} 真题测试` }));
    expect(onStart).toHaveBeenCalledWith(paper.id);
  });

  it("keeps starting unavailable while the catalogue is loading", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    const { onStart } = renderIntro();
    expect(screen.getByRole("status")).toHaveTextContent("正在读取真题题库");
    expect(screen.queryByRole("button", { name: /开始/ })).not.toBeInTheDocument();
    expect(onStart).not.toHaveBeenCalled();
  });

  it("shows an empty state without inventing question counts", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
    renderIntro();
    expect(await screen.findByText(/暂无可用试卷/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /开始/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/27/)).not.toBeInTheDocument();
  });

  it("shows a public error without exposing server details", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("private database failure", { status: 500 })));
    renderIntro();
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法加载真题题库");
    expect(screen.queryByText(/private database failure/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /开始/ })).not.toBeInTheDocument();
  });

  it("does not start a paper whose reviewed question count is zero", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
      { ...paper, available_question_count: 0 },
    ]), { status: 200 })));
    const { onStart } = renderIntro();
    const start = await screen.findByRole("button", { name: `开始 ${paper.title} 真题测试` });
    await waitFor(() => expect(start).toBeDisabled());
    fireEvent.click(start);
    expect(onStart).not.toHaveBeenCalled();
  });
});

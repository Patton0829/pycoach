import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ChatComposer } from "./ChatComposer";

describe("ChatComposer", () => {
  it("sends with Enter and clears the input", () => {
    const onSend = vi.fn();
    render(<ChatComposer placeholder="输入答案" onSend={onSend} />);
    const input = screen.getByLabelText("学习输入");

    fireEvent.change(input, { target: { value: "next(iterator)" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    expect(onSend).toHaveBeenCalledWith("next(iterator)");
    expect(input).toHaveValue("");
  });

  it("restores focus after a submitted message finishes processing", async () => {
    function ComposerHarness() {
      const [disabled, setDisabled] = useState(false);
      return (
        <>
          <ChatComposer
            placeholder="输入答案"
            onSend={() => setDisabled(true)}
            disabled={disabled}
          />
          <button type="button" onClick={() => setDisabled(false)}>
            完成处理
          </button>
        </>
      );
    }

    render(<ComposerHarness />);
    const input = screen.getByLabelText("学习输入");
    input.focus();

    fireEvent.change(input, { target: { value: "B" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    expect(input).toBeDisabled();
    input.blur();
    fireEvent.click(screen.getByRole("button", { name: "完成处理" }));

    await waitFor(() => expect(input).toHaveFocus());
  });

  it("keeps a newline with Shift+Enter", () => {
    const onSend = vi.fn();
    render(<ChatComposer placeholder="输入答案" onSend={onSend} />);
    const input = screen.getByLabelText("学习输入");

    fireEvent.change(input, { target: { value: "第一行\n第二行" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("第一行\n第二行");
  });

  it("does not send when disabled", () => {
    const onSend = vi.fn();
    render(
      <ChatComposer
        placeholder="正在处理"
        onSend={onSend}
        disabled
      />,
    );

    expect(screen.getByLabelText("学习输入")).toBeDisabled();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("does not submit while Enter confirms an IME composition", () => {
    const onSend = vi.fn();
    render(<ChatComposer placeholder="输入答案" onSend={onSend} />);
    const input = screen.getByLabelText("学习输入");

    fireEvent.change(input, { target: { value: "那g" } });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, {
      key: "Enter",
      keyCode: 229,
      isComposing: true,
    });

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("那g");

    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("那g");
  });
});

import type { PropsWithChildren } from "react";

export function CodeBlock({ children }: PropsWithChildren) {
  return <pre className="code-block">{children}</pre>;
}


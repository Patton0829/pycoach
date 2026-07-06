import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";

function normalizeTextSegment(segment: string): string {
  return segment
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\/n/g, "\n")
    .replace(/([。！？?：:])\s+(A[.．、]\s)/g, "$1\n\n$2")
    .replace(/\s+(?=[B-D][.．、]\s)/g, "\n\n")
    .replace(/\n{3,}/g, "\n\n");
}

export function normalizeMarkdownContent(content: string): string {
  return content
    .split(/(```[\s\S]*?```)/g)
    .map((segment) =>
      segment.startsWith("```") ? segment : normalizeTextSegment(segment),
    )
    .join("");
}

export function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown rehypePlugins={[rehypeHighlight]}>
      {normalizeMarkdownContent(content)}
    </ReactMarkdown>
  );
}

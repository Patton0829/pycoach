import type { GraphNode } from "../types/session";

export function ErrorGraph({ nodes }: { nodes: GraphNode[] }) {
  return (
    <section>
      <h2>错误图谱</h2>
      <ul className="graph-list graph-list--errors">
        {nodes.length === 0 ? (
          <li className="graph-list__empty">暂未发现活跃错误</li>
        ) : (
          nodes.map((node) => (
            <li key={node.id}>
              <span>{node.label}</span>
              <small>{node.displayStatus}</small>
            </li>
          ))
        )}
      </ul>
    </section>
  );
}

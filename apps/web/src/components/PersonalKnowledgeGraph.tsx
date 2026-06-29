import type { GraphNode } from "../types/session";

export function PersonalKnowledgeGraph({ nodes }: { nodes: GraphNode[] }) {
  return (
    <section>
      <h2>个人知识图谱</h2>
      <ul className="graph-list">
        {nodes.length === 0 ? (
          <li className="graph-list__empty">等待图谱数据…</li>
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
